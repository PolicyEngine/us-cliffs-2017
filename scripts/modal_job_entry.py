"""Run the national job-entry test on Modal: one candidate rank of one household part per container.

Each container holds this checkout (the commit it records) and the packages pinned in
scripts/modal-requirements.txt, the same frozen set scripts/modal_earnings_changes.py
uses, with the dataset baked into the image. It loads one of the frozen experiment's four
household parts, tests every in-scope candidate of one rank
(scripts/expanded_job_entry_national.py), and stops on any failed identity.

Results go to a Modal volume (``us-cliffs-2017-job-entry``, or
``us-cliffs-2017-job-entry-NAMESPACE`` with ``--namespace``) and into a local root
under results/job_entry/ (this checkout, or ``--local-root``, which a namespace
requires). Only a complete pair is published or installed: the container serializes
the person rows, then the JSON record that names them by a unique run id and hashes
them, validates the pair strictly, and uploads both in one batch that may not
overwrite. A failed container publishes nothing. Locally each file goes in under a
unique temporary name and is hard-linked into place, never over an existing file
(scripts/job_entry_outputs.py).

A launch first asks one container for its environment (code, dataset file, packages)
and checks it against this checkout. A rank already written, here or on the volume, is
reused only when its resume fingerprint matches the launch's: code, dataset, package
pins, the request (part, rank, scope), the planned candidate count and the resolved
wage table (job_entry_outputs.existing_result). Any mismatch stops the launch and
names each difference; a fresh namespace starts a run that resumes nothing. Plans
are reused under the same check. Every failed container, rank left without a pair,
install conflict or strict-validation problem makes the command exit nonzero and
names each one.

The wage scope ``resolved`` tests every jurisdiction scripts/job_entry_wages.py resolves
and counts the others' candidates as deferred; ``states:MD,NY`` tests only those states.

usage:
  modal run scripts/modal_job_entry.py --check-only          # one container: environment and wage table
  modal run scripts/modal_job_entry.py --model-fixture-only  # the model-backed run_rank fixture
  modal run scripts/modal_job_entry.py --smoke [--smoke-households 150] [--smoke-seed 17]
  modal run scripts/modal_job_entry.py --plan-only [--parts 0,1,2,3] [--scope resolved]
  modal run --detach scripts/modal_job_entry.py [--parts 0,1,2,3] [--scope resolved]
      [--ranks 1,2] [--dry-run] [--namespace NAME --local-root PATH]
  modal run scripts/modal_job_entry.py --fetch [--namespace NAME --local-root PATH]
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


def volume_name(namespace: str = "") -> str:
    if not namespace:
        return VOLUME
    if not namespace.replace("-", "").isalnum() or len(namespace) > 40:
        raise SystemExit("a namespace is letters, digits and hyphens, at most 40 characters")
    return f"{VOLUME}-{namespace}"


def _volume(name: str, create: bool = False):
    return modal.Volume.from_name(name, create_if_missing=create)


def _repo():
    root = REMOTE if not modal.is_local() else str(ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    from scripts import job_entry_outputs as out

    return out


def _reader(volume):
    def read(path: str) -> bytes | None:
        try:
            return b"".join(volume.read_file(path))
        except FileNotFoundError:
            return None

    return read


def _packet(status: str, json_rel: str, json_bytes: bytes, csv_bytes: bytes) -> dict:
    record = json.loads(json_bytes)
    return dict(status=status, json_rel=json_rel, part=record["part"], rank=record["rank"],
                scope=record["scope"], json=base64.b64encode(json_bytes).decode(),
                csv=base64.b64encode(csv_bytes).decode())


def _check_container(national, out, expected: dict, where: str) -> None:
    """Stop unless this container's environment is the one the launch expects."""
    env = national.environment()
    problems = out.differences(env, {k: expected[k] for k in ("code", "dataset", "packages")}, "environment")
    if problems:
        raise RuntimeError(f"{where}: this container differs from the launch:\n  " + "\n  ".join(problems))


def _reuse(read, json_rel: str, expected: dict, where: str):
    """A reusable pair's bytes from ``read``, None if absent; StaleResult if it may not be reused."""
    return _repo().reusable_pair(read, json_rel, expected, where)


@app.function(cpu=CPU, memory=MEMORY_MIB, timeout=6 * 3600,
              retries=modal.Retries(max_retries=1, initial_delay=10.0))
