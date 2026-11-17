"""Constant-price input convention, not 2017 premium observations.

Freeze model reference-2025 base premiums in their existing age-zero
normalization. Keep the native law's age curves, family tiers, enrollment,
coverage-family allocation and credit rules. No data or model imports occur
until the admitted reform factory is called.
"""

from fractions import Fraction

# These derived inputs could shadow the admitted formula replacements. The
# packet/input-contract witness must reject them rather than trust the reform.
FORBIDDEN_STORED_PRICE_INPUTS = frozenset(
    {
        "slcsp_age_0",
        "lcbp_age_0",
        "slcsp",
        "aca_ptc_slcsp",
        "lcbp",
        "selected_marketplace_plan_premium_proxy",
        "monthly_selected_marketplace_plan_premium_proxy",
        "aca_ptc_coverage_family_premium",
        "used_aca_ptc",
        "assigned_aca_ptc",
        "premium_tax_credit_in_force",
    }
)


def make_reference_benchmark_reform(*, law_year=2017, reference_year=2025):
    if type(law_year) is not int or law_year != 2017:
        raise ValueError("This proposed price convention covers law year 2017")
    if type(reference_year) is not int or reference_year != 2025:
        raise ValueError("Use the declared reference-2025 price inputs")

    from policyengine_core.reforms import Reform
    from policyengine_us.model_api import MONTH, USD, Household, Variable, where

    factor = float(Fraction(245120, 321943))

    def base_premium(household, period, parameters, *, bronze):
        if period.start.year != law_year:
            raise ValueError("Price override read outside its declared law year")
        state = household("state_code", period)
        area = household("slcsp_rating_area", period)
        known = area > 0
        safe_area = where(known, area, 1)
        reference = parameters(f"{reference_year}-01-01").gov.aca
        costs = (
            reference.lcbp.state_rating_area_cost
            if bronze
            else reference.state_rating_area_cost
        )
        # Unknown geography retains the model's zero and must be counted as
        # a coverage/price limitation in qualification, not a true zero price.
        return where(known, costs[state][safe_area] * factor, 0)

    class slcsp_age_0(Variable):
        value_type = float
        entity = Household
        definition_period = MONTH
        unit = USD
        label = "Reference-2025 silver base premium in native currency"

        def formula(household, period, parameters):
            return base_premium(household, period, parameters, bronze=False)

    class lcbp_age_0(Variable):
        value_type = float
        entity = Household
        definition_period = MONTH
        unit = USD
        label = "Reference-2025 bronze base premium in native currency"

        def formula(household, period, parameters):
            return base_premium(household, period, parameters, bronze=True)

    class ReferenceBenchmarkPrices(Reform):
        def apply(self):
            self.replace_variable(slcsp_age_0)
            self.replace_variable(lcbp_age_0)

    return ReferenceBenchmarkPrices
