"""Run the national job-entry test on Modal: one candidate rank of one household part per container.

Each container holds this checkout (the commit it records) and the packages pinned in
scripts/modal-requirements.txt, the same frozen set scripts/modal_earnings_changes.py
uses, with the dataset baked into the image. It loads one of the frozen experiment's four
household parts, tests every in-scope candidate of one rank
(scripts/expanded_job_entry_national.py), and stops on any failed identity.

Results go to the Modal volume ``us-cliffs-2017-job-entry`` and into this checkout under
results/job_entry/ (person rows under per_person/, git-ignored). Only a complete pair is
published or installed: the container serializes the person rows, then the JSON record
that names them by a unique run id and hashes them, validates the pair, and uploads both
in one batch that may not overwrite. A failed container publishes nothing. Locally each
file goes in under a unique temporary name and is hard-linked into place, never over an
existing file (scripts/job_entry_outputs.py). A rank already written, here or on the
volume, is skipped, so a relaunch resumes.

The wage scope ``resolved`` tests every jurisdiction scripts/job_entry_wages.py resolves
and counts the others' candidates as deferred; ``states:MD,NY`` tests only those states,
once wages.json carries their rates.

usage:
  modal run scripts/modal_job_entry.py --check-only          # one container: environment and wage table
  modal run scripts/modal_job_entry.py --smoke [--smoke-households 150] [--smoke-seed 17]
  modal run scripts/modal_job_entry.py --plan-only [--parts 0,1,2,3] [--scope resolved]
  modal run --detach scripts/modal_job_entry.py [--parts 0,1,2,3] [--scope resolved]
      [--ranks 1,2] [--dry-run]
  modal run scripts/modal_job_entry.py --fetch               # install every complete pair on the volume
"""

from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]
REMOTE = "/repo"
VOLUME = "us-cliffs-2017-job-entry"
SKIP = {".venv", "logs", "__pycache__", ".hypothesis", ".pytest_cache", "per_person", "src", "paper"}
MEMORY_MIB = 32768
CPU = 2.0


def _skip(path: Path) -> bool:
    parts = Path(path).parts
    return bool(SKIP.intersection(parts)) or parts[:2] == ("results", "job_entry")


def _download() -> None:
    from huggingface_hub import hf_hub_download

    hf_hub_download("policyengine/populace-us", "populace_us_2024.h5", repo_type="dataset",
                    revision="populace-us-2024-spm-20260909")


# Read here only: inside a container this file sits elsewhere and the image is already built.
REQUIREMENTS = (ROOT / "scripts" / "modal-requirements.txt").read_text().split() if modal.is_local() else []

image = (
    modal.Image.debian_slim(python_version="3.13")
    .apt_install("git")
    .uv_pip_install(*REQUIREMENTS)
    .run_commands("git config --global --add safe.directory '*'", "git config --global core.fileMode false")
    .env({"OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2", "MKL_NUM_THREADS": "2"})
    .run_function(_download)
    .add_local_dir(ROOT, REMOTE, ignore=_skip)
)
app = modal.App("us-cliffs-2017-job-entry", image=image)
volume = modal.Volume.from_name(VOLUME, create_if_missing=True)


