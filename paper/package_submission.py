"""Package the committed IJM manuscript, executable source and Git history.

No model commands execute. A self-contained bundle preserves source identities
needed by the checked full-replication preparer. Private reviews stay outside.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def package(destination: Path) -> dict:
    if git("status", "--porcelain").strip():
        raise ValueError("Commit the complete paper/source before packaging")
    commit = git("rev-parse", "HEAD").decode().strip()
    branch = git("branch", "--show-current").decode().strip()
    if not branch:
        raise ValueError("The replication bundle needs a named source branch")
    destination = destination.absolute()
    if destination.is_relative_to(ROOT):
        raise ValueError("Write the package outside its own source tree")
    destination.parent.mkdir(parents=True, exist_ok=True)
    entries = {}
    with tempfile.TemporaryDirectory(prefix="ijm-bundle-") as folder:
        bundle = Path(folder) / "replication.bundle"
        git("bundle", "create", str(bundle), f"refs/heads/{branch}")
        git("bundle", "verify", str(bundle))
        entries["replication.bundle"] = bundle.read_bytes()
    with tarfile.open(
        fileobj=io.BytesIO(git("archive", "--format=tar", commit))
    ) as tar:
        for member in tar:
            if not member.isfile():
                continue
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts:
                raise ValueError("Unexpected source archive path")
            entries["code/" + str(name)] = tar.extractfile(member).read()
    for suffix in ("pdf", "docx"):
        source = ROOT / "paper/submission" / f"manuscript.{suffix}"
        entries[f"IJM-manuscript.{suffix}"] = source.read_bytes()
    readme = f"""# IJM manuscript and executable replication source

Cliffs
Max Ghenis, PolicyEngine

Source branch: {branch}
Source commit: {commit}

Read IJM-manuscript.pdf; IJM-manuscript.docx provides editable tables and
embedded figure PNGs. The default PolicyEngine-branded edition lives at
code/paper/manuscript.pdf. The code/ folder contains inspectable analysis,
figure and manuscript source, exact environments, public-input identities and
saved outputs. The hypothetical-household snapshot contains model-calculated
examples, not survey records. No microdata-derived rows,
environments, private correspondence or private referee reports are included.
The bundle contains committed history needed by the source-identity checks.

## Verify this ZIP

PACKAGE-MANIFEST.json gives SHA-256 and byte count for every other entry.
The separate archive checksum identifies this ZIP as delivered. Exact source
identities and calculation results matter; renderer-specific PDF bytes may
change if rebuilt with different fonts or software.

## Rebuild tables, figures and Markdown without microdata

From the unpacked code/paper directory:

    uv sync --frozen
    uv run python build_assets.py
    uv run python build_figures.py
    uv run python fill_manuscript.py
    uv run python build_submission.py

For Word/PDF instructions and font requirements, see code/paper/RENDERING.md.
The journal manuscript uses Times New Roman, editable tables and six embedded
Matplotlib figures. build_figures.py reads verified saved inputs and performs
no tax-benefit simulation. Rebuild the default branded edition with
'uv run python build_policyengine.py' from code/paper; pe-doc must be on PATH.

## Regenerate the hypothetical-household results

This is a separate model step, not part of the national replication runner.
Use the Python 3.13.13 simulation environment in requirements-expanded.txt
(PolicyEngine-US 2.116.0, core 3.34.10), separate from the paper environment.
From the repository root on Max's machine:

    ~/reviews/us-hub/scripts/heavy_run.sh paper-household-curves .venv/bin/python scripts/paper_household_curves.py --out results/paper_household_curves_rerun.json

Other sites must use an equivalent resource wrapper. The script reads the
frozen results/medicaid/totals_2017_p4_s0.json and totals_2025_p4_s0.json,
not survey microdata, and writes JSON plus a Markdown summary. It checks all
eight frozen package versions and records inputs, controls and source hashes.
The article snapshot has 2,503 grid points and 72 stored scalar checks across
three cases. A rerun does not replace code/paper/inputs/household-curves/ or its
hash manifest automatically; compare outputs and provenance before adoption.

## Prepare a full simulation rerun

Run these from the unpacked package directory. Choose new destinations.

    git clone --branch {branch} replication.bundle replication-source
    git -C replication-source checkout --detach {commit}
    python3 replication-source/scripts/prepare_ijm_replication.py prepare /absolute/new/run
    python3 /absolute/new/run/source/scripts/prepare_ijm_replication.py verify-prepared /absolute/new/run

This prepares and verifies a separate working tree without running a model.
Read /absolute/new/run/PREPARE.json and RUN.sh before executing the expensive
stage. The commands regenerate ignored person-level files even though saved
aggregate references exist. The runner schedules one job at a time, requires
Python 3.13.13 and installs requirements-expanded.txt. It verifies public H5
bytes and compares regenerated settings/outcomes against the saved references.
Frozen Medicaid allocation totals remain inputs; this route does not rebuild
Microcosm or recompute those totals from upstream raw data.

HEAVY_RUNNER must name an executable resource wrapper accepting a label,
then the command and its arguments: '<label> <argv...>'. On Max's machine,
RUN.sh defaults to the required ~/reviews/us-hub/scripts/heavy_run.sh. Other
sites must explicitly provide an appropriate wrapper. Do not remove the
resource requirement to run the national calculations unattended. Original
parts require about 11 GB each; this package does not promise a runtime on a
particular machine.

A completed aggregate rebuild or prepare-only check does not establish that
a new national simulation rerun passed. Successful full reruns write
RUN_COMPLETED only after their recorded comparisons succeed. The historical
April 2025 replication uses the separate code/april2025 environment and inputs.

## Scope and disclosure

The main article uses a frozen 2025 model scenario and a selected adult
population. It does not establish validated current-law effects. The mixed
2017-oriented sensitivity appears in the appendix. Its finite raise grid does not identify
all-worker, full-time job-entry, continuous-path or observed historical
incidence. The paper discloses PolicyEngine institutional support, a client's
commissioning of related analysis and generative-AI assistance. Human-author
approval and the journal's portal declarations belong to the author. No
journal submission, upload, public deposit or external correspondence has
occurred as part of package preparation.

Analysis code: MIT license (code/LICENSE). Manuscript: intended CC BY 4.0
release after author approval. Dependency and input licenses remain with their
respective providers; the ZIP does not distribute licensed system fonts.
"""
    entries["README.md"] = readme.encode()
    manifest = {
        "source_commit": commit,
        "source_branch": branch,
        "scope": "Full manuscript and executable-source package; not a journal submission",
        "entries": {
            name: {"sha256": sha(data), "bytes": len(data)}
            for name, data in sorted(entries.items())
        },
    }
    entries["PACKAGE-MANIFEST.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    with ZipFile(
        destination, "w", compression=ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for name, data in sorted(entries.items()):
            archive.writestr(name, data)
    record = {
        "archive": str(destination),
        "sha256": sha(destination.read_bytes()),
        "bytes": destination.stat().st_size,
        "files": len(entries),
        "source_commit": commit,
    }
    destination.with_suffix(".sha256.json").write_text(
        json.dumps(record, indent=2) + "\n"
    )
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    print(json.dumps(package(parser.parse_args().destination), indent=2))
