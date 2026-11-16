"""Run the combined raise-and-job union on Modal: one household part per container, then the bootstrap.

Each part container holds this checkout (its code checked against the launching commit's
hashes) and the frozen packages in scripts/modal-requirements.txt, with the dataset baked
into the image. It loads one of the frozen experiment's four household parts, receives that
part's inputs as bytes, checks each against the manifest's SHA-256, and runs
scripts/expanded_combined_union.run_part, which stops on any failed identity or invariant.

Results go to the Modal volume ``us-cliffs-2017-combined-union`` and into this checkout under
results/combined_union/ (git-ignored). Only a complete, validated pair is published or
installed: the per-source totals, named by a unique run id, then the JSON record that hashes
them, uploaded in one batch that may not overwrite. Locally each file goes in under a unique
temporary name and is hard-linked into place, never over an existing file. Results are keyed
by the manifest digest (inputs, coverage and code), so a relaunch resumes and a launch on new
job rows (Maryland and New York) starts fresh. The bootstrap container reads the four
validated pairs from the volume and returns only intervals.

usage (paths to checkouts that hold the git-ignored inputs):
  modal run scripts/modal_combined_union.py --job-root PATH --raise-rows-root PATH [--dry-run]
      [--parts 0,1,2,3] [--draws 5000] [--seed 0]
  then: python scripts/expanded_combined_union.py combine --digest DIGEST
"""

from __future__ import annotations

import datetime
import io
import json
import os
import sys
import time
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]
REMOTE = "/repo"
APP = "us-cliffs-2017-combined-union"
VOLUME = "us-cliffs-2017-combined-union"
SKIP = {".venv", "logs", "__pycache__", ".hypothesis", ".pytest_cache", "per_person", "src", "paper", ".git"}
MEMORY_MIB = 16384
CPU = 2.0


def _skip(path: Path) -> bool:
    parts = Path(path).parts
    return bool(SKIP.intersection(parts)) or parts[:2] in {("results", "job_entry"), ("results", "combined_union")}


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


