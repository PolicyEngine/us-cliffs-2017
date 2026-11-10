"""Invariants of the backward adjustment from the 2024 build to an earlier year.

For every target year before the dataset's year:
1. each adjusted column equals the 2024 column times its factor, exactly;
2. every other column is unchanged, except calendar-year columns, which
   never exceed the target year;
3. each factor equals the ratio of its index between the two years, and the
   Social Security factor composes across intermediate years;
4. the household weights scale with the population index, so weighted
   household and person totals move by that factor;
5. row counts and identifiers are unchanged.
Subsampling keeps whole households and divides weights by the fraction.
Partitioning splits households into disjoint groups that cover every
household once at full weight; group 0 equals the matching subsample.
"""

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from cliffs2017.deflate import (
    COLA_COLUMNS,
    YEAR_COLUMNS,
    cola_ratio,
    column_factors,
    deflate,
    index_factors,
    partition,
    subsample,
)

BASE = 2024
YEARS = st.integers(min_value=2015, max_value=BASE - 1)


def tables(dataset):
    return dict(zip(dataset.table_names, dataset.tables))


@given(st.lists(YEARS, min_size=2, max_size=2, unique=True))
def test_cola_ratio_composes(system, pair):
    target, middle = sorted(pair)
    direct = cola_ratio(system.parameters, target, BASE)
    stepped = cola_ratio(system.parameters, target, middle) * cola_ratio(
        system.parameters, middle, BASE
    )
    assert direct == pytest.approx(stepped, rel=1e-12)


def test_cola_ratio_identity(system):
    assert cola_ratio(system.parameters, BASE, BASE) == 1


def test_cola_ratio_2017_matches_published_colas(system):
    # SSA COLAs paid from January 2018 through January 2024:
    # 2.0, 2.8, 1.6, 1.3, 5.9, 8.7 and 3.2 percent.
    published = np.prod([1.020, 1.028, 1.016, 1.013, 1.059, 1.087, 1.032])
    assert cola_ratio(system.parameters, 2017, BASE) == pytest.approx(1 / published, rel=1e-9)


@given(YEARS)
def test_index_factors_fall_below_one(system, target):
    # A data property of 2015-2024, not a law: wages, prices and benefits
    # rose over every year in this range.
    for value in index_factors(system, target, BASE).values():
        assert 0 < value < 1


@pytest.mark.parametrize("target", [2015, 2017, 2020, 2023])
def test_deflate_scales_each_column_by_its_factor(system, small_dataset, target):
    out, factors = deflate(small_dataset, system, target)
    before, after = tables(small_dataset), tables(out)
    adjusted = set()
    for row in factors.itertuples():
        expected = before[row.entity][row.column].to_numpy(dtype=np.float64) * row.factor
        np.testing.assert_array_equal(after[row.entity][row.column].to_numpy(), expected)
        adjusted.add((row.entity, row.column))
    for entity, frame in before.items():
        assert len(after[entity]) == len(frame)
        for column in frame.columns:
            if (entity, column) in adjusted:
                continue
            if column in YEAR_COLUMNS:
                values = after[entity][column].to_numpy()
                assert np.all(values[~np.isnan(values)] <= target)
                continue
            pd.testing.assert_series_equal(
                after[entity][column].reset_index(drop=True),
                frame[column].reset_index(drop=True),
                check_names=False,
            )
    assert int(out.time_period) == target


def test_deflate_uses_published_indices_for_2017(system, small_dataset):
    factors = {
        row.column: (row.index, row.factor)
        for row in column_factors(small_dataset, system, 2017)
    }
    p = system.parameters
    nawi = p.gov.ssa.nawi("2017-01-01") / p.gov.ssa.nawi("2024-01-01")
    cpi = p.gov.bls.cpi.cpi_u("2017-01-01") / p.gov.bls.cpi.cpi_u("2024-01-01")
    assert factors["employment_income_before_lsr"] == ("earnings", pytest.approx(nawi))
    for column in COLA_COLUMNS & set(factors):
        assert factors[column][0] == "cola"
    # Every input with no dedicated index falls back to CPI-U.
    cpi_columns = [c for c, (index, _) in factors.items() if index == "cpi_u"]
    assert cpi_columns
    assert all(factors[c][1] == pytest.approx(cpi) for c in cpi_columns)


