"""scripts/health_only.py: how the count with health coverage relates to the count without it.

Invariants the tests check, for every input they draw:
- the adults in both counts plus the adults only in one add up to that count (a partition);
- no adult only in the count with health coverage sees the rest of their household's net
  income fall, and each sees its health parts fall, whenever the health run's change is the
  plain run's change plus its health parts;
- the weighted median splits the weights: the values below it hold less than half, and the
  values up to it hold at least half.
"""

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("health_only", ROOT / "scripts" / "health_only.py")
ho = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ho)


def frames(wages, snap, medicaid, credit, premium, weight):
    """A plain and a health frame for the same adults, built the way cliffs2017.run builds them."""
    wages, snap, medicaid, credit, premium, weight = (np.asarray(x, dtype=float) for x in (wages, snap, medicaid, credit, premium, weight))
    ids = np.arange(len(wages))
    plain = pd.DataFrame(dict(person_id=ids, d_household_market_income=wages, d_snap=snap, weight=weight))
    plain["d_net"] = plain[["d_household_market_income", "d_snap"]].sum(axis=1)
    health = plain.drop(columns="d_net").assign(d_medicaid_cost=medicaid, d_assigned_aca_ptc=credit, d_marketplace_net_premium=premium)
    health["d_net"] = plain["d_net"] + medicaid + credit + premium
    health["d_net_single_ptc"] = plain["d_net"] + medicaid + credit
    return plain, health


def test_overlap_on_a_hand_built_example():
    # 0: on a cliff both ways (loses SNAP). 1: only with health coverage (gains $700, loses $5,000 of Medicaid).
    # 2: only without it (loses SNAP, gains a larger credit). 3: on neither.
    plain, health = frames(
        wages=[1000, 1000, 1000, 1000], snap=[-1500, -300, -1200, 0],
        medicaid=[0, -5000, 0, 0], credit=[0, 0, 400, 0], premium=[0, -50, -50, 0], weight=[2, 3, 5, 7],
    )
    out = ho.compare(plain, health)
    assert out["people_on_cliff_with_health_coverage"] == 5
    assert out["people_on_cliff_without_health_coverage"] == 7
    assert out["in_both"] == dict(people=2.0, sample_people=1)
    assert out["only_without_health_coverage"] == dict(people=5.0, sample_people=1)
    only = out["only_with_health_coverage"]
    assert (only["people"], only["sample_people"]) == (3.0, 1)
    assert only["share_of_count_with_health_coverage"] == pytest.approx(0.6)
    assert only["change_in_rest_of_net_income"]["smallest"] == 700
    assert only["change_in_health_parts"]["largest"] == -5000
    # counted once, adult 1's $50 rise in the premium net of the credit stays out of the health parts
    assert only["change_in_health_parts"]["smallest"] == only["change_in_health_parts"]["largest"] == -5000


def test_refuses_health_rows_that_lack_a_plain_part():
    plain, health = frames([1000], [-1500], [0], [0], [0], [1])
    with pytest.raises(ValueError, match="lack parts"):
        ho.compare(plain, health.drop(columns="d_snap"))


amounts = st.floats(min_value=-20_000, max_value=20_000, allow_nan=False).map(lambda x: round(x, 2))
people = st.lists(st.tuples(amounts, amounts, amounts, amounts, st.floats(min_value=0.01, max_value=5_000)), min_size=1, max_size=30)


@given(people)
def test_the_counts_partition_and_the_signs_follow(rows):
    snap, medicaid, credit, premium, weight = (np.array(c) for c in zip(*rows))
    plain, health = frames(np.full(len(rows), 1000.0), snap, medicaid, credit, premium, weight)
    out = ho.compare(plain, health)
    both, only_with, only_without = out["in_both"], out["only_with_health_coverage"], out["only_without_health_coverage"]
    assert both["people"] + only_with["people"] == pytest.approx(out["people_on_cliff_with_health_coverage"])
    assert both["people"] + only_without["people"] == pytest.approx(out["people_on_cliff_without_health_coverage"])
    assert both["sample_people"] + only_with["sample_people"] == int((health["d_net_single_ptc"] < 0).sum())
    if only_with["sample_people"]:
        # not on a cliff before health coverage counts, on one after: the rest doesn't fall, the health parts do
        assert only_with["change_in_rest_of_net_income"]["smallest"] >= 0
        assert only_with["change_in_rest_of_net_income"]["sample_people_where_it_falls"] == 0
        assert only_with["change_in_health_parts"]["largest"] < 0


@given(st.lists(st.tuples(amounts, st.floats(min_value=0.01, max_value=5_000)), min_size=1, max_size=40))
def test_weighted_median_splits_the_weights(pairs):
    values, weights = (np.array(c) for c in zip(*pairs))
    m = ho.weighted_median(values, weights)
    assert m in values
    assert weights[values < m].sum() < weights.sum() / 2 * (1 + 1e-12)
    assert weights[values <= m].sum() >= weights.sum() / 2 * (1 - 1e-12)


def test_check_stops_on_a_count_the_rows_do_not_reproduce():
    ho.check("x", 100.0, 100.0 + 1e-8)
    with pytest.raises(ValueError, match="committed run"):
        ho.check("x", 100.0, 100.5)
