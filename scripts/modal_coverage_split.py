"""Run the coverage split on Modal: one scenario per container, then one aggregation per part.

Each container holds this checkout (its code checked against the launching commit's hashes)
and the frozen packages in scripts/modal-requirements.txt, with the dataset baked into the
image, as scripts/modal_job_entry.py and scripts/modal_combined_union.py build it.

- ``scenario`` reruns one test of one household part (scripts/coverage_split.job_scenario or
  raise_scenario) on the frozen inputs of the 51-jurisdiction union (run 1c0cc9dd), which
  the launcher reads from their checkouts, checks against that run's manifest and ships as
  bytes. It stops, publishing nothing, unless every tested adult's household change
  reproduces the saved row to $0.01.
- ``aggregate`` loads one part's frozen simulation and counts the classified flags with
  MicroSeries (scripts/coverage_split.aggregate_part), reproducing the union's strict totals.

Results go to the Modal volume ``us-cliffs-2017-coverage-split`` and into this checkout under
results/coverage_split/ (git-ignored). A scenario's record and its two row files are uploaded
in one batch that may not overwrite, and installed locally under unique temporary names
hard-linked into place, never over an existing file; a relaunch skips every scenario already
written here or on the volume.

usage:
  MODAL_PROFILE=policyengine modal run scripts/modal_coverage_split.py --stage smoke
  MODAL_PROFILE=policyengine modal run [--detach] scripts/modal_coverage_split.py --stage job [--parts 0,1,2,3]
  MODAL_PROFILE=policyengine modal run scripts/modal_coverage_split.py --stage fetch   # after --detach
  MODAL_PROFILE=policyengine modal run scripts/modal_coverage_split.py --stage raise
  python scripts/coverage_split.py classify
  MODAL_PROFILE=policyengine modal run scripts/modal_coverage_split.py --stage aggregate
  python scripts/coverage_split.py combine --tag TAG
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import io
import json
import os
import sys
import time
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]
REMOTE = "/repo"
APP = "us-cliffs-2017-coverage-split"
VOLUME = "us-cliffs-2017-coverage-split"
SKIP = {".venv", "logs", "__pycache__", ".hypothesis", ".pytest_cache", "per_person", "src", "paper", ".git"}
MEMORY_MIB = 32768
CPU = 2.0
DEFAULTS = {
    "job_root": "/Users/maxghenis/reviews/bootstraps-cliffs-2017-2026-11-09/expanded-analysis",
    "raise_rows_root": "/Users/maxghenis/PolicyEngine/us-cliffs-2017",
    "union_root": "/Users/maxghenis/reviews/bootstraps-cliffs-2017-2026-11-09/expanded-union",
}


def _skip(path: Path) -> bool:
    parts = Path(path).parts
    return bool(SKIP.intersection(parts)) or parts[:2] in {
        ("results", "job_entry"), ("results", "combined_union"), ("results", "coverage_split")}


def _download() -> None:
    from huggingface_hub import hf_hub_download

    hf_hub_download("policyengine/populace-us", "populace_us_2024.h5", repo_type="dataset",
                    revision="populace-us-2024-spm-20260909")


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
app = modal.App(APP, image=image)
volume = modal.Volume.from_name(VOLUME, create_if_missing=True)


def _out():
    root = REMOTE if not modal.is_local() else str(ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    from scripts import coverage_split_outputs as out

    return out


def _read(path: str) -> bytes | None:
    try:
        return b"".join(volume.read_file(path))
    except FileNotFoundError:
        return None


def _volume_scenario(json_rel: str, expect: dict) -> tuple[bytes, bytes, bytes] | None:
    out = _out()
    json_bytes = _read(json_rel)
    if json_bytes is None:
        return None
    record = json.loads(json_bytes)
    files = [_read(record["rows"][kind]["file"]) for kind in ("tested", "persons")]
    if any(f is None for f in files):
        raise RuntimeError(f"the volume holds {json_rel} without its rows")
    out.validate_scenario(json_bytes, *files, expect)
    return json_bytes, files[0], files[1]


def _packet(status: str, json_rel: str, json_bytes: bytes, tested: bytes, persons: bytes) -> dict:
    record = json.loads(json_bytes)
    return dict(status=status, json_rel=json_rel, test=record["test"], part=record["part"], rank=record["rank"],
                smoke=record["smoke"], json=base64.b64encode(json_bytes).decode(),
                tested=base64.b64encode(tested).decode(), persons=base64.b64encode(persons).decode())


@app.function(cpu=CPU, memory=MEMORY_MIB, timeout=4 * 3600,
              retries=modal.Retries(max_retries=1, initial_delay=10.0))
def scenario(test: str, part: int, rank: int, code: dict, inputs: dict, rates: dict, smoke: int = 0) -> dict:
    os.chdir(REMOTE)
    out = _out()
    out.verify_code(code, Path(REMOTE))
    json_rel = out.scenario_json(part, test, rank, smoke)
    expect = dict(test=test, part=part, rank=rank, smoke=bool(smoke))
    existing = _volume_scenario(json_rel, expect)
    if existing:
        return _packet("already written", json_rel, *existing)
    started = time.time()
    import scripts.coverage_split as cs
    from scripts.expanded_historical import historical_provenance
    from scripts.job_entry_outputs import new_run_id

    if test == "job":
        tested, persons, record = cs.job_scenario(part, rank, inputs["pairs"], rates, smoke=smoke)
    else:
        tested, persons, record = cs.raise_scenario(part, test, rank, inputs["rows"], smoke=smoke)
    extra = dict(code=code, inputs=inputs["names"], union_run=out.UNION_TAG, historical=historical_provenance(),
                 seconds_total=round(time.time() - started, 1), container=dict(cpu=CPU, memory_mib=MEMORY_MIB),
                 modal={"app_id": os.environ.get("MODAL_APP_ID"), "task_id": os.environ.get("MODAL_TASK_ID")})
    json_bytes, tested_bytes, persons_bytes = cs.serialize(tested, persons, record, part, test, rank,
                                                           new_run_id(), smoke, extra)
    rows = json.loads(json_bytes)["rows"]
    try:
        with volume.batch_upload(force=False) as batch:
            batch.put_file(io.BytesIO(tested_bytes), "/" + rows["tested"]["file"])
            batch.put_file(io.BytesIO(persons_bytes), "/" + rows["persons"]["file"])
            batch.put_file(io.BytesIO(json_bytes), "/" + json_rel)
    except FileExistsError:
        existing = _volume_scenario(json_rel, expect)
        if existing:
            return _packet("already written", json_rel, *existing)
        raise
    return _packet("written", json_rel, json_bytes, tested_bytes, persons_bytes)


@app.function(cpu=CPU, memory=MEMORY_MIB, timeout=3 * 3600,
              retries=modal.Retries(max_retries=1, initial_delay=10.0))
def aggregate(part: int, payload_bytes: bytes, code: dict, tag: str) -> dict:
    os.chdir(REMOTE)
    out = _out()
    out.verify_code(code, Path(REMOTE))
    json_rel = out.aggregate_json(part, tag)
    existing = _read(json_rel)
    if existing is not None:
        return dict(status="already written", part=part, json_rel=json_rel, json=existing.decode())
    import scripts.coverage_split as cs

    payload = json.loads(payload_bytes)
    if payload["part"] != part:
        raise ValueError("payload of another part")
    record = cs.aggregate_part(part, payload)
    record.update(tag=tag, code=code, payload_sha256=hashlib.sha256(payload_bytes).hexdigest(),
                  modal={"app_id": os.environ.get("MODAL_APP_ID"), "task_id": os.environ.get("MODAL_TASK_ID")})
    json_bytes = (json.dumps(record, indent=1, sort_keys=True) + "\n").encode()
    try:
        with volume.batch_upload(force=False) as batch:
            batch.put_file(io.BytesIO(json_bytes), "/" + json_rel)
    except FileExistsError:
        pass
    return dict(status="written", part=part, json_rel=json_rel, json=json_bytes.decode())


@app.local_entrypoint()
def main(stage: str = "job", parts: str = "0,1,2,3", smoke_households: int = 150,
         job_root: str = DEFAULTS["job_root"], raise_rows_root: str = DEFAULTS["raise_rows_root"],
         union_root: str = DEFAULTS["union_root"], dry_run: bool = False):
    out = _out()
    from scripts.job_entry_outputs import install_bytes

    logfile = ROOT / "logs" / "coverage_split_modal.log"
    logfile.parent.mkdir(exist_ok=True)

    def log(message: str) -> None:
        line = f"{datetime.datetime.now(datetime.timezone.utc):%Y-%m-%dT%H:%M:%SZ} {message}"
        print(line, flush=True)
        with logfile.open("a") as handle:
            handle.write(line + "\n")

    if stage == "fetch":
        # Install every complete scenario and aggregate record the volume holds (after --detach).
        for folder in ("scenarios", "aggregate"):
            try:
                entries = list(volume.iterdir(f"/{out.BASE}/{folder}", recursive=True))
            except (FileNotFoundError, modal.exception.NotFoundError):
                continue
            for entry in entries:
                path = entry.path.lstrip("/")
                if entry.type != modal.volume.FileEntryType.FILE or not path.endswith(".json"):
                    continue
                data = _read(path)
                if folder == "aggregate":
                    log(f"{path}: {install_bytes(ROOT, path, data)}")
                    continue
                record = json.loads(data)
                files = [_read(record["rows"][kind]["file"]) for kind in ("tested", "persons")]
                if any(f is None for f in files):
                    log(f"{path}: skipped, rows missing")
                    continue
                log(f"{path}: {out.install_scenario(ROOT, path, data, *files)}")
        return
    code = out.code_record(ROOT)
    log(f"stage {stage}, commit {code['commit'][:7]}, app {APP}")
    if stage == "aggregate":
        payloads = {p: (ROOT / out.classified_json(p)).read_bytes() for p in range(out.PARTS)}
        tag = hashlib.sha256(b"".join(payloads[p] for p in range(out.PARTS)) + code["commit"].encode()).hexdigest()[:16]
        log(f"aggregate tag {tag}")
        jobs = [(p, payloads[p], code, tag) for p in range(out.PARTS)
                if not (ROOT / out.aggregate_json(p, tag)).exists()]
        if dry_run:
            return
        for result in aggregate.starmap(jobs, return_exceptions=True, wrap_returned_exceptions=False,
                                        order_outputs=False):
            if isinstance(result, BaseException):
                log(f"a container failed: {result!r}"[:3000])
                continue
            state = install_bytes(ROOT, result["json_rel"], result["json"].encode())
            record = json.loads(result["json"])
            log(f"part {result['part']}: {result['status']}; {state} {result['json_rel']}; "
                f"union reproduction {record['union_reproduction']}; {record['runtime']['seconds']} s")
        log(f"next: python scripts/coverage_split.py combine --tag {tag}")
        return

    manifest = out.union_manifest(Path(union_root))
    rates = out.job_rates(manifest, Path(job_root))
    smoke = smoke_households if stage == "smoke" else 0
    part_list = [0] if smoke else [int(p) for p in parts.split(",")]
    jobs = []
    for part in part_list:
        inputs = out.part_inputs(manifest, part, Path(job_root), Path(raise_rows_root))
        if stage in ("smoke", "job"):
            for rank in ([1] if smoke else sorted(inputs["job"])):
                jobs.append(("job", part, rank, code, {"pairs": inputs["job"][rank], "names": inputs["names"]},
                             rates, smoke))
        if stage in ("smoke", "raise"):
            for key in (["raise_1000"] if smoke else list(out.RAISE_KEYS)):
                for rank in ([1] if smoke else out.RAISE_RANKS):
                    jobs.append((key, part, rank, code, {"rows": inputs["raise"][key], "names": inputs["names"]},
                                 {}, smoke))
    jobs = [j for j in jobs if out.local_scenario(ROOT, out.scenario_json(j[1], j[0], j[2], smoke)) is None]
    log(f"{len(jobs)} scenarios to run: {[(j[0], j[1], j[2]) for j in jobs]}")
    if dry_run:
        return
    started = time.time()
    for result in scenario.starmap(jobs, return_exceptions=True, wrap_returned_exceptions=False,
                                   order_outputs=False):
        if isinstance(result, BaseException):
            log(f"a container failed: {result!r}"[:3000])
            continue
        data = {k: base64.b64decode(result[k]) for k in ("json", "tested", "persons")}
        state = out.install_scenario(ROOT, result["json_rel"], data["json"], data["tested"], data["persons"],
                                     expect=dict(test=result["test"], part=result["part"], rank=result["rank"]))
        record = json.loads(data["json"])
        r = record["reproduction"]
        log(f"{result['test']} part {result['part']} rank {result['rank']}: {result['status']}; {state}; "
            f"tested {r['tested_adults_compared']}, strict {r['sample_strict_saved']}, max |d| gap "
            f"{r['max_abs_difference_d_with']} (exact {r['exact_d_with']}); people written "
            f"{record['rows']['persons']['count']}; {record.get('seconds_total')} s, {record.get('peak_memory_gib')} GiB")
    log(f"stage {stage} done in {round(time.time() - started)} s")