def test_deflate_scales_weighted_population(system, small_dataset):
    out, _ = deflate(small_dataset, system, 2017)
    population = system.parameters.calibration.gov.census.populations.total
    ratio = population("2017-01-01") / population("2024-01-01")
    before = small_dataset.household["household_weight"].sum()
    after = out.household["household_weight"].sum()
    assert after == pytest.approx(before * ratio, rel=1e-12)


@pytest.mark.parametrize("target", [2024, 2025])
def test_deflate_refuses_later_years(system, small_dataset, target):
    with pytest.raises(ValueError):
        deflate(small_dataset, system, target)


@given(st.floats(min_value=0.05, max_value=1.0), st.integers(min_value=0, max_value=10_000))
def test_subsample_keeps_whole_households(small_dataset, fraction, seed):
    out = subsample(small_dataset, fraction, seed)
    kept = set(out.household.household_id)
    people = out.person
    assert set(people.person_household_id) <= kept
    original = small_dataset.person
    members_before = original[original.person_household_id.isin(kept)].groupby(
        "person_household_id"
    ).size()
    members_after = people.groupby("person_household_id").size()
    pd.testing.assert_series_equal(
        members_before.sort_index(), members_after.sort_index(), check_names=False
    )
    weights = small_dataset.household.set_index("household_id")["household_weight"]
    np.testing.assert_allclose(
        out.household.set_index("household_id")["household_weight"].to_numpy(),
        weights.loc[out.household.household_id].to_numpy() / fraction,
    )
    for name, id_column, person_column in [
        ("tax_unit", "tax_unit_id", "person_tax_unit_id"),
        ("spm_unit", "spm_unit_id", "person_spm_unit_id"),
        ("family", "family_id", "person_family_id"),
        ("marital_unit", "marital_unit_id", "person_marital_unit_id"),
    ]:
        assert set(tables(out)[name][id_column]) == set(people[person_column])


def test_subsample_is_deterministic(small_dataset):
    a = subsample(small_dataset, 0.5, seed=3)
    b = subsample(small_dataset, 0.5, seed=3)
    assert list(a.household.household_id) == list(b.household.household_id)


def test_subsample_full_fraction_keeps_everything(small_dataset):
    out = subsample(small_dataset, 1.0, seed=0)
    assert len(out.household) == len(small_dataset.household)
    assert len(out.person) == len(small_dataset.person)


@given(st.integers(min_value=1, max_value=8), st.integers(min_value=0, max_value=10_000))
def test_partition_covers_every_household_once(small_dataset, parts, seed):
    groups = [partition(small_dataset, parts, i, seed) for i in range(parts)]
    ids = [set(g.household.household_id) for g in groups]
    assert sum(len(i) for i in ids) == len(small_dataset.household)
    assert set().union(*ids) == set(small_dataset.household.household_id)
    assert sum(len(g.person) for g in groups) == len(small_dataset.person)
    total = sum(g.household.household_weight.sum() for g in groups)
    assert total == pytest.approx(small_dataset.household.household_weight.sum(), rel=1e-12)
    for g in groups:
        weights = small_dataset.household.set_index("household_id")["household_weight"]
        np.testing.assert_array_equal(
            g.household.household_weight.to_numpy(),
            weights.loc[g.household.household_id].to_numpy(),
        )


@given(st.integers(min_value=1, max_value=8), st.integers(min_value=0, max_value=10_000))
def test_partition_zero_matches_subsample(small_dataset, parts, seed):
    first = partition(small_dataset, parts, 0, seed)
    sample = subsample(small_dataset, 1 / parts, seed)
    assert list(first.household.household_id) == list(sample.household.household_id)
    assert list(first.person.person_id) == list(sample.person.person_id)


@pytest.mark.parametrize("index", [-1, 4])
def test_partition_rejects_out_of_range(small_dataset, index):
    with pytest.raises(ValueError):
        partition(small_dataset, 4, index)
