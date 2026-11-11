"""The summary's bookkeeping (scripts/earnings_changes_summary.py), on made-up rows.

1. Either side: every adult flagged under a raise or the cut of the same size
   gets exactly one row, whichever change reaches them.
2. The part that moves most against a change: the largest loss under a raise,
   the largest gain under a cut, never market income, and with health coverage
   counted once the marketplace premium net of the credit is left out.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from hypothesis import given
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.earnings_changes_summary import driver, either_side, moving_parts  # noqa: E402


@given(st.data())
def test_either_side_counts_each_adult_once(data):
    n = data.draw(st.integers(1, 30))
    reached_up = data.draw(st.lists(st.booleans(), min_size=n, max_size=n))
    reached_down = data.draw(st.lists(st.booleans(), min_size=n, max_size=n))
    person, keys, up_flags, down_flags = [], [], [], []
    for i in range(n):
        for key, reached in (("raise_1000", reached_up[i]), ("cut_1000", reached_down[i])):
            if reached:
                person.append(i)
                keys.append(key)
                flag = data.draw(st.booleans())
                up_flags.append(flag and key == "raise_1000")
                down_flags.append(flag and key == "cut_1000")
    person = np.array(person, dtype=int)
    keys = np.array(keys, dtype=object)
    either = either_side(person, keys, "raise_1000", "cut_1000", up_flags, down_flags)
    expected = set(person[np.array(up_flags, dtype=bool)]) | set(person[np.array(down_flags, dtype=bool)])
    assert sorted(person[either]) == sorted(expected)
    # The raise's row wins whenever the raise reaches the adult.
    for i in expected:
        row = np.flatnonzero(either & (person == i))[0]
        assert keys[row] == ("raise_1000" if reached_up[i] else "cut_1000")


def test_driver_and_parts():
    rows = pd.DataFrame(
        {
            "d_household_market_income": [1000.0, -1000.0],
            "d_snap": [-300.0, 250.0],
            "d_medicaid_cost": [-1500.0, 0.0],
            "d_marketplace_net_premium": [-2000.0, 0.0],
            "d_assigned_aca_ptc": [0.0, 900.0],
            "d_net": [-2800.0, 150.0],
            "d_parts": [-2800.0, 150.0],
            "d_net_single_ptc": [-800.0, 150.0],
            "d_net_without_health": [700.0, -750.0],
        }
    )
    health = ["d_medicaid_cost", "d_assigned_aca_ptc", "d_marketplace_net_premium"]
    with_health = moving_parts(rows, "with_health", health)
    assert "d_marketplace_net_premium" not in with_health and "d_household_market_income" not in with_health
    assert moving_parts(rows, "without_health", health) == ["d_snap"]
    assert list(driver(rows.iloc[[0]], with_health, 1)) == ["medicaid_cost"]
    assert list(driver(rows.iloc[[1]], with_health, -1)) == ["assigned_aca_ptc"]


def test_against_uses_signs_not_the_product():
    from scripts.earnings_changes_summary import against

    # The product of these underflows to -0.0, which isn't < 0; the signs still disagree.
    assert against([5.8e-205], [-6.4e-167]).tolist() == [True]
    assert against([1000.0, -1000.0, 1000.0, -1000.0, 0.0], [-1.0, 1.0, 1.0, -1.0, -5.0]).tolist() == [
        True, True, False, False, False
    ]


def test_code_hash_at_head_matches_code_version():
    """The summary's hash of a commit's cliffs2017/ equals what runs record (cliffs2017.run.code_version)."""
    import subprocess

    import pytest

    from cliffs2017.run import ROOT, code_version
    from scripts.earnings_changes_summary import code_hash_at

    dirty = subprocess.run(["git", "status", "--porcelain", "--", "cliffs2017"], cwd=ROOT,
                           capture_output=True, text=True).stdout.strip()
    untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "--", "cliffs2017"],
                               cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if dirty or untracked:
        pytest.skip("cliffs2017/ differs from HEAD")
    assert code_hash_at("HEAD") == code_version()["cliffs2017_sha256"]


def test_check_code_accepts_commits_with_the_same_code_and_refuses_others():
    import pytest

    from scripts.earnings_changes_summary import check_code, code_hash_at, script_hash_at

    good = dict(commit="HEAD", cliffs2017_sha256=code_hash_at("HEAD"),
                script_sha256=script_hash_at("HEAD", "scripts/earnings_changes.py"))
    assert check_code(2017, [dict(code=good), dict(code=good)])["commits"] == ["HEAD"]
    with pytest.raises(ValueError, match="different code"):
        check_code(2017, [dict(code=good), dict(code=dict(good, script_sha256="0" * 64))])
    with pytest.raises(ValueError, match="doesn't hold"):
        check_code(2017, [dict(code=dict(good, cliffs2017_sha256="0" * 64))])


def _write_part(root, year, part, keys, reproduces=True):
    import json

    folder = root / "results" / "earnings_changes" / "parts" / f"changes_{year}_p4_{part}_s0"
    folder.mkdir(parents=True, exist_ok=True)
    rows_dir = root / "results" / "parts" / "per_person"
    rows_dir.mkdir(parents=True, exist_ok=True)
    for key in keys:
        sign = 1 if key.startswith("raise") else -1
        frame = pd.DataFrame(
            {
                "change_key": key,
                "person_id": [10 * part + 1, 10 * part + 2],
                "household_id": [part, part],
                "change": [sign * 1000.0, sign * 1000.0],
                "d_net_without_health": [-sign * 5.0, sign * 600.0],
                "d_net_single_ptc": [-sign * 5.0, -sign * 7.0],
                "weight": [2.0, 3.0],
            }
        )
        rows = rows_dir / f"changes_{year}_p4_{part}_s0_{key}.csv.gz"
        frame.to_csv(rows, index=False)
        record = dict(
            year=year, parts=4, part=part, seed=0, versions={"x": "1"}, stored_input_renames={}, health_parts=[],
            workers=10.0, people_total=20.0, dataset="d", key=key,
            change=dict(adults_reached=5.0, without_health=dict(people_on_cliff=2.0),
                        with_health=dict(people_on_cliff=5.0)),
            reproduces_committed_part=reproduces if key == "raise_1000" else None,
            per_person_file=str(rows.relative_to(root)), code=dict(commit="c", cliffs2017_sha256="a", script_sha256="b"),
        )
        (folder / f"{key}.json").write_text(json.dumps(record))


def test_load_year_reads_one_file_per_change(tmp_path, monkeypatch):
    import pytest

    import scripts.earnings_changes_summary as summary

    monkeypatch.setattr(summary, "ROOT", tmp_path)
    monkeypatch.setattr(summary, "PARTS", tmp_path / "results" / "earnings_changes" / "parts")
    for part in range(4):
        # Written cut first: the summary must still list the changes in the script's order.
        _write_part(tmp_path, 2017, part, ["cut_1000", "raise_1000"])
    parts, rows = summary.load_year(2017, "d")
    assert [list(p["changes"]) for p in parts] == [["raise_1000", "cut_1000"]] * 4
    assert len(rows) == 16 and set(rows["change_key"]) == {"raise_1000", "cut_1000"}
    # A $1,000 raise that doesn't reproduce the committed part stops the summary.
    _write_part(tmp_path, 2017, 2, ["raise_1000"], reproduces=False)
    with pytest.raises(ValueError, match="doesn't reproduce"):
        summary.load_year(2017, "d")
    _write_part(tmp_path, 2017, 2, ["raise_1000"], reproduces=True)
    # A part missing a change the others ran stops it too.
    (tmp_path / "results" / "earnings_changes" / "parts" / "changes_2017_p4_3_s0" / "cut_1000.json").unlink()
    with pytest.raises(ValueError, match="different changes"):
        summary.load_year(2017, "d")
