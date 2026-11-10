"""The run scripts refuse a CSFP setting other than keep before they run anything.

Only CSFP=keep changes what a run computes; any other value would still leave
CSFP out but tag the logs and labels "csfp". Each test runs a copy of the
scripts in an empty folder, with a runner that runs nothing, so a script that
failed to refuse couldn't touch the repository's results.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ["run_final.sh", "run_batch.sh", "runner.zsh"]
RUNS = {
    "run_final.sh": ["4", "0", "0", "2025-plain"],
    "run_batch.sh": ["0.25", "0"],
}


@pytest.fixture
def copy(tmp_path):
    (tmp_path / "scripts").mkdir()
    for name in SCRIPTS:
        shutil.copy(ROOT / "scripts" / name, tmp_path / "scripts" / name)
    return tmp_path


def run(copy, script, csfp):
    env = dict(os.environ, CLIFFS_RUNNER="true")
    env.pop("CSFP", None)
    if csfp is not None:
        env["CSFP"] = csfp
    return subprocess.run(
        ["zsh", str(copy / "scripts" / script), *RUNS[script]],
        cwd=copy,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.parametrize("script", sorted(RUNS))
@pytest.mark.parametrize("csfp", ["1", "yes", "Keep", "drop"])
def test_refuses_other_csfp_values(copy, script, csfp):
    result = run(copy, script, csfp)
    assert result.returncode == 2
    assert "CSFP must be unset or keep" in result.stderr
    assert not (copy / "logs").exists()  # it refused before writing anything


@pytest.mark.parametrize("script", sorted(RUNS))
@pytest.mark.parametrize("csfp", [None, "", "keep"])
def test_accepts_unset_or_keep(copy, script, csfp):
    result = run(copy, script, csfp)
    assert result.returncode == 0, result.stderr
    assert "CSFP must be" not in result.stderr


def test_counted_once_logs_each_part_and_its_exit_code(copy):
    """scripts/run_counted_once.sh logs a failed part's exit code, not the date's."""
    name = "run_counted_once.sh"
    shutil.copy(ROOT / "scripts" / name, copy / "scripts" / name)
    result = subprocess.run(
        ["zsh", str(copy / "scripts" / name), "4", "0", "0,1", "2017"],
        cwd=copy,
        env=dict(os.environ, CLIFFS_RUNNER="false"),  # a runner whose every run fails
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    log = (copy / "logs" / "counted_once.log").read_text()
    for part in (0, 1):
        assert f"start once 2017 part {part}/4 s=0" in log
        assert f"end once 2017 part {part} rc=1" in log
    assert not list((copy / "results" / "counted_once").glob("once_*.json"))  # nothing to combine
