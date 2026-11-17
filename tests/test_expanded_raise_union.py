"""Behavioral checks for saved-result classification and household disjointness."""

import numpy as np
import pandas as pd
import pytest

from scripts.expanded_raise_union import (
    CHANGES,
    add_variable,
    flag_counts,
    household_combination,
    household_counts,
    retention_flags,
    set_person_flag,
    summarize_part,
    validate_rows,
    validate_same_universe,
)


def test_retention_boundaries_are_strict_and_exclude_nonworkers():
    """At exactly half retained the <half test fails; zero is not a strict loss."""
    change = [1000] * 6
    net = [600, 500, 200, 0, -1, -1]
    workers = [True, True, True, True, True, False]
    assert retention_flags(change, net, 0.5, workers).tolist() == [
        False,
        False,
        True,
        True,
        True,
        False,
    ]
    assert retention_flags(change, net, 0, workers).tolist() == [
        False,
        False,
        False,
        False,
        True,
        False,
    ]


@pytest.mark.parametrize(
    "change,net", [([0], [0]), ([-1], [1]), ([1], [np.nan]), ([np.inf], [0])]
)
def test_invalid_saved_changes_fail(change, net):
    with pytest.raises(ValueError):
        retention_flags(change, net, 0.5)


def rows():
    return pd.DataFrame(
        {
            "person_index": [0, 2],
            "person_id": [101, 103],
            "household_id": [1, 2],
            "rank": [1, 1],
            "change": [1000.0, 1000.0],
            "worker": [True, False],
            "d_net_single_ptc": [-100.0, 400.0],
            "d_net_without_health": [800.0, 400.0],
        }
    )


def population():
    return pd.DataFrame(
        {"person_id": [101, 102, 103], "person_household_id": [1, 1, 2]}
    )


def test_identity_guard_rejects_wrong_person_and_household_mapping():
    validate_rows(rows(), population(), 1000)
    for column, values in (
        ("person_id", [102, 103]),
        ("household_id", [2, 2]),
        ("person_index", [0, 0]),
    ):
        changed = rows()
        changed[column] = values
        with pytest.raises(ValueError):
            validate_rows(changed, population(), 1000)


def test_universe_guard_rejects_changed_worker_selection():
    a, b = rows(), rows()
    b.loc[0, "worker"] = False
    with pytest.raises(ValueError, match="population or worker selection"):
        validate_same_universe({"raise_1000": a, "raise_2000": b})


def tiny_microsimulation():
    """A real core MicroSeries simulation with two households and no tax formulas."""
    from policyengine_core.entities import build_entity
    from policyengine_core.periods import YEAR
    from policyengine_core.simulations.microsimulation import Microsimulation
    from policyengine_core.taxbenefitsystems import TaxBenefitSystem
    from policyengine_core.variables import Variable

    person = build_entity(key="person", plural="people", label="Person", is_person=True)
    household = build_entity(
        key="household",
        plural="households",
        label="Household",
        roles=[{"key": "member", "plural": "members", "label": "Member"}],
    )
    system = TaxBenefitSystem([person, household])
    system.add_variable(
        type(
            "household_weight",
            (Variable,),
            {
                "value_type": float,
                "entity": household,
                "definition_period": YEAR,
                "label": "Synthetic household calibration input",
            },
        )
    )
    return Microsimulation(
        tax_benefit_system=system,
        situation={
            "people": {"a": {}, "b": {}, "c": {}},
            "households": {
                "h1": {"members": ["a", "b"], "household_weight": {2017: 100}},
                "h2": {"members": ["c"], "household_weight": {2017: 200}},
            },
        },
    )


def test_household_union_counts_members_once_and_additional_group_is_disjoint():
    """Two qualifying adults in one household must not duplicate its residents."""
    sim = tiny_microsimulation()
    union_hh = set_person_flag(sim, "union_person", np.array([True, True, True]), 2017)
    strict_hh = set_person_flag(
        sim, "strict_person", np.array([True, False, False]), 2017
    )
    add_variable(
        sim,
        "additional_household",
        "household",
        household_combination(union_hh, strict_hh, "left_only"),
    )
    assert flag_counts(sim, "union_person", union_hh, 2017) == {
        "adults": 400,
        "households": 300,
        "household_members": 400,
    }
    assert household_counts(sim, strict_hh, 2017) == {
        "households": 100,
        "household_members": 200,
    }
    assert household_counts(sim, "additional_household", 2017, "union_person") == {
        "adults": 200,
        "households": 200,
        "household_members": 200,
    }
    # Person b is below half but lives with person a, who faces a strict cliff.
    # It therefore contributes no residents to the additional household group.


def test_finite_grid_union_handles_non_nested_size_flags():
    """A person flagged by a smaller raise can fail the larger-raise test."""
    a = retention_flags([1000, 1000], [-500, 800], 0)
    b = retention_flags([5000, 5000], [3500, -2000], 0)
    assert a.tolist() == [True, False]
    assert b.tolist() == [False, True]
    assert (a | b).tolist() == [True, True]


@pytest.mark.parametrize(
    "wrong_workers,expected_error",
    [([False, False], "workers_reached"), ([False, True], "workers_on_cliff")],
)
def test_consistently_wrong_worker_flags_fail_saved_worker_checks(
    wrong_workers, expected_error
):
    """An identical wrong mask across every size must fail metadata checks.

    Both tested adults share a household, so swapping which one is a worker
    preserves the worker population and every unrestricted cliff total.
    Only the worker-specific strict-cliff check detects the second mutation.
    """
    frames, records = {}, {}
    for key, amount in CHANGES.items():
        frames[key] = pd.DataFrame(
            {
                "person_index": [0, 1],
                "person_id": [101, 102],
                "household_id": [1, 1],
                "rank": [1, 2],
                "change": [amount, amount],
                "worker": wrong_workers,
                "d_net_single_ptc": [-100.0, 400.0],
                "d_net_without_health": [800.0, 400.0],
            }
        )
        records[key] = {
            "change": {
                "workers_reached": 100.0,
                "with_health": {
                    "people_on_cliff": 100.0,
                    "workers_on_cliff": 100.0,
                    "households_with_person_on_cliff": 100.0,
                    "people_in_those_households": 200.0,
                },
                "without_health": {
                    "people_on_cliff": 0.0,
                    "workers_on_cliff": 0.0,
                    "households_with_person_on_cliff": 0.0,
                    "people_in_those_households": 0.0,
                },
            }
        }
    # All three masks agree, so this older guard alone accepts the mutation.
    validate_same_universe(frames)
    with pytest.raises(ValueError, match=expected_error):
        summarize_part(tiny_microsimulation(), population(), frames, records, 2017)
