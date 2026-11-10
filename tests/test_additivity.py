"""Households interact in the model only through Medicaid's two state totals.

METHODOLOGY.md and cliffs2017/combine.py rest on this: with those totals fixed
at their full-sample values, a household's marginal tax rate, net income and
cliff flag don't depend on which other households share its run, so the four
parts add up to a single full-sample run. These tests split a Microcosm
subsample in two and check every person's values against the unsplit run, for
each configuration the runs use.
"""

import numpy as np
import pandas as pd
import pytest

from cliffs2017.deflate import deflate, partition
from cliffs2017.medicaid import simulation_sums, totals_from_sums
from cliffs2017.simulation import build_simulation

CONFIGURATIONS = [(2017, False), (2017, True), (2025, False), (2025, True)]


def prepare(dataset, system, year):
    if year < int(dataset.time_period):
        return deflate(dataset, system, year)[0]
    return dataset


def person_values(dataset, year, options):
    sim = build_simulation(dataset, year, **options)
    return pd.DataFrame(
        {
            "marginal_tax_rate": np.asarray(sim.calculate("marginal_tax_rate", year)),
            "household_net_income": np.asarray(
                sim.calculate("household_net_income", year, map_to="person")
            ),
            "is_on_cliff": np.asarray(sim.calculate("is_on_cliff", year)).astype(bool),
        },
        index=np.asarray(sim.calculate("person_id", year)),
    )


@pytest.fixture(scope="module", params=CONFIGURATIONS, ids=lambda c: f"{c[0]}-{'health' if c[1] else 'plain'}")
def runs(request, system, small_dataset):
    year, health = request.param
    options = dict(health=health, aca_before_2018=year < 2018, leave_out_csfp=year >= 2024)
    whole_data = prepare(small_dataset, system, year)
    if health:
        stock = build_simulation(whole_data, year, **options)
        options["medicaid_totals"] = totals_from_sums(simulation_sums(stock, year))
    whole = person_values(whole_data, year, options)
    parts = [
        person_values(prepare(partition(small_dataset, 2, k, seed=3), system, year), year, options)
        for k in range(2)
    ]
    return whole, parts


def test_parts_cover_every_person_once(runs):
    whole, parts = runs
    ids = np.concatenate([part.index.to_numpy() for part in parts])
    assert len(ids) == len(set(ids)) == len(whole)
    assert set(ids) == set(whole.index)


def test_parts_reproduce_the_whole(runs):
    whole, parts = runs
    joined = pd.concat(parts).loc[whole.index]
    np.testing.assert_array_equal(joined["is_on_cliff"], whole["is_on_cliff"])
    for column in ("marginal_tax_rate", "household_net_income"):
        np.testing.assert_allclose(joined[column], whole[column], rtol=0, atol=1e-4)
    # The small sample may hold no cliff in a configuration, so check instead
    # that the rates compared vary from adult to adult.
    assert whole["marginal_tax_rate"].nunique() > 50
