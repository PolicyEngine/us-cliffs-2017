"""Prepare a fresh, independently stored replication checkout; never run it.

Usage: uv run --no-sync python scripts/prepare_ijm_replication.py prepare DEST
Commit this preparer before preparing from HEAD. Uncommitted source and existing
environments are never copied. RUN.sh is an explicit, separate expensive step.
"""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import io
import json
import math
import os
import shlex
import subprocess
import tarfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
SELF = "scripts/prepare_ijm_replication.py"
PYTHON = ".venv/bin/python"
YEARS = (2017, 2025)
PARTS = range(4)
PAIRS = ("+1000,-1000", "+5000,-5000", "+1%,-1%", "+2000,-2000", "+10%,-10%")
DATA_REVISION = "populace-us-2024-spm-20260909"
DATA_COMMIT = "9a814a3b3b53c0ecd6e1737b6ec862c31300ef6f"
DATA_SHA256 = "6496cc4393d4d3c6574f76eca231de5898c803b9067645591fd5c4d3e65aee84"
DATA_BYTES = 826_917_837
# Only volatile provenance is omitted; settings, code hashes and outcomes remain.
VOLATILE = {"commit", "commits", "timing_seconds", "seconds", "part_files"}
ORIGINAL_HASH = "04f6b6c399139cf514ae9cd8ed0a5aeaf95e9d728a1c360d0415eed929b97574"
EXTENDED_HASH = "e791e670d5407372c89fb549580813d6d82254fa590dd8049f85963ab09d4e73"
ADDED_MODULE = "cliffs2017/changes.py"
ADDED_MODULE_HASH = "2690bc0f879833b30531fb290e225bc89f1bcbd47cd5a93b4001b99d32e179be"


def artifact_names(stage: str) -> list[str]:
    """The complete fixed experiment artifacts required at each checkpoint."""
    if stage == "original":
        return [
            f"results/parts/run_{year}_{kind}_p4_{part}_s0.json"
            for year in YEARS
            for kind in ("plain", "health")
            for part in PARTS
        ]
    if stage == "final":
        return [
            f"results/final_{year}_{kind}.json"
            for year in YEARS
            for kind in ("plain", "health")
        ]
    if stage == "summary":
        return [
            "results/earnings_changes.json",
            "results/take_up_bounds.json",
            "results/driver_intervals.json",
            "results/health_only.json",
            *[f"results/counted_once/once_{year}.json" for year in YEARS],
        ]
    if stage == "robustness":
        return ["results/ijm_saved_robustness.json"]
    raise ValueError(f"Unknown checkpoint: {stage}")


def git(source: Path, *args: str) -> bytes:
    """Read Git output, raising on an invalid object or repository."""
    return subprocess.check_output(["git", "-C", str(source), *args])


