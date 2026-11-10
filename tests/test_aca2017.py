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


# Age curves (cliffs2017.aca2017, item 3 of its docstring).

AGES = [0, 5, 14, 15, 17, 20, 21, 30, 40, 63, 64, 70]
STATES = ["NC", "NJ", "DC", "MA", "MN", "UT", "AL", "NY"]
# The model's normalisation (parameters/gov/aca/age_curves/generate_age_curves.py).
MODEL_BASES = {"default": 0.765, "DC": 0.654, "MA": 0.751, "MN": 0.890, "UT": 0.793}


def curve_households(year):
    people, households, tax_units = {}, {}, {}
    for state in STATES:
        members = []
        for age in AGES:
            name = f"{state}_{age}"
            people[name] = {"age": {year: age}}
            members.append(name)
        households[state] = {"members": members, "state_code": {year: state}}
        tax_units[state] = {"members": members}
    return {"people": people, "tax_units": tax_units, "households": households}


def multipliers(year, reform=None):
    from policyengine_us import Simulation

    sim = Simulation(situation=curve_households(year), reform=reform)
    values = np.asarray(sim.calculate("slcsp_age_curve_multiplier", f"{year}-01"))
    return {
        (state, age): values[i * len(AGES) + j]
        for i, state in enumerate(STATES)
        for j, age in enumerate(AGES)
    }


@pytest.fixture(scope="module")
def curves_2017():
    return multipliers(2017, ACABefore2018), multipliers(2017)


def test_cms_2014_2017_curves_equal_the_model_except_default_children():
    # The 2014-2017 curves for DC, MA, MN and UT, and the default adult
    # ratios, equal the model's 2018 curves; only the default children differ.
    from policyengine_us import CountryTaxBenefitSystem

    from cliffs2017.aca2017 import CURVES_BEFORE_2018

    curves = CountryTaxBenefitSystem().parameters("2018-01-01").gov.aca.age_curves
    ages = np.arange(65)
    for state, base in MODEL_BASES.items():
        model = curves.default if state == "default" else curves[state.lower()]
        cms = CURVES_BEFORE_2018[state] / base
        modelled = model.calc(ages)
        compare = ages >= 21 if state == "default" else ages >= 0
        np.testing.assert_allclose(cms[compare], modelled[compare], rtol=2e-4)
    assert CURVES_BEFORE_2018["default"][0] == 0.635
    assert curves.default.calc(np.array([0, 15, 20])).tolist() == pytest.approx(
        [1.0, 0.833 / 0.765, 0.970 / 0.765], rel=2e-4
    )


def test_2017_default_children_use_the_2014_2017_ratio(curves_2017):
    reform, model = curves_2017
    for age in AGES:
        if age < 21:
            assert reform[("NC", age)] == pytest.approx(0.635 / 0.765)
            assert reform[("NC", age)] < model[("NC", age)]
        else:
            assert reform[("NC", age)] == model[("NC", age)]


def test_2017_new_jersey_uses_its_own_curve_anchored_at_40(curves_2017):
    from cliffs2017.aca2017 import CURVES_BEFORE_2018

    reform, model = curves_2017
    nj = CURVES_BEFORE_2018["NJ"]
    assert reform[("NJ", 40)] == pytest.approx(model[("NJ", 40)])
    for age in AGES:
        expected = nj[min(age, 64)] / nj[40] * model[("NJ", 40)]
        assert reform[("NJ", age)] == pytest.approx(expected)


def test_2017_other_state_curves_unchanged(curves_2017):
    reform, model = curves_2017
    for state in ["DC", "MA", "MN", "UT", "AL", "NY"]:
        for age in AGES:
            assert reform[(state, age)] == model[(state, age)]


@pytest.mark.parametrize("year", [2018, 2024])
def test_age_curves_match_model_from_2018(year):
    assert multipliers(year, ACABefore2018) == multipliers(year)
