"""Leave the Commodity Supplemental Food Program out of household benefits.

PolicyEngine-US lists the benefits it counts in household net income in
``gov.household.household_benefits``. Its list adds the Commodity
Supplemental Food Program (CSFP) from 2024; a 2017 run reads the list's
earliest value, from 2022, which has no CSFP.

The model gives CSFP's food package to every person its eligibility rules
admit: aged 60 or older, with income at or below the program's limit and, in
Illinois, Kansas and Massachusetts, living in a served county. Its
``gov.usda.csfp.amount`` values one package as the program's funding divided
by its participation: $601 in 2025, from $425 million and 707,000 people.
Every eligible person in the model therefore receives a package, however
many the program's caseload serves.

``LeaveOutCSFP`` removes CSFP from every value of the list, so a 2025 run
counts the same benefits as a 2017 run. In PolicyEngine-US 2.116.0 only the
``household_benefits`` variable reads the list, and only the list reads CSFP,
so the reform changes household net income and nothing else; the tests check
that a recipient's net income falls by the package's value and that Medicaid's
value stays the same (tests/test_benefits.py).
"""

from __future__ import annotations

from policyengine_core import periods
from policyengine_core.reforms import Reform

CSFP = "commodity_supplemental_food_program"
BENEFITS = "gov.household.household_benefits"


def without_csfp(benefits) -> list[str]:
    return [benefit for benefit in benefits if benefit != CSFP]


class LeaveOutCSFP(Reform):
    def apply(self):
        node = self.parameters.gov.household.household_benefits
        # Snapshot the dated values first: each update rewrites the list from
        # its start date on, so applying them oldest first leaves every dated
        # value as it was, less CSFP.
        values = sorted(
            ((at.instant_str, list(at.value)) for at in node.values_list),
            key=lambda item: item[0],
        )
        for start, benefits in values:
            node.update(start=periods.instant(start), value=without_csfp(benefits))
