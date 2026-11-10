"""scripts/driver_intervals.py: intervals for the counts by largest loss, and their support.

Invariants the tests check, for every input they draw:
- support(): the fewest households that supply half of a count do supply at least half,
  one fewer don't, and Kish's effective number lies between 1 and the households that
  carry the count;
- resample(): every resample draws as many source households as the dataset holds, it
  skips only rows that are all zero without changing a draw, and with run.py's clusters
  and seed it reproduces cliffs2017.run.bootstrap's standard error;
- largest_loss() and counts(): each adult's largest loss is the one cliffs2017.run assigns,
  and a run whose committed counts the rows don't reproduce stops the script.
"""

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("driver_intervals", ROOT / "scripts" / "driver_intervals.py")
di = importlib.util.module_from_spec(spec)
spec.loader.exec_module(di)

totals_lists = st.lists(st.floats(min_value=0, max_value=1e6, allow_nan=False), min_size=1, max_size=40)


def rows(**columns) -> pd.DataFrame:
    n = len(next(iter(columns.values())))
    base = {
        "person_id": np.arange(n),
        "household_id": np.arange(n),
        "weight": np.ones(n),
        "d_net": np.zeros(n),
        "d_net_single_ptc": np.zeros(n),
        "d_household_market_income": np.full(n, 1000.0),
        "d_assigned_aca_ptc": np.zeros(n),
        "d_marketplace_net_premium": np.zeros(n),
        "d_medicaid_cost": np.zeros(n),
        "d_snap": np.zeros(n),
    }
    base.update({k: np.asarray(v) for k, v in columns.items()})
    return pd.DataFrame(base)


def test_counting_the_credit_once_leaves_out_the_net_premium():
    # Row 0 loses $500 of credit, and its premium net of the credit rises by $500 (a -500 part
    # that is $100 larger here), so the model's own count names the premium; counting the credit
    # once, the credit is the largest loss. Row 1 isn't on a cliff, row 2 loses SNAP.
    frame = rows(
        d_net=[-700, 50, -20],
        d_net_single_ptc=[-100, 50, -20],
        d_assigned_aca_ptc=[-500, 0, 0],
        d_marketplace_net_premium=[-600, 0, 0],
        d_snap=[0, 0, -300],
    )
    modeled = di.largest_loss(frame, "d_net")
    once = di.largest_loss(frame, "d_net_single_ptc")
    assert modeled["driver"].tolist() == ["marketplace_net_premium", "snap"]
    assert once["driver"].tolist() == ["assigned_aca_ptc", "snap"]
    # market income rises with the raise and never counts as a loss
    assert "household_market_income" not in set(modeled["driver"]) | set(once["driver"])


def test_source_index_draws_both_records_of_a_household_together():
    households = pd.DataFrame({"household_id": [10, 11, 12, 13], "household_source_id": [7, 3, 7, 9]})
    index, n = di.source_index(np.array([12, 10, 11, 13, 10]), households)
    assert n == 3
    # sorted source ids 3, 7, 9: households 10 and 12 share source 7
    assert index.tolist() == [1, 1, 0, 2, 1]


def test_source_index_refuses_unknown_or_repeated_households():
    households = pd.DataFrame({"household_id": [10, 11], "household_source_id": [1, 2]})
    with pytest.raises(ValueError, match="aren't in the household table"):
        di.source_index(np.array([10, 99]), households)
    repeated = pd.DataFrame({"household_id": [10, 10], "household_source_id": [1, 2]})
    with pytest.raises(ValueError, match="repeats a household_id"):
        di.source_index(np.array([10]), repeated)


def test_support_on_a_small_example():
    s = di.support(np.array([0.0, 5.0, 3.0, 2.0]), sample_people=6)
    assert s["sample_people_on_cliff"] == 6
    assert s["source_households"] == 3
    # 5 of the 10 is half
    assert s["source_households_for_half"] == 1
    assert s["kish_effective_source_households"] == pytest.approx(100 / 38)
    empty = di.support(np.zeros(4), sample_people=0)
    assert empty["source_households"] == empty["source_households_for_half"] == 0


@given(totals_lists)
def test_support_invariants(values):
    totals = np.array(values)
    s = di.support(totals, sample_people=len(values))
    held = np.sort(totals[totals > 0])[::-1]
    if held.sum() == 0:
        assert s["source_households"] == 0
        return
    k = s["source_households_for_half"]
    assert 1 <= k <= s["source_households"] == len(held)
    assert held[:k].sum() >= held.sum() / 2 * (1 - 1e-12)
    assert held[: k - 1].sum() < held.sum() / 2
    assert 1 - 1e-9 <= s["kish_effective_source_households"] <= len(held) * (1 + 1e-9)