def run_rank(part: int, rank: int, scope: str, wages_sha256: str, expected: dict,
             smoke_households: int = 0, smoke_seed: int = 17, volume: str = VOLUME) -> dict:
    out = _repo()
    try:
        return _run_rank(part, rank, scope, wages_sha256, expected, smoke_households, smoke_seed, volume)
    except Exception as error:
        raise RuntimeError(f"part {part} rank {rank} scope {out.scope_tag(scope)}: {error!r}"[:4000]) from None


def _run_rank(part, rank, scope, wages_sha256, expected, smoke_households, smoke_seed, volume_label) -> dict:
    os.chdir(REMOTE)
    out = _repo()
    import scripts.expanded_job_entry_national as national

    started = time.time()
    if out.request_identity(part, rank, scope, smoke_households, smoke_seed) != expected["request"]:
        raise RuntimeError("the launch's expectation names another request")
    _check_container(national, out, expected, "run_rank")
    provenance, table = national.provenance(wages_sha256)
    if provenance["wage_table"] != expected["wage_table"]:
        raise RuntimeError("this container's resolved wage table differs from the launch's")
    volume = _volume(volume_label)
    read = _reader(volume)
    stem = out.smoke_stem(part, smoke_households, smoke_seed) if smoke_households else out.part_stem(part)
    json_rel = out.result_json(stem, scope, rank)
    existing = _reuse(read, json_rel, expected, f"volume {volume_label}: {json_rel}")
    if existing:
        return _packet("already written", json_rel, *existing)

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
    planned = expected["planned_candidates"]
    if planned is not None and tested != planned:
        raise RuntimeError(f"part {part} rank {rank}: {tested} candidates, the plan counted {planned}")
    run_id = out.new_run_id()
    csv_rel = out.result_csv(stem, scope, rank, run_id)
    record["timing_seconds"].update(load=load_seconds, build=build_seconds)
    provenance["resume"] = expected
    extra = dict(
        part=part,
        smoke=bool(smoke_households),
        smoke_sample=None if not sample else dict(sample, seed=smoke_seed, part=part),
        run_id=run_id,
        provenance=provenance,
        modal=dict(app_id=os.environ.get("MODAL_APP_ID"), task_id=os.environ.get("MODAL_TASK_ID"),
                   volume=volume_label),
        container=dict(cpu=CPU, memory_mib=MEMORY_MIB),
        peak_memory_gib=national.peak_memory_gib(),
        seconds_total=round(time.time() - started, 1),
    )
    json_bytes, csv_bytes = national.write_pair(rows, record, csv_rel, extra)
    problems = out.resume_mismatches(json.loads(json_bytes), expected)
    if problems:
        raise RuntimeError("the new record does not carry the launch's fingerprint: " + "; ".join(problems))
    try:
        with volume.batch_upload(force=False) as batch:
            batch.put_file(io.BytesIO(csv_bytes), "/" + csv_rel)
            batch.put_file(io.BytesIO(json_bytes), "/" + json_rel)
    except FileExistsError:
        existing = _reuse(read, json_rel, expected, f"volume {volume_label}: {json_rel}")
        if existing:
            return _packet("already written", json_rel, *existing)
        raise
    return _packet("written", json_rel, json_bytes, csv_bytes)


@app.function(cpu=CPU, memory=MEMORY_MIB, timeout=2 * 3600)
def plan_part(part: int, scope: str, wages_sha256: str, expected: dict) -> dict:
    os.chdir(REMOTE)
    out = _repo()
    import scripts.expanded_job_entry_national as national

    started = time.time()
    if expected["request"] != {"part": part, "scope": out.scope_tag(scope)}:
        raise RuntimeError(f"plan part {part}: the launch's expectation names another request")
    _check_container(national, out, expected, f"plan part {part}")
    provenance, table = national.provenance(wages_sha256)
    if provenance["wage_table"] != expected["wage_table"]:
        raise RuntimeError(f"plan part {part}: this container's resolved wage table differs from the launch's")
    provenance["resume"] = expected
    dataset = national.load_part(part)
    sim = national.build(dataset)
    plan = national.plan(sim, table["rates"], scope)
    return dict(part=part, scope=out.scope_tag(scope), plan=plan, provenance=provenance,
                modal=dict(app_id=os.environ.get("MODAL_APP_ID"), task_id=os.environ.get("MODAL_TASK_ID")),
                peak_memory_gib=national.peak_memory_gib(), seconds=round(time.time() - started, 1))


