"""Run scripts/earnings_changes.py on Modal, one change per container, all at once.

Each container holds this checkout (the commit it records) and the packages pinned in
scripts/modal-requirements.txt, frozen from the environment that ran the committed
parts. It runs one change for one household part, exactly as
scripts/run_earnings_changes.sh would, and writes the change's totals and per-person
rows to the Modal volume ``us-cliffs-2017-changes`` under the same paths the script
uses here. The local entrypoint copies each result into this checkout as it lands, and
never overwrites a change already written here.

Every part's $1,000 raise still has to reproduce the committed part to 1e-9
(``reproduces_committed_part``), so a container whose arithmetic differs from the
machine that ran the committed parts shows up there, and the summary refuses that part.

usage:
  modal run --detach scripts/modal_earnings_changes.py [--years 2017,2025] [--parts 0,1,2,3]
      [--changes=+5000,-5000] [--dry-run]   # "=" so a leading minus is not read as a flag
  modal run scripts/modal_earnings_changes.py --check      # one container: environment only
  modal run scripts/modal_earnings_changes.py --fetch      # copy what the volume holds
"""

from __future__ import annotations

import base64
import os
import subprocess
import sys
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]
REMOTE = "/repo"
VOLUME = "us-cliffs-2017-changes"
ALL_CHANGES = "+1000,-1000,+2000,-2000,+5000,-5000,+1%,-1%,+10%,-10%"
SKIP = {".venv", "logs", "__pycache__", ".hypothesis", ".pytest_cache", "per_person", "src"}


def _skip(path: Path) -> bool:
    parts = Path(path).parts
    return bool(SKIP.intersection(parts)) or "earnings_changes" in parts[:2] and parts[:1] == ("results",)


def _download() -> None:
    sys.path.insert(0, REMOTE)
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
app = modal.App("us-cliffs-2017-changes", image=image)
volume = modal.Volume.from_name(VOLUME, create_if_missing=True)


@app.function(volumes={"/vol": volume}, cpu=2.0, memory=16384, timeout=6 * 3600,
              retries=modal.Retries(max_retries=2, initial_delay=10.0))
def run_change(year: int, part: int, change: str) -> dict:
    os.chdir(REMOTE)
    run = subprocess.run(
        [sys.executable, "scripts/earnings_changes.py", "--year", str(year), "--part", str(part), f"--changes={change}"],
        capture_output=True, text=True,
    )
    files = {}
    for folder in ("results/earnings_changes/parts", "results/parts/per_person"):
        for path in sorted(Path(REMOTE, folder).rglob("*")):
            if path.is_file() and not path.name.endswith(".tmp"):
                rel = str(path.relative_to(REMOTE))
                target = Path("/vol", rel)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(path.read_bytes())
                files[rel] = base64.b64encode(path.read_bytes()).decode()
    volume.commit()
    return dict(year=year, part=part, change=change, rc=run.returncode,
                stdout=run.stdout[-3000:], stderr=run.stderr[-3000:], files=files)


@app.function()
def check() -> dict:
    os.chdir(REMOTE)
    sys.path.insert(0, REMOTE)
    from importlib import metadata

    from cliffs2017.run import code_version

    status = subprocess.run(["git", "status", "--porcelain", "--", "cliffs2017", "scripts/earnings_changes.py"],
                            capture_output=True, text=True)
    return dict(code=code_version(), status=status.stdout, status_rc=status.returncode, stderr=status.stderr,
                versions={p: metadata.version(p) for p in ("policyengine-us", "policyengine-core", "numpy", "pandas")},
                results=sorted(str(p) for p in Path("results").rglob("*.json"))[:5])


def _write(rel: str, data: bytes, log) -> None:
    path = ROOT / rel
    if path.exists():
        if path.read_bytes() != data:
            log(f"kept the local {rel}; the container's copy differs")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    log(f"wrote {rel}")


def _jobs(years: str, parts: str, changes: str) -> list[tuple[int, int, str]]:
    # cliffs2017.changes names the files; the modal CLI's own Python may lack numpy, so ask the
    # checkout's environment.
    python = ROOT / ".venv" / "bin" / "python"
    texts = changes.split(",")
    keys = subprocess.run(
        [str(python) if python.exists() else "python3", "-c",
         "import sys; from cliffs2017.changes import parse; print(*(parse(t).key for t in sys.argv[1:]))", *texts],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()
    jobs = []
    for year in (int(y) for y in years.split(",")):
        for part in (int(p) for p in parts.split(",")):
            for text, key in zip(texts, keys, strict=True):
                done = ROOT / "results" / "earnings_changes" / "parts" / f"changes_{year}_p4_{part}_s0" / f"{key}.json"
                if not done.exists():
                    jobs.append((year, part, text))
    return jobs


@app.local_entrypoint()
def main(years: str = "2017,2025", parts: str = "0,1,2,3", changes: str = ALL_CHANGES,
         dry_run: bool = False, check_only: bool = False, fetch: bool = False):
    logfile = ROOT / "logs" / "earnings_changes_modal.log"
    logfile.parent.mkdir(exist_ok=True)

    def log(message: str) -> None:
        import datetime

        line = f"{datetime.datetime.now(datetime.timezone.utc):%Y-%m-%dT%H:%M:%SZ} {message}"
        print(line, flush=True)
        with logfile.open("a") as handle:
            handle.write(line + "\n")

    if check_only:
        print(check.remote())
        return
    if fetch:
        for entry in volume.iterdir("/", recursive=True):
            if entry.type == modal.volume.FileEntryType.FILE:
                _write(entry.path.lstrip("/"), b"".join(volume.read_file(entry.path)), log)
        return
    jobs = _jobs(years, parts, changes)
    log(f"{len(jobs)} changes to run: {jobs}")
    if dry_run:
        return
    for result in run_change.starmap(jobs, return_exceptions=True, wrap_returned_exceptions=False, order_outputs=False):
        if isinstance(result, BaseException):
            log(f"a container failed: {result!r}")
            continue
        last = (result["stdout"].strip().splitlines() or [""])[-1]
        log(f"{result['year']} part {result['part']} {result['change']}: rc={result['rc']} {last}")
        if result["rc"] != 0:
            log("stderr: " + result["stderr"][-1500:].replace("\n", " | "))
        for rel, data in result["files"].items():
            _write(rel, base64.b64decode(data), log)
