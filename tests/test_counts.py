"""Invariants of the headline counts and their bootstrap standard errors.

For any set of households with household-level weights:
1. households with someone on a cliff <= people on a cliff
   <= people in those households <= everyone;
2. workers on a cliff <= people on a cliff;
3. flagging more people never lowers a count (monotonicity);
4. with nobody on a cliff, every count and standard error is zero;
5. the bootstrap standard error of each total agrees with the closed form for
   resampling n households with replacement, sqrt(sum y_i^2 - T^2 / n)
   (differential test).
"""

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from cliffs2017.run import bootstrap, headline


@st.composite
def households(draw):
    sizes = draw(st.lists(st.integers(1, 6), min_size=2, max_size=40))
    weights = draw(
        st.lists(st.floats(1, 5_000, allow_nan=False), min_size=len(sizes), max_size=len(sizes))
    )
    rows = []
    for h, (size, weight) in enumerate(zip(sizes, weights)):
        for _ in range(size):
            rows.append((h, weight))
    people = pd.DataFrame(rows, columns=["household_id", "weight"])
    n = len(people)
    people["worker"] = draw(st.lists(st.booleans(), min_size=n, max_size=n))
    on_cliff = np.array(draw(st.lists(st.booleans(), min_size=n, max_size=n)))
    return people, on_cliff


@given(households())
def test_count_ordering(data):
    people, on_cliff = data
    c = headline(people, on_cliff)
    everyone = people["weight"].sum()
    eps = 1e-6 * max(everyone, 1)
    assert c["households_with_person_on_cliff"] <= c["people_on_cliff"] + eps
    assert c["people_on_cliff"] <= c["people_in_those_households"] + eps
    assert c["people_in_those_households"] <= everyone + eps
    assert c["workers_on_cliff"] <= c["people_on_cliff"] + eps


@given(households(), st.data())
def test_more_flags_never_lower_counts(data, extra):
    people, on_cliff = data
    more = on_cliff | np.array(
        extra.draw(st.lists(st.booleans(), min_size=len(on_cliff), max_size=len(on_cliff)))
    )
    before, after = headline(people, on_cliff), headline(people, more)
    for key in before:
        assert after[key] >= before[key] - 1e-6 * max(before[key], 1)


@given(households())
def test_nobody_on_a_cliff(data):
    people, on_cliff = data
    none = np.zeros_like(on_cliff)
    assert all(v == 0 for v in headline(people, none).values())
    assert all(v == 0 for v in bootstrap(people, none, draws=20).values())


def test_bootstrap_matches_closed_form():
    rng = np.random.default_rng(3)
    n_households = 400
    sizes = rng.integers(1, 6, n_households)
    weights = rng.uniform(100, 3_000, n_households)
    household_id = np.repeat(np.arange(n_households), sizes)
    people = pd.DataFrame(
        dict(household_id=household_id, weight=weights[household_id])
    )
    people["worker"] = rng.random(len(people)) < 0.6
    on_cliff = rng.random(len(people)) < 0.15
    draws = 4_000
    se = bootstrap(people, on_cliff, draws=draws, seed=11)

    frame = people.assign(on_cliff=on_cliff, worker_on=on_cliff & people["worker"])
    g = frame.groupby("household_id").agg(
        w=("weight", "first"),
        m=("weight", "size"),
        p=("on_cliff", "sum"),
        k=("worker_on", "sum"),
        a=("on_cliff", "any"),
    )
    totals = dict(
        people_on_cliff=g.w * g.p,
        workers_on_cliff=g.w * g.k,
        households_with_person_on_cliff=g.w * g.a,
        people_in_those_households=g.w * g.m * g.a,
    )
    for key, y in totals.items():
        y = y.to_numpy(dtype=float)
        closed = np.sqrt((y**2).sum() - y.sum() ** 2 / len(y))
        # With 4,000 draws the bootstrap SE has about 1% relative error.
        assert se[key] == pytest.approx(closed, rel=0.05), key


@settings(max_examples=20)
@given(households())
def test_bootstrap_is_deterministic(data):
    people, on_cliff = data
    assert bootstrap(people, on_cliff, draws=30, seed=5) == bootstrap(
        people, on_cliff, draws=30, seed=5
    )