def digest(path: Path) -> str:
    """Hash files in chunks, including the large microdata input."""
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def command_plan(robustness: bool = False) -> list[dict]:
    """Return serial argv data; constructing this plan executes no command."""
    plan = []

    def add(stage, label, argv, heavy=True):
        plan.append({"stage": stage, "label": label, "argv": argv, "heavy": heavy})

    def compare(stage):
        add(
            f"compare-{stage}",
            f"compare-{stage}",
            [PYTHON, SELF, "compare", stage, "--reference", "../reference"],
            False,
        )

    add("prepared", "verify-prepared", [PYTHON, SELF, "verify-prepared", ".."], False)
    add("data", "verify-data", [PYTHON, SELF, "verify-data"], False)
    for year in YEARS:
        for kind in ("plain", "health"):
            for part in PARTS:
                argv = [
                    PYTHON,
                    "-m",
                    "cliffs2017.run",
                    "--year",
                    str(year),
                    "--parts",
                    "4",
                    "--part",
                    str(part),
                    "--seed",
                    "0",
                    "--decompose",
                    "--out",
                    f"results/parts/run_{year}_{kind}_p4_{part}_s0.json",
                ]
                if year == 2017:
                    argv.append("--aca-before-2018")
                else:
                    argv.append("--leave-out-csfp")
                if kind == "health":
                    argv += [
                        "--health",
                        "--medicaid-totals",
                        f"results/medicaid/totals_{year}_p4_s0.json",
                    ]
                add("original", f"original-{year}-{kind}-{part}", argv)
    compare("original")
    for year in YEARS:
        for kind in ("plain", "health"):
            files = [
                f"results/parts/run_{year}_{kind}_p4_{part}_s0.json" for part in PARTS
            ]
            add(
                "combine",
                f"combine-{year}-{kind}",
                [
                    PYTHON,
                    "-m",
                    "cliffs2017.combine",
                    *files,
                    "--out",
                    f"results/final_{year}_{kind}.json",
                ],
                False,
            )
    compare("final")
    for year in YEARS:
        for part in PARTS:
            add(
                "counted-once",
                f"counted-once-{year}-{part}",
                [
                    PYTHON,
                    "scripts/counted_once.py",
                    "--year",
                    str(year),
                    "--part",
                    str(part),
                ],
            )
        files = [
            f"results/counted_once/parts/once_{year}_p4_{part}_s0.json"
            for part in PARTS
        ]
        add(
            "counted-once-combine",
            f"counted-once-combine-{year}",
            [PYTHON, "scripts/counted_once.py", "--combine", *files],
            False,
        )
    for year in YEARS:
        for part in PARTS:
            for index, pair in enumerate(PAIRS):
                add(
                    "changes",
                    f"changes-{year}-{part}-{index}",
                    [
                        PYTHON,
                        "scripts/earnings_changes.py",
                        "--year",
                        str(year),
                        "--part",
                        str(part),
                        f"--changes={pair}",
                    ],
                )
    for name in (
        "take_up_bounds",
        "driver_intervals",
        "health_only",
        "earnings_changes_summary",
    ):
        add("summary", name, [PYTHON, f"scripts/{name}.py"])
    compare("summary")
    if robustness:
        add(
            "robustness",
            "ijm-robustness",
            [
                PYTHON,
                "scripts/ijm_saved_robustness.py",
                "--source-root",
                ".",
                "--draws",
                "5000",
                "--seed",
                "0",
                "--out",
                "results/ijm_saved_robustness.json",
                "--table",
                "results/ijm_saved_robustness.md",
            ],
        )
        compare("robustness")
    return plan


def render_run(plan: list[dict]) -> str:
    """Render an explicit expensive run with a required resource wrapper."""
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        'cd -- "$(dirname -- "${BASH_SOURCE[0]}")/source"',
        "# Serial execution; these assignments do not raise positive thread limits.",
        "export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1",
        'HEAVY_RUNNER="${HEAVY_RUNNER:-$HOME/reviews/us-hub/scripts/heavy_run.sh}"',
        '[[ -x "$HEAVY_RUNNER" ]] || { echo "Set HEAVY_RUNNER to your resource-queue wrapper." >&2; exit 2; }',
        'heavy() { "$HEAVY_RUNNER" "$@"; }',
        '[[ ! -e ../RUN_STARTED ]] || { echo "This prepared run was already started; prepare another fresh destination." >&2; exit 2; }',
        "touch ../RUN_STARTED",
        "mkdir -p logs results/parts results/counted_once/parts",
        "uv venv --python 3.13.13 .venv",
        "uv pip install --python .venv/bin/python -r requirements-expanded.txt",
    ]
    for item in plan:
        command = shlex.join(item["argv"])
        if item["heavy"]:
            command = f"heavy {shlex.quote('ijm-' + item['label'])} {command}"
        lines.append(
            f"{command} > {shlex.quote('logs/' + item['label'] + '.log')} 2>&1"
        )
        if item["stage"] == "data":
            lines.append("export HF_HUB_OFFLINE=1")
    lines += [
        'printf "%s\\n" "Frozen original/earnings-change replication and recorded checks completed." > ../RUN_COMPLETED',
        "",
    ]
    return "\n".join(lines)


