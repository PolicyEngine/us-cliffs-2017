"""Controls for real household curves and the reporting/refinement machinery."""

from copy import deepcopy

import numpy as np
import pytest

from scripts.paper_household_curves import (
    CASES,
    accounting_checks,
    at_index,
    cap_threads,
    compare,
    compute,
    refine_integer_transition,
    situation,
    transition_record,
    write_summary,
)


def test_thread_caps_preserve_lower_and_unusual_settings():
    env = {"OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "8", "OPENBLAS_NUM_THREADS": "unusual"}
    limits = cap_threads(env)
    assert limits["OMP_NUM_THREADS"] == "1"
    assert limits["MKL_NUM_THREADS"] == "2"
    assert limits["OPENBLAS_NUM_THREADS"] == "unusual"
    assert limits["NUMEXPR_NUM_THREADS"] == "2"


def test_axes_change_only_adult_earnings_and_keep_roles():
    case = CASES["parent_2025"]
    scalar = situation(case, 0)
    axis = situation(case, 0, axis=(0, 90_000, 901))
    assert axis.pop("axes")[0][0]["index"] == 0
    assert axis == scalar
    assert scalar["people"]["adult"]["is_tax_unit_head"][2025]
    for child in ("child1", "child2"):
        assert scalar["people"][child]["is_tax_unit_dependent"][2025]
        assert not scalar["people"][child]["is_tax_unit_spouse"][2025]
        assert scalar["marital_units"][child]["members"] == [child]
    assert "aca_magi" not in str(scalar)
    assert "medicaid_income" not in str(scalar)


def fake_point(earnings, threshold=100):
    credit = 2000.0 if earnings < threshold else 0.0
    return {
        "earnings": np.array([float(earnings)]),
        "resources_full_health": np.array([earnings + credit + 0.001]),
        "resources_cash": np.array([float(earnings)]),
        "native_rounding_residual": np.array([0.001]),
        "signed_components": {"household_market_income": np.array([float(earnings)]),
                              "assigned_aca_ptc": np.array([credit]),
                              "marketplace_net_premium": np.array([credit - 5000]),
                              "free_school_meals": np.array([0.0]),
                              "reduced_price_school_meals": np.array([0.0])},
        "people": {"medicaid_enrolled": np.array([[False]]), "chip_enrolled": np.array([[False]])},
        "tax_unit": {"aca_ptc": np.array([credit])},
    }


@pytest.mark.parametrize("threshold", [1, 27, 50, 99, 100])
def test_integer_refinement_locates_transition_without_interpolation(threshold):
    calls = []

    def point(x):
        calls.append(x)
        return fake_point(x, threshold)

    assert refine_integer_transition(0, 100, point) == [threshold - 1, threshold]
    assert all(isinstance(x, int) for x in calls)
    assert threshold in calls
    assert threshold - 1 in calls


def test_refinement_reports_no_changed_status():
    assert refine_integer_transition(0, 50, lambda x: fake_point(x, 100)) is None


def test_transition_removes_premium_once_and_retains_residual():
    out = transition_record(fake_point(99), fake_point(100))
    assert out["earnings_change"] == 1
    assert out["full_resource_change"] == pytest.approx(-1999)
    assert "marketplace_net_premium" not in out["signed_component_changes"]
    assert out["signed_component_changes"]["assigned_aca_ptc"] == -2000
    assert out["before"]["earnings"] == 99
    assert out["after"]["earnings"] == 100


def test_comparison_rejects_wrong_point_and_shape():
    original = fake_point(99)
    assert compare(original, deepcopy(original), atol=0) == 0
    with pytest.raises(AssertionError, match="Mismatch"):
        compare(original, fake_point(100))
    changed = deepcopy(original)
    changed["earnings"] = np.array([[99.0]])
    with pytest.raises(AssertionError, match="shapes"):
        compare(original, changed)


def test_summary_accepts_no_coverage_status_boundary(tmp_path):
    record = transition_record(fake_point(99), fake_point(100))
    event = dict(sampled_bracket=[99, 100], integer_dollar_status_transition=None,
                 raise_comparisons={"1000": record, "5000": record},
                 sampled_recovery_earnings_bracket=None)
    result = {"cases": {"example": dict(label="Example", specification={"low": 0, "high": 100}, annotations=[event])}}
    out = tmp_path / "summary.md"
    write_summary(result, out)
    assert "No changed coverage/meal status" in out.read_text()


@pytest.mark.parametrize("name,low,high", [("aca_2017", 47_500, 47_600), ("parent_2025", 36_700, 36_800), ("single_2025", 21_600, 21_700)])
def test_actual_axis_matches_fresh_household_and_fixed_medicaid(name, low, high):
    case = CASES[name]
    curve = compute(case, axis=(low, high, 3))
    checks = accounting_checks(curve, case)
    assert checks["once_only_ptc_identity"]
    assert checks["fixed_national_medicaid_values"]
    scalar = compute(case, (low + high) / 2)
    assert compare(at_index(curve, 1), scalar) <= 0.01
    assert compare(scalar, compute(case, (low + high) / 2), atol=0) == 0
    assert curve["resources_full_health"][2] < curve["resources_full_health"][0]
