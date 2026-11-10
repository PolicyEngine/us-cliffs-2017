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

The 400%-of-poverty eligibility limit needs no change: the model's
``gov.aca.ptc_income_eligibility`` already ends eligibility above 400% before
2021.
"""

from policyengine_core import periods
from policyengine_core.reforms import Reform

from policyengine_us.model_api import *

FIRST_PREMIUM_DATA_YEAR = 2018

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


class ACABefore2018(Reform):
    def apply(self):
        for variable in (aca_ptc_before_filing_gate, aca_ptc, slcsp_age_0):
            self.update_variable(variable)
        node = self.parameters.gov.aca.required_contribution_percentage
        for year, table in APPLICABLE_PERCENTAGES.items():
            span = periods.period(f"year:{year}-01-01:1")
            node.initial.update(period=span, value=table["initial"])
            node.final.update(period=span, value=table["final"])
