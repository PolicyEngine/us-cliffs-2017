"""Model the ACA premium tax credit before 2018 (an analysis reform, not current law code).

PolicyEngine-US returns a $0 premium tax credit before 2018
(``aca_ptc`` and ``aca_ptc_before_filing_gate`` have a ``formula`` returning 0
and a ``formula_2018``), because its rating-area benchmark premium data starts
in 2018. This reform applies the model's 2018 formula to earlier years too,
with two adjustments so the credit reflects the earlier year's law and prices:

1. Benchmark premiums: the model copies its 2018 rating-area premiums back to
   earlier years. ``slcsp_age_0`` (which feeds both the age-curve and
   family-tier premiums) is scaled by
   gov.aca.benchmark_premium_uprating(year) / gov.aca.benchmark_premium_uprating(2018),
   the same index the model uses to carry those premiums forward
   (2017: 359, 2018: 481).
2. Applicable percentages: the model's earliest table (dated 2015) holds the
   statute's original 2014 percentages. For 2017 this sets the table in
   Rev. Proc. 2016-24, section 4.01: 2.04% below 133% of the poverty line,
   3.06-4.08%, 4.08-6.43%, 6.43-8.21%, 8.21-9.69% and 9.69% at 300-400%.
3. Age curves: the model holds each age curve with one value, dated 2018,
   which it also uses for earlier years. From 2014 to 2017 the federal default
   curve rated everyone aged 0 to 20 at 0.635 of the age-21 premium; from 2018
   it rates ages 0-14 at 0.765 and ages 15-20 at 0.833 to 0.970. Before 2018
   ``slcsp_age_curve_multiplier`` uses the 2014-2017 curves in CMS's "State
   Specific Age Curve Variations" of August 9, 2013
   (data/cms_age_curves_2014_2017.csv): 0.635 for children on the default
   curve, and New Jersey's own curve, which the model's 2018 list drops. New
   Jersey's curve is anchored at age 40, the age the benchmark premium index
   tracks (KFF's average benchmark premium for a 40-year-old). CMS's 2014-2017
   curves for DC, Massachusetts, Minnesota and Utah equal the model's 2018 ones,
   and Alabama, Mississippi and Oregon used the default curve, so those states
   keep the model's curves. New York and Vermont rate by family tier.
   Medicaid's cost index reads the same multiplier, so this also changes how
   the model spreads each state's Medicaid spending in 2017.

The 400%-of-poverty eligibility limit needs no change: the model's
``gov.aca.ptc_income_eligibility`` already ends eligibility above 400% before
2021. (The model truncates income to whole percentage points of poverty, so it
also denies the credit at exactly 400.00%, which the IRS's 2017 Form 8962
worksheet allows; no survey record lands exactly there.)
"""

import csv
from pathlib import Path

from policyengine_core import periods
from policyengine_core.reforms import Reform

from policyengine_us.model_api import *

FIRST_PREMIUM_DATA_YEAR = 2018

CURVES_BEFORE_2018_FILE = Path(__file__).parent / "data" / "cms_age_curves_2014_2017.csv"
# The model's default curve divides CMS's ratios by the 2018 ratio for ages 0-14.
DEFAULT_CURVE_BASE_2018 = 0.765
# States with their own curve in PolicyEngine-US 2.116.0's slcsp_age_curve_multiplier.
MODEL_STATE_CURVES = ("AL", "DC", "MA", "MN", "MS", "NY", "OR", "UT", "VT")
FIRST_ADULT_AGE = 21
ANCHOR_AGE = 40


def load_curves_before_2018(path=CURVES_BEFORE_2018_FILE) -> dict[str, np.ndarray]:
    """CMS's 2014-2017 premium ratios, indexed by age 0 to 64 (64 = 64 and older)."""
    with open(path) as f:
        rows = list(csv.DictReader(line for line in f if not line.startswith("#")))
    curves = {}
    for state in rows[0]:
        if state == "age":
            continue
        child = float(rows[0][state])
        adults = [float(row[state]) for row in rows[1:]]
        curves[state] = np.array([child] * FIRST_ADULT_AGE + adults)
    assert all(len(curve) == 65 for curve in curves.values())
    return curves


CURVES_BEFORE_2018 = load_curves_before_2018()


