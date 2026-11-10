"""scripts/check_part_scaling.py passes only when part 0 times the part count
matches the subsample run, and refuses runs whose settings differ."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_part_scaling import SAMPLE, WEIGHTED, main  # noqa: E402

PARTS = 4


def runs():
    """A part-0 result and the subsample result it should match."""
    settings = {
        "year": 2017,
        "health_benefits_in_net_income": False,
        "aca_before_2018": True,
        "seed": 0,
        "versions": {"policyengine_us": "2.116.0", "policyengine_core": "3.34.10"},
        "dataset": "populace_us_2024.h5",
        "leave_out_csfp": False,
        "bootstrap_clusters": "household_source_id",
        "code": {"commit": "abc", "cliffs2017_sha256": "070af058"},
    }
    part = dict(settings, part=0, parts=PARTS)
    sub = dict(settings, fraction=1 / PARTS)
    for i, key in enumerate(WEIGHTED):
        part[key] = 1_000.0 * (i + 1) + 0.25
        sub[key] = part[key] * PARTS
    for i, key in enumerate(SAMPLE):
        part[key] = sub[key] = 10 * (i + 1)
    return part, sub


def check(tmp_path, monkeypatch, part, sub):
    """Run the script's main() on the two results; return its exit code."""
    paths = []
    for name, result in (("part.json", part), ("sub.json", sub)):
        path = tmp_path / name
        path.write_text(json.dumps(result))
        paths.append(str(path))
    monkeypatch.setattr(sys, "argv", ["check_part_scaling.py", str(PARTS), *paths])
    with pytest.raises(SystemExit) as exit_info:
        main()
    return exit_info.value.code


def test_passes_when_the_part_scales_to_the_subsample(tmp_path, monkeypatch):
    part, sub = runs()
    assert check(tmp_path, monkeypatch, part, sub) == 0


@pytest.mark.parametrize("key", WEIGHTED + SAMPLE)
def test_fails_on_any_gap(tmp_path, monkeypatch, key):
    part, sub = runs()
    sub[key] *= 1.001
    assert check(tmp_path, monkeypatch, part, sub) == 1


@pytest.mark.parametrize(
    "change",
    [
        lambda part, sub: part.update(part=1),
        lambda part, sub: part.update(parts=PARTS + 1),
        lambda part, sub: sub.update(fraction=0.5),
        lambda part, sub: sub.update(year=2025),
        lambda part, sub: sub.update(health_benefits_in_net_income=True),
        lambda part, sub: sub.update(aca_before_2018=False),
        lambda part, sub: sub.update(seed=1),
        lambda part, sub: sub.update(versions={"policyengine_us": "2.115.0"}),
        lambda part, sub: sub.update(dataset="other.h5"),
        lambda part, sub: sub.update(leave_out_csfp=True),
        lambda part, sub: sub.update(bootstrap_clusters="household_id"),
        lambda part, sub: sub.update(code={"commit": "abc", "cliffs2017_sha256": "other"}),
    ],
    ids=[
        "part",
        "parts",
        "fraction",
        "year",
        "health",
        "aca_before_2018",
        "seed",
        "versions",
        "dataset",
        "leave_out_csfp",
        "bootstrap_clusters",
        "code",
    ],
)
def test_refuses_runs_that_differ(tmp_path, monkeypatch, change):
    part, sub = runs()
    change(part, sub)
    code = check(tmp_path, monkeypatch, part, sub)
    # sys.exit with a message exits with status 1 and prints the message.
    assert isinstance(code, str) and code


def test_committed_results_pass(tmp_path, monkeypatch):
    """Each committed part 0 without health coverage matches its subsample run."""
    pairs = [
        ("results/parts/run_2017_plain_p4_0_s0.json", "results/run_2017_plain_f0.25_s0.json"),
        ("results/parts/run_2025_plain_p4_0_s0.json", "results/run_2025_plain_f0.25_s0.json"),
        ("results/parts/csfp/run_2025_plain_p4_0_s0.json", "results/csfp/run_2025_plain_f0.25_s0.json"),
    ]
    for part_path, sub_path in pairs:
        part = json.loads((ROOT / part_path).read_text())
        sub = json.loads((ROOT / sub_path).read_text())
        assert check(tmp_path, monkeypatch, part, sub) == 0, part_path
