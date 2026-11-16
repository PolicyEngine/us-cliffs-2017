"""Replication preparation never runs model commands or touches source outputs.

All command-plan checks pass argv as data; no heavy, destructive-shaped, or
guard-bypass probes are executed, including under stubs.
"""

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "prepare_ijm_replication.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("ijm_prepare", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tool():
    return load_tool()


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args]).decode().strip()


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "original"
    root.mkdir()
    git(root, "init", "--quiet")
    files = {
        "scripts/prepare_ijm_replication.py": TOOL.read_text(),
        "requirements-expanded.txt": "numpy==2.5.4\n",
        "cliffs2017/run.py": "# fixture only; never executed\n",
        "results/parts/run_2017_health_p4_0_s0.json": '{"people_on_cliff": 123}',
        "results/earnings_changes/parts/changes_2017_p4_0_s0/raise_1000.json": "{}",
        "results/earnings_changes.json": "{}",
        "results/medicaid/totals_2017_p4_s0.json": '{"frozen": true}',
        "paper/inputs/manifest.json": "{}",
        ".gitignore": ".venv/\nresults/parts/per_person/\n",
    }
    module = load_tool()
    for stage in ("original", "final", "summary"):
        for name in module.artifact_names(stage):
            files.setdefault(name, "{}")
    files["results/medicaid/totals_2025_p4_s0.json"] = '{"frozen": true}'
    files["cliffs2017/combine.py"] = "# fixture only; never executed\n"
    for name in (
        "counted_once",
        "earnings_changes",
        "take_up_bounds",
        "driver_intervals",
        "health_only",
        "earnings_changes_summary",
    ):
        files[f"scripts/{name}.py"] = "# fixture only; never executed\n"
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    git(root, "add", ".")
    tree = git(root, "write-tree")
    commit = git(
        root,
        "-c",
        "user.name=Replication test fixture",
        "-c",
        "user.email=replication-test@example.invalid",
        "commit-tree",
        tree,
        "-m",
        "Fixture, no model run",
    )
    git(root, "update-ref", "refs/heads/main", commit)
    git(root, "symbolic-ref", "HEAD", "refs/heads/main")
    (root / "untracked-session-note.txt").write_text("do not copy")
    return root