@app.function(timeout=900)
def check() -> dict:
    os.chdir(REMOTE)
    out = _repo()
    from importlib import metadata

    from scripts.expanded_historical import historical_provenance
    from scripts.expanded_job_entry_national import code_record, environment
    from scripts.job_entry_wages import national_wage_table

    table = national_wage_table()
    return dict(code=code_record(), historical=historical_provenance(), environment=environment(),
                versions={p: metadata.version(p) for p in ("policyengine-us", "policyengine-core", "numpy", "pandas")},
                wages_json_sha256=table["wages_json_sha256"], wage_table=out.wage_table_fingerprint(table),
                resolved=len(table["rates"]), unresolved=table["unresolved"],
                medicaid_totals=Path(out.MEDICAID_TOTALS).exists())


@app.function(cpu=CPU, memory=MEMORY_MIB, timeout=3600)
def model_fixture() -> dict:
    os.chdir(REMOTE)
    _repo()
    from scripts.job_entry_model_fixture import run

    return run()


def _uncommitted(files) -> str:
    return subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", *files, "cliffs2017"],
                          capture_output=True, text=True, check=True).stdout.strip()


def _install(packet: dict, root: Path) -> str:
    out = _repo()
    try:
        return out.install_pair(
            root, packet["json_rel"], base64.b64decode(packet["json"]), base64.b64decode(packet["csv"]),
            expect=dict(part=packet["part"], rank=packet["rank"], scope=packet["scope"]),
        )
    except (KeyError, ValueError, TypeError) as error:
        return f"invalid pair, not installed: {error}"


def _fetch(volume, root: Path, log) -> list[str]:
    """Install every complete pair on the volume; one problem line per pair that would not install."""
    out = _repo()
    read = _reader(volume)
    try:
        entries = list(volume.iterdir(f"/{out.BASE}/parts", recursive=True))
    except (FileNotFoundError, modal.exception.NotFoundError):
        log("the volume holds no results yet")
        return ["the volume holds no results"]
    problems = []
    for entry in entries:
        path = entry.path.lstrip("/")
        if entry.type != modal.volume.FileEntryType.FILE or not path.endswith(".json"):
            continue
        json_bytes = read(path)
        try:
            record = json.loads(json_bytes)
            csv_bytes = read(record["rows"]["file"])
            if csv_bytes is None:
                raise ValueError("its rows file is missing")
            state = out.install_pair(root, path, json_bytes, csv_bytes)
        except (KeyError, ValueError, TypeError) as error:
            state = f"not a complete pair: {error}"
        log(f"{path}: {state}")
        if not out.installed(state):
            problems.append(f"{path}: {state}")
    return problems


def _environment(out, log) -> dict:
    """One container's environment, checked against this checkout."""
    info = check.remote()
    env = info["environment"]
    problems = out.environment_differences(out.local_environment(ROOT), env)
    if problems:
        raise SystemExit(f"the container's environment differs from this checkout: {problems}")
    log(f"environment: code {out.sha256(json.dumps(env['code'], sort_keys=True).encode())[:12]}, "
        f"dataset {env['dataset']['file_sha256'][:12]}, packages {env['packages']['requirements_sha256'][:12]}, "
        f"python {env['packages']['python']}")
    return env


@app.local_entrypoint()
def main(parts: str = "0,1,2,3", scope: str = "resolved", ranks: str = "", smoke: bool = False,
         smoke_households: int = 150, smoke_seed: int = 17, plan_only: bool = False,
         check_only: bool = False, model_fixture_only: bool = False, fetch: bool = False,
         dry_run: bool = False, namespace: str = "", local_root: str = ""):
    out = _repo()
    try:
        _main(out, parts, scope, ranks, smoke, smoke_households, smoke_seed, plan_only, check_only,
              model_fixture_only, fetch, dry_run, namespace, local_root)
    except out.StaleResult as error:
        raise SystemExit(f"stale result, not resuming: {error}") from None