def _inputs():
    root = REMOTE if not modal.is_local() else str(ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    from scripts import combined_union_inputs as inputs

    return inputs


def _read(path: str) -> bytes | None:
    try:
        return b"".join(volume.read_file(path))
    except FileNotFoundError:
        return None


def _volume_pair(json_rel: str, expect: dict) -> tuple[bytes, bytes] | None:
    """A complete pair already on the volume, None if absent; an incomplete one stops the run."""
    inputs = _inputs()
    json_bytes = _read(json_rel)
    if json_bytes is None:
        return None
    npz_rel = json.loads(json_bytes)["per_source"]["file"]
    npz_bytes = _read(npz_rel)
    if npz_bytes is None:
        raise RuntimeError(f"the volume holds {json_rel} without its totals {npz_rel}")
    inputs.validate_part_pair(json_bytes, npz_bytes, expect)
    return json_bytes, npz_bytes


@app.function(cpu=CPU, memory=MEMORY_MIB, timeout=3 * 3600,
              retries=modal.Retries(max_retries=1, initial_delay=10.0))
def summarize(part: int, manifest: dict, files: dict) -> dict:
    os.chdir(REMOTE)
    inputs = _inputs()
    digest = manifest["digest"]
    json_rel = inputs.part_json_rel(digest, part)
    expect = dict(part=part, digest=digest)
    if _volume_pair(json_rel, expect):
        return dict(status="already written", part=part, json_rel=json_rel)
    inputs.verify_code(manifest["code"], Path(REMOTE))
    inputs.check_files(manifest, part, files)

    from scripts.expanded_combined_union import run_part
    from scripts.job_entry_outputs import new_run_id

    record, npz_bytes = run_part(part, manifest, files)
    run_id = new_run_id()
    npz_rel = inputs.per_source_rel(digest, part, run_id)
    record["run_id"] = run_id
    record["per_source"]["file"] = npz_rel
    record["modal"] = {"app_id": os.environ.get("MODAL_APP_ID"), "task_id": os.environ.get("MODAL_TASK_ID")}
    json_bytes = (json.dumps(record, indent=1, sort_keys=True) + "\n").encode()
    inputs.validate_part_pair(json_bytes, npz_bytes, expect)
    try:
        with volume.batch_upload(force=False) as batch:
            batch.put_file(io.BytesIO(npz_bytes), "/" + npz_rel)
            batch.put_file(io.BytesIO(json_bytes), "/" + json_rel)
    except FileExistsError:
        if _volume_pair(json_rel, expect):
            return dict(status="already written", part=part, json_rel=json_rel)
        raise
    return dict(status="written", part=part, json_rel=json_rel, seconds=record["runtime"]["seconds_total"],
                peak_memory_gib=record["runtime"]["peak_memory_gib"])


@app.function(cpu=CPU, memory=MEMORY_MIB, timeout=2 * 3600)
def bootstrap(digest: str, code: dict, draws: int, seed: int) -> dict:
    os.chdir(REMOTE)
    inputs = _inputs()
    inputs.verify_code(code, Path(REMOTE))
    from scripts.expanded_combined_union import bootstrap_parts

    records, npz = [], []
    for part in range(inputs.PARTS):
        pair = _volume_pair(inputs.part_json_rel(digest, part), dict(part=part, digest=digest))
        if pair is None:
            raise RuntimeError(f"part {part} has no result on the volume")
        records.append(json.loads(pair[0]))
        npz.append(pair[1])
    result = bootstrap_parts(records, npz, draws, seed)
    result["digest"] = digest
    result["code_commit"] = code["commit"]
    result["modal"] = {"app_id": os.environ.get("MODAL_APP_ID"), "task_id": os.environ.get("MODAL_TASK_ID")}
    return result


def _fetch_pair(json_rel: str, part: int, digest: str, log) -> None:
    inputs = _inputs()
    pair = _volume_pair(json_rel, dict(part=part, digest=digest))
    if pair is None:
        log(f"part {part}: no result on the volume")
        return
    log(f"part {part}: " + inputs.install_part_pair(ROOT, json_rel, *pair, expect=dict(part=part, digest=digest)))


@app.local_entrypoint()
def main(job_root: str = "", raise_rows_root: str = "", parts: str = "0,1,2,3", draws: int = 5000,
         seed: int = 0, dry_run: bool = False):
    inputs = _inputs()
    from scripts.job_entry_outputs import install_bytes

    if not job_root or not raise_rows_root:
        raise SystemExit("pass --job-root and --raise-rows-root: checkouts holding the git-ignored inputs")
    logfile = ROOT / "logs" / "combined_union_modal.log"
    logfile.parent.mkdir(exist_ok=True)

    def log(message: str) -> None:
        line = f"{datetime.datetime.now(datetime.timezone.utc):%Y-%m-%dT%H:%M:%SZ} {message}"
        print(line, flush=True)
        with logfile.open("a") as handle:
            handle.write(line + "\n")

    code = inputs.code_record(ROOT)
    manifest, files = inputs.build_manifest(ROOT, Path(job_root), Path(raise_rows_root), code)
    digest = manifest["digest"]
    coverage = manifest["coverage"]
    log(f"manifest {inputs.tag(digest)}: commit {code['commit'][:7]}, {len(manifest['inputs'])} inputs, "
        f"{len(coverage['jurisdictions_covered'])} jurisdictions covered, deferred "
        f"{coverage['jurisdictions_deferred']}, excluded scopes {coverage['scopes_excluded']}")
    state = install_bytes(ROOT, inputs.manifest_rel(digest),
                          (json.dumps(manifest, indent=1, sort_keys=True) + "\n").encode())
    log(f"manifest {inputs.manifest_rel(digest)}: {state}")
    if dry_run:
        return
    launch = {"time": f"{datetime.datetime.now(datetime.timezone.utc):%Y-%m-%dT%H:%M:%SZ}",
              "app_id": app.app_id, "commit": code["commit"]}
    launches = ROOT / inputs.launches_rel(digest)
    launches.parent.mkdir(parents=True, exist_ok=True)
    with launches.open("a") as handle:
        handle.write(json.dumps(launch) + "\n")
    log(f"app {app.app_id}")

    wanted = [int(p) for p in parts.split(",")]
    jobs = [(p, manifest, files[p]) for p in wanted if inputs.local_part(ROOT, digest, p) is None]
    log(f"{len(jobs)} parts to run: {[j[0] for j in jobs]}")
    started = time.time()
    for result in summarize.starmap(jobs, return_exceptions=True, wrap_returned_exceptions=False,
                                    order_outputs=False):
        if isinstance(result, BaseException):
            log(f"a container failed: {result!r}"[:2000])
            continue
        log(f"part {result['part']}: {result['status']} "
            f"({result.get('seconds')} s, {result.get('peak_memory_gib')} GiB)")
        _fetch_pair(result["json_rel"], result["part"], digest, log)
    log(f"parts done in {round(time.time() - started)} s")
    if any(inputs.local_part(ROOT, digest, p) is None for p in range(inputs.PARTS)):
        log("not every part has a validated result; skipping the bootstrap")
        return
    boot_rel = inputs.bootstrap_rel(digest, draws, seed)
    if (ROOT / boot_rel).exists():
        log(f"{boot_rel} exists")
    else:
        result = bootstrap.remote(digest, code, draws, seed)
        state = install_bytes(ROOT, boot_rel, (json.dumps(result, indent=1, sort_keys=True) + "\n").encode())
        log(f"bootstrap: {draws} draws, seed {seed}, {result['source_households']} source households, "
            f"{result['seconds']} s; {state} {boot_rel}")
    log(f"next: python scripts/expanded_combined_union.py combine --digest {inputs.tag(digest)}")