def test_preparation_copies_committed_source_and_separates_saved_results(
    tool, source, tmp_path
):
    destination = tmp_path / "fresh"
    before = git(source, "status", "--porcelain")
    manifest = tool.prepare(source, destination, "HEAD")
    copied = destination / "source"
    assert manifest["status"] == "PREPARED_NOT_EXECUTED"
    assert git(copied, "rev-parse", "HEAD") == git(source, "rev-parse", "HEAD")
    assert (copied / "cliffs2017/run.py").read_bytes() == (
        source / "cliffs2017/run.py"
    ).read_bytes()
    assert not (copied / "results/parts").exists()
    assert not (copied / "results/earnings_changes").exists()
    assert not (copied / "results/earnings_changes.json").exists()
    assert (copied / "results/medicaid/totals_2017_p4_s0.json").is_file()
    assert (destination / "reference/results/earnings_changes.json").is_file()
    assert not (copied / "untracked-session-note.txt").exists()
    assert not (copied / ".venv").exists()
    assert git(source, "status", "--porcelain") == before
    assert not git(copied, "status", "--porcelain", "--", "cliffs2017", "scripts")
    assert tool.verify_manifest(destination) == len(manifest["files"])
    parsed = subprocess.run(
        ["bash", "-n", str(destination / "RUN.sh")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert parsed.returncode == 0, parsed.stderr


def test_existing_destination_is_refused_without_changes(tool, source, tmp_path):
    destination = tmp_path / "existing"
    destination.mkdir()
    marker = destination / "preserve.txt"
    marker.write_text("preserve me")
    with pytest.raises(FileExistsError):
        tool.prepare(source, destination, "HEAD")
    assert list(destination.iterdir()) == [marker]
    assert marker.read_text() == "preserve me"


def test_dirty_preparer_cannot_claim_committed_provenance(tool, source, tmp_path):
    path = source / "scripts/prepare_ijm_replication.py"
    path.write_text(path.read_text() + "\n# uncommitted\n")
    with pytest.raises(ValueError, match="committed"):
        tool.prepare(source, tmp_path / "fresh", "HEAD")
    assert not (tmp_path / "fresh").exists()


def test_plan_regenerates_every_original_before_downstream_checks(tool):
    plan = tool.command_plan()
    originals = [item for item in plan if item["stage"] == "original"]
    assert len(originals) == 16
    settings = set()
    for item in originals:
        argv = item["argv"]
        assert argv[:3] == [".venv/bin/python", "-m", "cliffs2017.run"]
        assert "--decompose" in argv
        year = int(argv[argv.index("--year") + 1])
        part = int(argv[argv.index("--part") + 1])
        settings.add((year, part, "--health" in argv))
        assert ("--aca-before-2018" in argv) == (year == 2017)
        assert ("--leave-out-csfp" in argv) == (year == 2025)
    assert len(settings) == 16
    stages = [item["stage"] for item in plan]
    assert max(i for i, stage in enumerate(stages) if stage == "original") < (
        stages.index("compare-original")
    )
    assert stages.index("compare-original") < stages.index("counted-once")
    changes = [item for item in plan if item["stage"] == "changes"]
    assert len(changes) == 40  # two years x four parts x five memory-bounded pairs
    assert all(item["heavy"] for item in originals + changes)
    commands = [arg for item in plan for arg in item["argv"]]
    assert "scripts/run_final.sh" not in commands
    assert "scripts/run_earnings_changes.sh" not in commands


def test_comparison_checks_numbers_but_accepts_volatile_provenance(tool):
    original = {"people_on_cliff": 100.0, "code": {"commit": "old", "hash": "same"}}
    rebuilt = {"people_on_cliff": 100.0, "code": {"commit": "new", "hash": "same"}}
    assert tool.differences(original, rebuilt) == []
    rebuilt["people_on_cliff"] = 101.0
    assert any(
        "people_on_cliff" in item for item in tool.differences(original, rebuilt)
    )
    assert tool.differences({"required": 1}, {})
    assert tool.differences({"settings": True}, {"settings": 1})


@given(st.floats(min_value=1_000, max_value=1_000_000_000, allow_nan=False))
def test_comparison_never_ignores_material_numeric_change(value):
    tool = load_tool()
    original = {"nested": {"people": value}}
    rebuilt = {"nested": {"people": value + max(1.0, value * 0.00001)}}
    assert tool.differences(original, rebuilt)


def test_modified_archive_is_detected(tool, source, tmp_path):
    destination = tmp_path / "fresh"
    tool.prepare(source, destination, "HEAD")
    path = destination / "reference/results/earnings_changes.json"
    path.write_text(json.dumps({"changed": True}))
    with pytest.raises(ValueError, match="hash"):
        tool.verify_manifest(destination)


def test_original_checkpoint_requires_rebuilt_rows(tool, tmp_path):
    workspace, reference = tmp_path / "working", tmp_path / "reference"
    for name in tool.artifact_names("original"):
        for root in (workspace, reference):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "people_on_cliff": 123.0,
                        "cliff_parts_file": "results/parts/per_person/rows.csv.gz",
                    }
                )
            )
    with pytest.raises(ValueError, match="per-person"):
        tool.compare_stage("original", workspace, reference)
    rows = workspace / "results/parts/per_person/rows.csv.gz"
    rows.parent.mkdir(parents=True)
    rows.write_bytes(b"fixture bytes, never loaded as model output")
    assert tool.compare_stage("original", workspace, reference) == 16


def test_robustness_plan_uses_frozen_python_and_required_cli(tool):
    item = next(
        item
        for item in tool.command_plan(robustness=True)
        if item["stage"] == "robustness"
    )
    assert item["argv"][:2] == [".venv/bin/python", "scripts/ijm_saved_robustness.py"]
    assert item["argv"][item["argv"].index("--draws") + 1] == "5000"
    assert item["heavy"] is True
    shell = tool.render_run(tool.command_plan())
    assert "requirements-expanded.txt" in shell
    assert "heavy_run.sh" in shell
    assert "RUN_STARTED" in shell
    assert "export HF_HUB_OFFLINE=1" in shell
    assert tool.command_plan(robustness=True)[-1]["stage"] == "compare-robustness"


def test_actual_archived_source_equivalence_is_narrowly_verified(tool):
    proof = tool.verified_code_equivalence(ROOT, ROOT)
    assert proof["baseline_code_sha256"] == tool.ORIGINAL_HASH
    assert proof["execution_code_sha256"] == tool.EXTENDED_HASH
    expected = {"code": {"cliffs2017_sha256": tool.ORIGINAL_HASH}}
    actual = {"code": {"cliffs2017_sha256": tool.EXTENDED_HASH}}
    assert tool.differences(expected, actual, equivalence=proof) == []
    assert tool.differences(expected, actual)
    actual["code"]["cliffs2017_sha256"] = "unapproved-hash"
    assert tool.differences(expected, actual, equivalence=proof)
    assert tool.differences(
        {"other": tool.ORIGINAL_HASH}, {"other": tool.EXTENDED_HASH}, equivalence=proof
    )