def ratio_at(curve: np.ndarray, age) -> np.ndarray:
    return curve[np.clip(np.floor(age).astype(int), 0, len(curve) - 1)]

# Rev. Proc. 2016-24, section 4.01 (taxable years beginning in 2017).
APPLICABLE_PERCENTAGES = {
    2017: dict(
        initial=[0.0204, 0.0306, 0.0408, 0.0643, 0.0821, 0.0969],
        final=[0.0204, 0.0408, 0.0643, 0.0821, 0.0969, 0.0969],
    ),
}


class aca_ptc_before_filing_gate(Variable):
    value_type = float
    entity = TaxUnit
    label = "ACA premium tax credit before the filing condition"
    unit = USD
    definition_period = YEAR
    defined_for = "is_aca_ptc_eligible"

    def formula(tax_unit, period, parameters):
        plan_cost = tax_unit("slcsp", period)
        income = tax_unit("aca_magi", period)
        applicable_figure = tax_unit("aca_required_contribution_percentage", period)
        return max_(0, plan_cost - income * applicable_figure)


class aca_ptc(Variable):
    value_type = float
    entity = TaxUnit
    label = "ACA premium tax credit for tax unit"
    unit = USD
    definition_period = YEAR
    defined_for = "is_aca_ptc_eligible"

    def formula(tax_unit, period, parameters):
        credit = tax_unit("aca_ptc_before_filing_gate", period)
        files = tax_unit("files_return_for_aca_ptc", period)
        return credit * files


class slcsp_age_0(Variable):
    value_type = float
    entity = Household
    label = "Second-lowest ACA silver-plan for a person aged 0"
    unit = USD
    definition_period = MONTH

    def formula(household, period, parameters):
        state_code = household("state_code", period)
        rating_area = household("slcsp_rating_area", period)
        p = parameters(period).gov.aca
        known = rating_area > 0
        safe_rating_area = where(known, rating_area, 1)
        cost = p.state_rating_area_cost[state_code][safe_rating_area]
        if period.start.year < FIRST_PREMIUM_DATA_YEAR:
            index = parameters.gov.aca.benchmark_premium_uprating
            cost = cost * index(period.start) / index(f"{FIRST_PREMIUM_DATA_YEAR}-01-01")
        return where(known, cost, 0)


class slcsp_age_curve_multiplier(Variable):
    value_type = float
    entity = Person
    label = "ACA SLCSP age curve multiplier"
    unit = "/1"
    definition_period = MONTH

    def formula(person, period, parameters):
        state_code = person.household("state_code_str", period)
        age = person("monthly_age", period)
        p = parameters(period).gov.aca.age_curves
        # PolicyEngine-US 2.116.0's formula, unchanged.
        model = select(
            [state_code == state for state in MODEL_STATE_CURVES],
            [
                p.al.calc(age),
                p.dc.calc(age),
                p.ma.calc(age),
                p.mn.calc(age),
                p.ms.calc(age),
                p.ny.calc(age),
                p["or"].calc(age),
                p.ut.calc(age),
                p.vt,
            ],
            default=p.default.calc(age),
        )
        if period.start.year >= FIRST_PREMIUM_DATA_YEAR:
            return model
        curves = CURVES_BEFORE_2018
        child = age < FIRST_ADULT_AGE
        # Adults keep the model's values, which equal CMS's 2014-2017 ratios.
        default = where(child, curves["default"][0] / DEFAULT_CURVE_BASE_2018, p.default.calc(age))
        anchor = p.default.calc(np.full_like(age, ANCHOR_AGE))
        new_jersey = ratio_at(curves["NJ"], age) / curves["NJ"][ANCHOR_AGE] * anchor
        on_model_curve = np.isin(state_code, MODEL_STATE_CURVES)
        return where(on_model_curve, model, where(state_code == "NJ", new_jersey, default))


class ACABefore2018(Reform):
    def apply(self):
        for variable in (
            aca_ptc_before_filing_gate,
            aca_ptc,
            slcsp_age_0,
            slcsp_age_curve_multiplier,
        ):
            self.update_variable(variable)
        node = self.parameters.gov.aca.required_contribution_percentage
        for year, table in APPLICABLE_PERCENTAGES.items():
            span = periods.period(f"year:{year}-01-01:1")
            node.initial.update(period=span, value=table["initial"])
            node.final.update(period=span, value=table["final"])