@given(st.integers(min_value=1, max_value=60), st.integers(min_value=0, max_value=2**32 - 1))
def test_every_resample_draws_as_many_households_as_the_dataset_holds(n, seed):
    draws = di.resample(np.ones((n, 1)), draws=20, seed=seed)
    assert (draws[:, 0] == n).all()


@given(
    st.lists(st.lists(st.floats(min_value=0, max_value=1e5, allow_nan=False), min_size=3, max_size=3), min_size=1, max_size=30),
    st.integers(min_value=0, max_value=2**32 - 1),
)
def test_skipping_zero_rows_changes_no_draw(table, seed):
    stats = np.array(table)
    stats[::2] = 0  # every other source household carries none of any count
    fast = di.resample(stats, draws=15, seed=seed)
    rng = np.random.default_rng(seed)
    n = len(stats)
    slow = np.array([rng.multinomial(n, np.full(n, 1 / n)) @ stats for _ in range(15)])
    np.testing.assert_allclose(fast, slow, rtol=1e-12, atol=1e-9)


def test_resample_reproduces_the_run_bootstrap():
    # The same clusters and seed as cliffs2017.run.bootstrap give the same standard error.
    from cliffs2017.run import bootstrap

    rng = np.random.default_rng(5)
    household = np.repeat(np.arange(40), 2)
    cluster = household // 2  # two household records per source household
    weight = rng.uniform(0.01, 3000, 40)[household]
    on = rng.random(80) < 0.3
    people = pd.DataFrame(dict(household_id=household, cluster=cluster, weight=weight, worker=np.ones(80, bool)))
    se = bootstrap(people, on, draws=200, seed=0)["people_on_cliff"]
    _, index = np.unique(cluster, return_inverse=True)
    stats = np.bincount(index, weights=weight * on, minlength=index.max() + 1)[:, None]
    ours = di.resample(stats, draws=200, seed=0)[:, 0].std(ddof=1)
    assert ours == pytest.approx(se, rel=1e-12)


def test_the_mean_resample_total_is_close_to_the_estimate():
    stats = np.zeros((500, 1))
    stats[:10, 0] = np.arange(1, 11) * 100.0
    draws = di.resample(stats, draws=4000, seed=1)[:, 0]
    # E[total] equals the estimate; 4,000 draws pin the mean to about 1.5% of the SE times 3
    assert abs(draws.mean() - stats.sum()) < 3 * draws.std(ddof=1) / np.sqrt(4000)
    lo, hi = di.interval(draws)
    assert lo < stats.sum() < hi


def final_for(frame, health=True):
    modeled = di.largest_loss(frame, "d_net")
    once = di.largest_loss(frame, "d_net_single_ptc")
    return dict(
        health_benefits_in_net_income=health,
        people_on_cliff=float(modeled["weight"].sum()),
        people_on_cliff_by_driver=modeled.groupby("driver")["weight"].sum().to_dict(),
        premium_tax_credit_counted_once=dict(
            people_on_cliff=float(once["weight"].sum()),
            people_on_cliff_by_driver=once.groupby("driver")["weight"].sum().to_dict(),
        ),
    )


def test_counts_checks_the_committed_run():
    frame = rows(
        d_net=[-700, -20, -5],
        d_net_single_ptc=[-100, -20, -5],
        d_assigned_aca_ptc=[-500, 0, 0],
        d_marketplace_net_premium=[-600, 0, 0],
        d_snap=[0, -300, -40],
        weight=[2.0, 3.0, 4.0],
    )
    final = final_for(frame)
    got = di.counts("2017_health", frame, final)
    assert set(got) == {"as_modeled", "credit_counted_once"}
    # A run without health coverage reports the model's own count only.
    assert set(di.counts("2017_plain", frame, final_for(frame, health=False))) == {"as_modeled"}

    off_total = final_for(frame)
    off_total["people_on_cliff"] += 1
    with pytest.raises(ValueError, match="committed run"):
        di.counts("2017_health", frame, off_total)
    off_driver = final_for(frame)
    off_driver["premium_tax_credit_counted_once"]["people_on_cliff_by_driver"]["snap"] += 0.5
    with pytest.raises(ValueError, match="snap"):
        di.counts("2017_health", frame, off_driver)
    extra = final_for(frame)
    extra["people_on_cliff_by_driver"]["tanf"] = 0.0
    with pytest.raises(ValueError, match="largest losses"):
        di.counts("2017_health", frame, extra)
