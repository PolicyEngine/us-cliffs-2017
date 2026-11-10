"""Invariants of the premium tax credit before 2018 (cliffs2017.aca2017).

1. From 2018 on, the reform matches PolicyEngine-US's own premium tax
   credit exactly (differential test), so it changes only earlier years.
2. In 2017 the credit equals the benchmark premium less the required
   contribution, with Rev. Proc. 2016-24's applicable percentages.
3. 2017 benchmark premiums equal 2018's scaled by the model's benchmark
   premium index (359 / 481).
4. For a single adult, the 2017 credit never rises with income, and it ends
   above 400% of the prior year's poverty line.
"""

import numpy as np
import pytest

from cliffs2017.aca2017 import APPLICABLE_PERCENTAGES, ACABefore2018

AXIS_POINTS = 61


def single_adult(year, state="NC", county="WAKE_COUNTY_NC", low=10_000, high=70_000):
    return {
        "people": {"adult": {"age": {year: 60}, "has_esi": {year: False}}},
        "tax_units": {"tu": {"members": ["adult"]}},
        "spm_units": {"spm": {"members": ["adult"]}},
        "households": {
            "h": {
                "members": ["adult"],
                "state_code": {year: state},
                "county_str": {year: county},
            }
        },
        "axes": [
            [
                {
                    "name": "employment_income",
                    "count": AXIS_POINTS,
                    "min": low,
                    "max": high,
                    "period": year,
                }
            ]
        ],
    }


_SIMULATIONS = {}


def calc(year, variable, reform=None):
    """Calculate on one shared simulation per (year, reform)."""
    from policyengine_us import Simulation

    key = (year, reform)
    if key not in _SIMULATIONS:
        _SIMULATIONS[key] = Simulation(situation=single_adult(year), reform=reform)
    return np.asarray(_SIMULATIONS[key].calculate(variable, year))


@pytest.fixture(scope="module")
def ptc_2017():
    return dict(
        income=calc(2017, "employment_income", ACABefore2018),
        ptc=calc(2017, "aca_ptc_before_filing_gate", ACABefore2018),
        magi_fraction=calc(2017, "aca_magi_fraction", ACABefore2018),
        slcsp=calc(2017, "slcsp", ACABefore2018),
        magi=calc(2017, "aca_magi", ACABefore2018),
        percentage=calc(2017, "aca_required_contribution_percentage", ACABefore2018),
        eligible=calc(2017, "is_aca_ptc_eligible", ACABefore2018).astype(bool),
    )


@pytest.mark.parametrize("year", [2018, 2021, 2024])
@pytest.mark.parametrize(
    "variable", ["aca_ptc_before_filing_gate", "aca_ptc", "slcsp", "is_aca_ptc_eligible"]
)
def test_reform_matches_model_from_2018(year, variable):
    np.testing.assert_array_equal(calc(year, variable, ACABefore2018), calc(year, variable))


def test_model_alone_pays_no_credit_in_2017():
    assert calc(2017, "aca_ptc_before_filing_gate").max() == 0


def test_2017_credit_formula(ptc_2017):
    expected = np.where(
        ptc_2017["eligible"],
        np.maximum(0, ptc_2017["slcsp"] - ptc_2017["magi"] * ptc_2017["percentage"]),
        0,
    )
    np.testing.assert_allclose(ptc_2017["ptc"], expected, rtol=1e-6)
    assert ptc_2017["ptc"].max() > 0


def test_2017_benchmark_premium_scaling():
    from policyengine_us import CountryTaxBenefitSystem

    index = CountryTaxBenefitSystem().parameters.gov.aca.benchmark_premium_uprating
    ratio = index("2017-01-01") / index("2018-01-01")
    premium_2017 = calc(2017, "slcsp", ACABefore2018)
    premium_2018 = calc(2018, "slcsp", ACABefore2018)
    # The model counts the benchmark premium only for members eligible for
    # the credit. Eligibility differs between the years near the poverty
    # line (2017 coverage uses the 2016 guidelines, 2018 the 2017 ones), so
    # compare incomes at which the adult qualifies in both years.
    both = (premium_2017 > 0) & (premium_2018 > 0)
    assert both.sum() >= AXIS_POINTS // 2
    np.testing.assert_allclose(premium_2017[both], premium_2018[both] * ratio, rtol=1e-6)
    assert ratio == pytest.approx(359 / 481)


@pytest.mark.parametrize(
    "fraction, expected",
    [
        # Rev. Proc. 2016-24, section 4.01: flat 2.04% below 133%, then linear
        # within each band.
        (1.00, 0.0204),
        (1.33, 0.0306),
        (1.40, 0.0306 + (0.0408 - 0.0306) * (0.07 / 0.17)),
        (1.50, 0.0408),
        (2.00, 0.0643),
        (2.50, 0.0821),
        (3.00, 0.0969),
        (3.50, 0.0969),
        (4.00, 0.0969),
    ],
)
def test_2017_applicable_percentages(fraction, expected):
    from policyengine_core.periods import instant
    from policyengine_us import CountryTaxBenefitSystem

    system = ACABefore2018(CountryTaxBenefitSystem())
    p = system.parameters.gov.aca.required_contribution_percentage
    at = instant("2017-01-01")
    thresholds = np.array(p.threshold(at))
    initial, final = np.array(p.initial(at)), np.array(p.final(at))
    i = min(np.searchsorted(thresholds, fraction, side="right") - 1, len(initial) - 1)
    width = thresholds[min(i + 1, len(thresholds) - 1)] - thresholds[i]
    position = 0 if i == len(initial) - 1 else (fraction - thresholds[i]) / width
    assert initial[i] + position * (final[i] - initial[i]) == pytest.approx(expected)
    table = APPLICABLE_PERCENTAGES[2017]
    np.testing.assert_allclose(initial, table["initial"])
    np.testing.assert_allclose(final, table["final"])


def test_2017_credit_never_rises_with_income(ptc_2017):
    order = np.argsort(ptc_2017["income"])
    eligible = ptc_2017["eligible"][order]
    credit = ptc_2017["ptc"][order]
    # Compare consecutive incomes at which the adult qualifies.
    steps = np.diff(credit[eligible])
    assert np.all(steps <= 1e-6)


def test_2017_credit_ends_above_400_percent(ptc_2017):
    above = ptc_2017["magi_fraction"] > 4
    assert above.any()
    assert np.all(ptc_2017["ptc"][above] == 0)
    just_below = (ptc_2017["magi_fraction"] > 3.6) & (ptc_2017["magi_fraction"] <= 4)
    assert np.all(ptc_2017["ptc"][just_below] > 0)