def test_equivalence_refuses_any_additional_model_source_change(
    tool, source, tmp_path, monkeypatch
):
    def model_hash():
        result = hashlib.sha256()
        for path in sorted((source / "cliffs2017").rglob("*.py")):
            result.update(str(path.relative_to(source)).encode())
            result.update(path.read_bytes())
        return result.hexdigest()

    original = model_hash()
    baseline_commit = git(source, "rev-parse", "HEAD")
    added = source / "cliffs2017/changes.py"
    added.write_text("# added test module; no simulation\n")
    monkeypatch.setattr(tool, "ORIGINAL_HASH", original)
    monkeypatch.setattr(tool, "EXTENDED_HASH", model_hash())
    monkeypatch.setattr(tool, "ADDED_MODULE_HASH", tool.digest(added))
    reference = tmp_path / "reference"
    receipt = reference / tool.artifact_names("original")[0]
    receipt.parent.mkdir(parents=True)
    receipt.write_text(
        json.dumps({"code": {"commit": baseline_commit, "cliffs2017_sha256": original}})
    )
    assert tool.verified_code_equivalence(source, reference)
    (source / "cliffs2017/run.py").write_text("# changed old module\n")
    with pytest.raises(ValueError, match="approved"):
        tool.verified_code_equivalence(source, reference)


@pytest.mark.parametrize("target", ["HEAD", "index"])
def test_prepared_git_identity_is_checked(tool, source, tmp_path, target):
    destination = tmp_path / "fresh"
    tool.prepare(source, destination, "HEAD")
    copied = destination / "source"
    if target == "HEAD":
        tree = git(copied, "rev-parse", "HEAD^{tree}")
        commit = git(
            copied,
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit-tree",
            tree,
            "-m",
            "Different identity",
        )
        git(copied, "update-ref", "HEAD", commit)
    else:
        (copied / "extra-index-file.txt").write_text("index check fixture")
        git(copied, "add", "extra-index-file.txt")
    with pytest.raises(ValueError, match=target):
        tool.verify_manifest(destination)


def test_robustness_comparison_retains_scientific_values_and_code_hash(tool):
    def result(prefix, receipt_hash, commit, value=123):
        return {
            "code": {"commit_at_run": commit, "script_sha256": "same-code"},
            "effective_thread_limits": {
                name: 2
                for name in (
                    "BLIS_NUM_THREADS",
                    "MKL_NUM_THREADS",
                    "NUMEXPR_NUM_THREADS",
                    "OMP_NUM_THREADS",
                    "OPENBLAS_NUM_THREADS",
                    "VECLIB_MAXIMUM_THREADS",
                )
            },
            "years": {
                "2017": {
                    "points": {"adults": value},
                    "parts": [
                        {
                            "inputs": [
                                {
                                    "metadata_file": prefix + "/part/raise_1000.json",
                                    "rows_file": prefix
                                    + "/per_person/year-part.csv.gz",
                                    "metadata_sha256": receipt_hash,
                                    "rows_sha256": receipt_hash,
                                }
                            ]
                        }
                    ],
                }
            },
        }

    original = tool.robustness_comparison_view(
        result("/first", "first-receipt", "first-commit")
    )
    actual = tool.robustness_comparison_view(
        result("/second", "second-receipt", "second-commit")
    )
    assert tool.differences(original, actual) == []
    changed = tool.robustness_comparison_view(
        result("/second", "second-receipt", "second-commit", value=124)
    )
    assert tool.differences(original, changed)
    actual["code"]["script_sha256"] = "different-code"
    assert tool.differences(original, actual)


def test_robustness_runtime_receipt_allows_lower_safe_thread_limits(tool):
    import copy

    values = {
        name: 2
        for name in (
            "BLIS_NUM_THREADS",
            "MKL_NUM_THREADS",
            "NUMEXPR_NUM_THREADS",
            "OMP_NUM_THREADS",
            "OPENBLAS_NUM_THREADS",
            "VECLIB_MAXIMUM_THREADS",
        )
    }
    source = {
        "code": {"commit_at_run": "fixture", "script_sha256": "same"},
        "effective_thread_limits": values,
        "years": {},
    }
    lower = copy.deepcopy(source)
    lower["effective_thread_limits"] = {name: 1 for name in values}
    assert tool.robustness_comparison_view(source) == tool.robustness_comparison_view(
        lower
    )
    assert source["effective_thread_limits"] == values
    for bad in (0, 3, "2", True):
        unsafe = copy.deepcopy(source)
        unsafe["effective_thread_limits"]["OMP_NUM_THREADS"] = bad
        with pytest.raises(ValueError, match="thread limits"):
            tool.robustness_comparison_view(unsafe)