def _main(out, parts, scope, ranks, smoke, smoke_households, smoke_seed, plan_only, check_only,
          model_fixture_only, fetch, dry_run, namespace, local_root):
    from scripts.job_entry_wages import national_wage_table

    logfile = ROOT / "logs" / "job_entry_modal.log"
    logfile.parent.mkdir(exist_ok=True)

    def log(message: str) -> None:
        import datetime

        line = f"{datetime.datetime.now(datetime.timezone.utc):%Y-%m-%dT%H:%M:%SZ} {message}"
        print(line, flush=True)
        with logfile.open("a") as handle:
            handle.write(line + "\n")

    vol_name = volume_name(namespace)
    if namespace and not local_root:
        raise SystemExit("--namespace needs its own --local-root, so nothing resumes from this checkout")
    root = Path(local_root).expanduser().resolve() if local_root else ROOT
    if root != ROOT and root.is_relative_to(ROOT):
        raise SystemExit("--local-root must lie outside the checkout (it would enter the image)")
    log(f"volume {vol_name}; local root {'this checkout' if root == ROOT else 'given by --local-root'}")

    if check_only:
        print(json.dumps(check.remote(), indent=1))
        return
    if fetch:
        problems = _fetch(_volume(vol_name), root, log)
        try:
            summary = out.validate_results(root)
            log(f"strict validation: {json.dumps(summary, sort_keys=True)}")
        except ValueError as error:
            problems.append(f"strict validation: {error}")
        out.require_success(problems, "the fetch")
        return
    dirty = _uncommitted([*out.CODE_FILES, out.REQUIREMENTS, out.MEDICAID_TOTALS, "scripts/job_entry_model_fixture.py"])
    if dirty:
        raise SystemExit(f"commit these first, so the recorded commit holds the code:\n{dirty}")
    if model_fixture_only:
        result = model_fixture.remote()
        print(json.dumps(result, indent=1, sort_keys=True))
        if not result.get("pass"):
            raise SystemExit("the model-backed fixture failed")
        return
    table = national_wage_table()
    sha = table["wages_json_sha256"]
    wage_table = out.wage_table_fingerprint(table)
    for code, reason in table["unresolved"].items():
        log(f"unresolved wage, candidates deferred under scope 'resolved': {reason}")
    log(f"wage table {wage_table['sha256'][:12]}: {wage_table['jurisdictions']} resolved, "
        f"unresolved {wage_table['unresolved']}")
    env = _environment(out, log)
    _volume(vol_name, create=True).hydrate()  # creates a new namespace's volume before any container opens it
    read = out.read_local(root)
    if smoke:
        log(f"smoke: part 0 rank 1, {smoke_households} households, seed {smoke_seed}, scope {scope}")
        expected = out.resume_expectation(env, wage_table, out.request_identity(0, 1, scope, smoke_households,
                                                                                smoke_seed), None)
        try:
            results = [run_rank.remote(0, 1, scope, sha, expected, smoke_households, smoke_seed, vol_name)]
        except Exception as error:  # noqa: BLE001 - reported and turned into a nonzero exit
            results = [error]
        out.require_success(out.settle([(0, 1)], results, lambda p: _install(p, root), log), "the smoke run")
        return

    part_list = [int(p) for p in parts.split(",")]
    plans = {}
    for part in part_list:
        rel = out.plan_json(part, scope)
        reused = out.existing_plan(read(rel), out.plan_expectation(env, wage_table, part, scope), f"local {rel}")
        if reused:
            plans[part] = reused
    missing = [p for p in part_list if p not in plans]
    if missing:
        log(f"planning parts {missing} for scope {scope}")
        problems = []
        for result in plan_part.starmap([(p, scope, sha, out.plan_expectation(env, wage_table, p, scope))
                                         for p in missing]):
            data = (json.dumps(result, indent=1) + "\n").encode()
            state = out.install_bytes(root, out.plan_json(result["part"], scope), data)
            plans[result["part"]] = result
            log(f"plan part {result['part']}: {state}; {result['plan']['sample_candidates_by_rank']} "
                f"({result['seconds']} s, {result['peak_memory_gib']} GiB)")
            if state == "differs":
                problems.append(f"plan part {result['part']}: a different plan is installed")
        out.require_success(problems, "planning")
    if plan_only:
        return
    wanted = {int(r) for r in ranks.split(",")} if ranks else None
    planned = out.ranks_to_run({p: plans[p] for p in part_list}, scope, env, wage_table, read, wanted, log)
    jobs = [(part, k, scope, sha, expected, 0, 17, vol_name) for part, k, expected in planned]
    log(f"{len(jobs)} ranks to run: {[(j[0], j[1]) for j in jobs]}")
    if dry_run:
        return
    results = run_rank.starmap(jobs, return_exceptions=True, wrap_returned_exceptions=False, order_outputs=False)
    out.finish_launch(jobs, results, lambda packet: _install(packet, root), root, part_list, wanted, log)