def prepare(source: Path, destination: Path, ref: str = "HEAD") -> dict:
    """Copy an immutable source tree and references without running analyses."""
    source = source.resolve()
    destination = destination.absolute()
    if os.path.lexists(destination):
        raise FileExistsError(f"Destination must not exist: {destination}")
    if destination.resolve().is_relative_to(source):
        raise ValueError("Choose a destination outside the original checkout")
    commit = git(source, "rev-parse", "--verify", f"{ref}^{{commit}}").decode().strip()
    try:
        committed_tool = git(source, "show", f"{commit}:{SELF}")
    except subprocess.CalledProcessError as error:
        raise ValueError(
            "The preparer must be committed at the selected ref"
        ) from error
    if (
        committed_tool != (source / SELF).read_bytes()
        or committed_tool != Path(__file__).read_bytes()
    ):
        raise ValueError(
            "Run the preparer committed at the selected ref; commit changes first"
        )
    names = set(
        git(source, "ls-tree", "-r", "--name-only", commit).decode().splitlines()
    )
    required = {
        SELF,
        "requirements-expanded.txt",
        "cliffs2017/run.py",
        "cliffs2017/combine.py",
        *[
            f"scripts/{name}.py"
            for name in (
                "counted_once",
                "earnings_changes",
                "take_up_bounds",
                "driver_intervals",
                "health_only",
                "earnings_changes_summary",
            )
        ],
        *[f"results/medicaid/totals_{year}_p4_s0.json" for year in YEARS],
        *[
            name
            for stage in ("original", "final", "summary")
            for name in artifact_names(stage)
        ],
    }
    if missing := required - names:
        raise ValueError(f"Selected commit lacks replication inputs: {sorted(missing)}")
    if (
        "scripts/ijm_saved_robustness.py" in names
        and "results/ijm_saved_robustness.json" not in names
    ):
        raise ValueError(
            "Commit the robustness reference result before preparing its replication"
        )
    archive = git(source, "archive", "--format=tar", commit)
    destination.mkdir(parents=True)
    copied = destination / "source"
    # Independent objects preserve the original scripts' commit/source checks.
    subprocess.run(
        [
            "git",
            "clone",
            "--quiet",
            "--no-local",
            "--no-hardlinks",
            "--no-checkout",
            "--",
            str(source),
            str(copied),
        ],
        check=True,
    )
    git(copied, "update-ref", "HEAD", commit)
    git(copied, "read-tree", commit)
    records = []
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar:
            if member.isdir():
                continue
            name = PurePosixPath(member.name)
            if not member.isfile() or name.is_absolute() or ".." in name.parts:
                raise ValueError(f"Unsupported archive member: {member.name}")
            data = tar.extractfile(member).read()
            targets = []
            if name.parts[0] == "results":
                targets.append(destination / "reference" / str(name))
                if name.parts[:2] == ("results", "medicaid"):
                    targets.append(copied / str(name))
            else:
                targets.append(copied / str(name))
            for path in targets:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                path.chmod(member.mode & 0o777)
                records.append(
                    {
                        "path": str(path.relative_to(destination)),
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "bytes": len(data),
                    }
                )
    plan = command_plan(robustness="scripts/ijm_saved_robustness.py" in names)
    run = destination / "RUN.sh"
    run.write_text(render_run(plan))
    run.chmod(0o755)
    (destination / "command-plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    (destination / "README.md").write_text(
        "# Prepared frozen-simulation replication\n\n"
        "Preparation has not run any simulation or installed an environment.\n"
        "The source tree is committed code; reference/ holds the saved result files.\n"
        "Only frozen Medicaid totals remain active; their construction is not rerun.\n"
        "RUN.sh starts a separate, expensive serial run, using Python 3.13.13 and\n"
        "requirements-expanded.txt. Set HEAVY_RUNNER to your site's resource\n"
        "wrapper; on Max's machine it defaults to the required heavy_run.sh.\n"
        "It verifies the public data file's bytes, then disables network data reads.\n"
        "All 16 original branches must match archived settings and outcomes before\n"
        "downstream summaries begin. Changes use five memory-bounded pairs per part.\n"
        "The comparison tolerance is relative 1e-9, absolute 1e-6; timing and commit\n"
        "identifiers may change, while computation hashes remain checked. The only\n"
        "source-hash equivalence is the exact archived addition of changes.py:\n"
        "all original modules must remain byte-identical, without importing it.\n"
        "The complete proof appears in PREPARE.json and comparison logs.\n"
        "When robustness is present, its reference result is required and checked.\n"
        "That check excludes regenerated per-part receipt hashes/path prefixes and\n"
        "the new run commit; scientific results and code/data identities remain.\n"
        "The April-2025 historical environment is separate: see source/april2025/README.md.\n"
        "The manuscript build is separate: see source/paper/README.md.\n"
        "RUN_STARTED prevents a cached resume from being mistaken for a fresh run.\n"
        "A failure leaves its evidence intact; prepare a different destination.\n"
        "Microdata-derived rows stay local and must not enter a public archive.\n"
    )
    for path in (run, destination / "command-plan.json", destination / "README.md"):
        records.append(
            {
                "path": str(path.relative_to(destination)),
                "sha256": digest(path),
                "bytes": path.stat().st_size,
            }
        )
    manifest = {
        "status": "PREPARED_NOT_EXECUTED",
        "source_commit": commit,
        "fixed_medicaid_totals": True,
        "python": "3.13.13",
        "data_revision": DATA_REVISION,
        "data_commit": DATA_COMMIT,
        "data_sha256": DATA_SHA256,
        "data_bytes": DATA_BYTES,
        "files": records,
        "original_source_equivalence": verified_code_equivalence(
            copied, destination / "reference"
        ),
    }
    (destination / "PREPARE.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def verify_manifest(destination: Path) -> int:
    """Verify the prepared source, saved references and command plan."""
    manifest = json.loads((destination / "PREPARE.json").read_text())
    copied = destination / "source"
    if git(copied, "rev-parse", "HEAD").decode().strip() != manifest["source_commit"]:
        raise ValueError("Prepared source HEAD differs from source_commit")
    if git(
        copied, "diff", "--cached", "--name-only", manifest["source_commit"]
    ).strip():
        raise ValueError("Prepared source index differs from source_commit")
    for item in manifest["files"]:
        path = destination / item["path"]
        if path.stat().st_size != item["bytes"] or digest(path) != item["sha256"]:
            raise ValueError(f"Prepared file hash/size mismatch: {item['path']}")
    return len(manifest["files"])


def verified_code_equivalence(workspace: Path, reference: Path) -> dict | None:
    """Prove the sole allowed old/new hash difference from exact source bytes.

    Original CLI modules are unchanged. The one added, unimported module affects
    the directory-wide provenance digest only; its exact bytes are allowlisted.
    Existing-module changes, extra additions and new imports all fail closed.
    """
    baseline = json.loads((reference / artifact_names("original")[0]).read_text())
    provenance = baseline.get("code")
    if not provenance:
        return None  # Synthetic preparation fixtures carry no scientific metadata.
    old_commit = provenance["commit"]
    old_names = [
        name
        for name in git(
            workspace, "ls-tree", "-r", "--name-only", old_commit, "--", "cliffs2017"
        )
        .decode()
        .splitlines()
        if PurePosixPath(name).suffix in (".py", ".csv")
    ]
    current_names = [
        str(path.relative_to(workspace))
        for path in (workspace / "cliffs2017").rglob("*")
        if path.is_file() and path.suffix in (".py", ".csv")
    ]

    def model_hash(names, reader):
        result = hashlib.sha256()
        for name in sorted(names, key=lambda name: PurePosixPath(name).parts):
            result.update(name.encode())
            result.update(reader(name))
        return result.hexdigest()

    old_hash = model_hash(
        old_names, lambda name: git(workspace, "show", f"{old_commit}:{name}")
    )
    new_hash = model_hash(current_names, lambda name: (workspace / name).read_bytes())
    if old_hash != provenance["cliffs2017_sha256"]:
        raise ValueError(
            "Archived original source hash is not held by its recorded commit"
        )
    if old_hash == new_hash:
        return None
    if (
        old_hash != ORIGINAL_HASH
        or new_hash != EXTENDED_HASH
        or set(current_names) != set(old_names) | {ADDED_MODULE}
        or ADDED_MODULE in old_names
    ):
        raise ValueError(
            "Model source differs beyond the exact approved module addition"
        )
    if digest(workspace / ADDED_MODULE) != ADDED_MODULE_HASH:
        raise ValueError("Added model module has changed")
    for name in old_names:
        data = git(workspace, "show", f"{old_commit}:{name}")
        if (workspace / name).read_bytes() != data:
            raise ValueError(f"Original execution module changed: {name}")
        if not name.endswith(".py"):
            continue
        for node in ast.walk(ast.parse(data)):
            if isinstance(node, ast.Import) and any(
                alias.name == "cliffs2017.changes" for alias in node.names
            ):
                raise ValueError("Original execution imports the added module")
            if isinstance(node, ast.ImportFrom) and (
                node.module in ("changes", "cliffs2017.changes")
                or node.module in (None, "cliffs2017")
                and any(alias.name == "changes" for alias in node.names)
            ):
                raise ValueError("Original execution imports the added module")
            if isinstance(node, ast.Call) and (
                isinstance(node.func, ast.Name)
                and node.func.id == "__import__"
                or isinstance(node.func, ast.Attribute)
                and node.func.attr == "import_module"
            ):
                raise ValueError(
                    "Dynamic model imports require a separate equivalence audit"
                )
    return {
        "baseline_commit": old_commit,
        "baseline_code_sha256": old_hash,
        "execution_code_sha256": new_hash,
        "only_added_module": ADDED_MODULE,
        "added_module_sha256": ADDED_MODULE_HASH,
        "existing_modules_byte_identical": True,
        "added_module_not_imported_by_originals": True,
    }


def differences(
    expected, actual, path: str = "root", equivalence: dict | None = None
) -> list[str]:
    """Compare settings and outcomes recursively, excluding volatile metadata."""
    if (
        equivalence
        and path.endswith(".code.cliffs2017_sha256")
        and expected == equivalence["baseline_code_sha256"]
        and actual == equivalence["execution_code_sha256"]
    ):
        return []
    if isinstance(expected, bool) or isinstance(actual, bool):
        return [] if type(expected) is type(actual) and expected == actual else [path]
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return (
            [] if math.isclose(expected, actual, rel_tol=1e-9, abs_tol=1e-6) else [path]
        )
    if isinstance(expected, dict) and isinstance(actual, dict):
        keys = (set(expected) | set(actual)) - VOLATILE
        failed = []
        for key in sorted(keys):
            if key not in expected or key not in actual:
                failed.append(f"{path}.{key}: missing field")
            else:
                failed.extend(
                    differences(
                        expected[key], actual[key], f"{path}.{key}", equivalence
                    )
                )
        return failed
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return [f"{path}: list lengths differ"]
        return [
            failed
            for i, (left, right) in enumerate(zip(expected, actual))
            for failed in differences(left, right, f"{path}[{i}]", equivalence)
        ]
    return [] if expected == actual else [path]


def compare_stage(stage: str, workspace: Path, reference: Path) -> int:
    """Refuse changed outcomes or absent regenerated per-person originals."""
    names = artifact_names(stage)
    equivalence = verified_code_equivalence(workspace, reference)
    if equivalence:
        print(
            json.dumps(
                {"verified_original_code_equivalence": equivalence}, sort_keys=True
            )
        )
    for name in names:
        expected = json.loads((reference / name).read_text())
        actual = json.loads((workspace / name).read_text())
        if stage == "robustness":
            expected, actual = (
                robustness_comparison_view(expected),
                robustness_comparison_view(actual),
            )
        failed = differences(expected, actual, equivalence=equivalence)
        if failed:
            raise ValueError(f"{name} differs: {failed[:20]}")
        if stage == "original":
            rows = (workspace / actual["cliff_parts_file"]).resolve()
            if (
                not rows.is_relative_to(workspace.resolve())
                or not rows.is_file()
                or rows.stat().st_size == 0
            ):
                raise ValueError(f"Missing or external per-person output for {name}")
    return len(names)


def robustness_comparison_view(result: dict) -> dict:
    """Keep scientific results and code/input identities; normalize rerun receipts.

    Per-part CSV gzip bytes, metadata timing/commit hashes and absolute paths
    differ after regeneration. Each run still validates its own file receipts.
    Safe effective thread limits (one or two) can differ without raising caller limits. Those runtime/input receipt fields are excluded here, never result values.
    """
    result = copy.deepcopy(result)
    thread_fields = {
        "BLIS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    }
    limits = result.pop("effective_thread_limits")
    if set(limits) != thread_fields or any(
        type(value) is not int or not 1 <= value <= 2 for value in limits.values()
    ):
        raise ValueError("Robustness receipt has unsafe or missing thread limits")
    result["code"].pop("commit_at_run", None)
    for year in result["years"].values():
        for part in year["parts"]:
            for receipt in part["inputs"]:
                for key in ("metadata_sha256", "rows_sha256"):
                    receipt.pop(key)
                for key in ("metadata_file", "rows_file"):
                    receipt[key] = "/".join(Path(receipt[key]).parts[-2:])
    return result


def verify_data() -> None:
    """Fetch the frozen public file and verify bytes before offline simulation."""
    from huggingface_hub import hf_hub_download

    path = Path(
        hf_hub_download(
            "policyengine/populace-us",
            "populace_us_2024.h5",
            repo_type="dataset",
            revision=DATA_REVISION,
        )
    )
    if path.parent.name != DATA_COMMIT:
        raise ValueError(
            "Frozen microdata release no longer resolves to its verified commit"
        )
    if path.stat().st_size != DATA_BYTES or digest(path) != DATA_SHA256:
        raise ValueError("Frozen microdata content does not match the verified release")
    print(
        json.dumps(
            {
                "revision": DATA_REVISION,
                "resolved_commit": DATA_COMMIT,
                "sha256": DATA_SHA256,
                "bytes": DATA_BYTES,
                "status": "PASS",
            }
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    preparing = commands.add_parser(
        "prepare", help="copy and plan only; run no analyses"
    )
    preparing.add_argument("destination", type=Path)
    preparing.add_argument("--source", type=Path, default=ROOT)
    preparing.add_argument("--ref", default="HEAD")
    comparing = commands.add_parser("compare")
    comparing.add_argument(
        "stage", choices=("original", "final", "summary", "robustness")
    )
    comparing.add_argument("--workspace", type=Path, default=ROOT)
    comparing.add_argument("--reference", type=Path, required=True)
    verifying = commands.add_parser("verify-prepared")
    verifying.add_argument("destination", type=Path)
    commands.add_parser("verify-data")
    args = parser.parse_args()
    if args.action == "prepare":
        result = prepare(args.source, args.destination, args.ref)
        print(
            json.dumps(
                {key: value for key, value in result.items() if key != "files"},
                indent=2,
            )
        )
    elif args.action == "compare":
        print(
            f"Verified {compare_stage(args.stage, args.workspace, args.reference)} {args.stage} artifacts"
        )
    elif args.action == "verify-prepared":
        print(f"Verified {verify_manifest(args.destination)} prepared files")
    else:
        verify_data()


if __name__ == "__main__":
    main()