def _repo():
    root = REMOTE if not modal.is_local() else str(ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    from scripts import job_entry_outputs as out

    return out


def _read(path: str) -> bytes | None:
    try:
        return b"".join(volume.read_file(path))
    except FileNotFoundError:
        return None


def _volume_pair(json_rel: str, expect: dict) -> tuple[bytes, bytes] | None:
    """A complete pair already on the volume, None if absent; an incomplete one stops the run."""
    out = _repo()
    json_bytes = _read(json_rel)
    if json_bytes is None:
        return None
    csv_rel = json.loads(json_bytes)["rows"]["file"]
    csv_bytes = _read(csv_rel)
    if csv_bytes is None:
        raise RuntimeError(f"the volume holds {json_rel} without its rows {csv_rel}")
    out.validate_pair(json_bytes, csv_bytes, expect)
    return json_bytes, csv_bytes


def _packet(status: str, json_rel: str, json_bytes: bytes, csv_bytes: bytes) -> dict:
    record = json.loads(json_bytes)
    return dict(status=status, json_rel=json_rel, part=record["part"], rank=record["rank"],
                scope=record["scope"], json=base64.b64encode(json_bytes).decode(),
                csv=base64.b64encode(csv_bytes).decode())


@app.function(cpu=CPU, memory=MEMORY_MIB, timeout=6 * 3600,
              retries=modal.Retries(max_retries=1, initial_delay=10.0))
def run_rank(part: int, rank: int, scope: str, wages_sha256: str, expected_candidates: int | None = None,
             smoke_households: int = 0, smoke_seed: int = 17) -> dict:
    os.chdir(REMOTE)
    out = _repo()
    started = time.time()
    stem = out.smoke_stem(part, smoke_households, smoke_seed) if smoke_households else out.part_stem(part)
    json_rel = out.result_json(stem, scope, rank)
    expect = dict(part=part, rank=rank, scope=out.scope_tag(scope))
    existing = _volume_pair(json_rel, expect)
    if existing:
        return _packet("already written", json_rel, *existing)

    import scripts.expanded_job_entry_national as national

    provenance, table = national.provenance(wages_sha256)
    t = time.time()
    dataset = national.load_part(part)
    load_seconds = round(time.time() - t, 1)
    sample = None
    if smoke_households:
        dataset, sample = national.smoke_sample(dataset, smoke_households, smoke_seed)
    t = time.time()
    sim = national.build(dataset)
    build_seconds = round(time.time() - t, 1)
    rows, record = national.run_rank(sim, dataset, rank, table["rates"], scope, fresh=bool(smoke_households))
    tested = record["counts"]["sample_candidates_tested"]
    if expected_candidates is not None and tested != expected_candidates:
        raise RuntimeError(f"part {part} rank {rank}: {tested} candidates, the plan counted {expected_candidates}")
    run_id = out.new_run_id()
    csv_rel = out.result_csv(stem, scope, rank, run_id)
    record["timing_seconds"].update(load=load_seconds, build=build_seconds)
    extra = dict(
        part=part,
        smoke=bool(smoke_households),
        smoke_sample=None if not sample else dict(sample, seed=smoke_seed, part=part),
        run_id=run_id,
        provenance=provenance,
        container=dict(cpu=CPU, memory_mib=MEMORY_MIB),
        peak_memory_gib=national.peak_memory_gib(),
        seconds_total=round(time.time() - started, 1),
    )
    json_bytes, csv_bytes = national.write_pair(rows, record, csv_rel, extra)
    try:
        with volume.batch_upload(force=False) as batch:
            batch.put_file(io.BytesIO(csv_bytes), "/" + csv_rel)
            batch.put_file(io.BytesIO(json_bytes), "/" + json_rel)
    except FileExistsError:
        existing = _volume_pair(json_rel, expect)
        if existing:
            return _packet("already written", json_rel, *existing)
        raise
    return _packet("written", json_rel, json_bytes, csv_bytes)


@app.function(cpu=CPU, memory=MEMORY_MIB, timeout=2 * 3600)
def plan_part(part: int, scope: str, wages_sha256: str) -> dict:
    os.chdir(REMOTE)
    out = _repo()
    import scripts.expanded_job_entry_national as national

    started = time.time()
    provenance, table = national.provenance(wages_sha256)
    dataset = national.load_part(part)
    sim = national.build(dataset)
    plan = national.plan(sim, table["rates"], scope)
    return dict(part=part, scope=out.scope_tag(scope), plan=plan, provenance=provenance,
                peak_memory_gib=national.peak_memory_gib(), seconds=round(time.time() - started, 1))


@app.function(timeout=900)
def check() -> dict:
    os.chdir(REMOTE)
    _repo()
    from importlib import metadata

    from scripts.expanded_historical import historical_provenance
    from scripts.expanded_job_entry_national import code_record
    from scripts.job_entry_wages import national_wage_table

    table = national_wage_table()
    return dict(code=code_record(), historical=historical_provenance(),
                versions={p: metadata.version(p) for p in ("policyengine-us", "policyengine-core", "numpy", "pandas")},
                wages_json_sha256=table["wages_json_sha256"], resolved=len(table["rates"]),
                unresolved=table["unresolved"],
                medicaid_totals=Path("results/medicaid/totals_2017_p4_s0.json").exists())


def _uncommitted(files) -> str:
    return subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", *files, "cliffs2017"],
                          capture_output=True, text=True, check=True).stdout.strip()


def _install(packet: dict, log) -> None:
    out = _repo()
    state = out.install_pair(
        ROOT, packet["json_rel"], base64.b64decode(packet["json"]), base64.b64decode(packet["csv"]),
        expect=dict(part=packet["part"], rank=packet["rank"], scope=packet["scope"]),
    )
    log(f"part {packet['part']} rank {packet['rank']} {packet['scope']}: {packet['status']}; {state}")


def _fetch(log) -> None:
    out = _repo()
    try:
        entries = list(volume.iterdir(f"/{out.BASE}/parts", recursive=True))
    except (FileNotFoundError, modal.exception.NotFoundError):
        log("the volume holds no results yet")
        return
    for entry in entries:
        path = entry.path.lstrip("/")
        if entry.type != modal.volume.FileEntryType.FILE or not path.endswith(".json"):
            continue
        json_bytes = _read(path)
        try:
            record = json.loads(json_bytes)
            csv_bytes = _read(record["rows"]["file"])
            if csv_bytes is None:
                raise ValueError("its rows file is missing")
            state = out.install_pair(ROOT, path, json_bytes, csv_bytes)
        except (KeyError, ValueError) as error:
            state = f"skipped, not a complete pair: {error}"
        log(f"{path}: {state}")


@app.local_entrypoint()
def main(parts: str = "0,1,2,3", scope: str = "resolved", ranks: str = "", smoke: bool = False,
         smoke_households: int = 150, smoke_seed: int = 17, plan_only: bool = False,
         check_only: bool = False, fetch: bool = False, dry_run: bool = False):
    out = _repo()
    from scripts.job_entry_wages import national_wage_table

    logfile = ROOT / "logs" / "job_entry_modal.log"
    logfile.parent.mkdir(exist_ok=True)

    def log(message: str) -> None:
        import datetime

        line = f"{datetime.datetime.now(datetime.timezone.utc):%Y-%m-%dT%H:%M:%SZ} {message}"
        print(line, flush=True)
        with logfile.open("a") as handle:
            handle.write(line + "\n")

    if check_only:
        print(json.dumps(check.remote(), indent=1))
        return
    if fetch:
        _fetch(log)
        return
    table = national_wage_table()
    sha = table["wages_json_sha256"]
    for code, reason in table["unresolved"].items():
        log(f"unresolved wage, candidates deferred under scope 'resolved': {reason}")
    dirty = _uncommitted(out.CODE_FILES)
    if dirty:
        raise SystemExit(f"commit these first, so the recorded commit holds the code:\n{dirty}")
    if smoke:
        log(f"smoke: part 0 rank 1, {smoke_households} households, seed {smoke_seed}, scope {scope}")
        _install(run_rank.remote(0, 1, scope, sha, None, smoke_households, smoke_seed), log)
        return

    part_list = [int(p) for p in parts.split(",")]
    plans = {}
    for part in part_list:
        path = ROOT / out.plan_json(part, scope)
        if path.exists():
            plans[part] = json.loads(path.read_text())
    missing = [p for p in part_list if p not in plans]
    if missing:
        log(f"planning parts {missing} for scope {scope}")
        for result in plan_part.starmap([(p, scope, sha) for p in missing]):
            data = (json.dumps(result, indent=1) + "\n").encode()
            state = out.install_bytes(ROOT, out.plan_json(result["part"], scope), data)
            plans[result["part"]] = result
            log(f"plan part {result['part']}: {state}; {result['plan']['sample_candidates_by_rank']} "
                f"({result['seconds']} s, {result['peak_memory_gib']} GiB)")
    for part, record in plans.items():
        if record["provenance"]["wages_json_sha256"] != sha:
            raise SystemExit(f"wages.json changed since part {part}'s plan for scope {scope}")
    if plan_only:
        return
    wanted = {int(r) for r in ranks.split(",")} if ranks else None
    jobs = []
    for part in part_list:
        for k, n in sorted((int(k), n) for k, n in plans[part]["plan"]["sample_candidates_by_rank"].items()):
            if n and (wanted is None or k in wanted):
                if out.local_record(ROOT, out.result_json(out.part_stem(part), scope, k)) is None:
                    jobs.append((part, k, scope, sha, n))
    log(f"{len(jobs)} ranks to run: {[(j[0], j[1]) for j in jobs]}")
    if dry_run:
        return
    for result in run_rank.starmap(jobs, return_exceptions=True, wrap_returned_exceptions=False,
                                   order_outputs=False):
        if isinstance(result, BaseException):
            log(f"a container failed: {result!r}")
            continue
        _install(result, log)
