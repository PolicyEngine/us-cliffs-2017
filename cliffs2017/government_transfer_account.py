"""Government-transfer account; importing this module loads no model or data.

The adapter owns context authentication and the qualified health-price reform.
This module neither prepares prices nor turns declared hashes into qualification.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import ClassVar

CASH_VARIABLE = "cliffs_household_cash_near_cash_resources"
GOVERNMENT_VARIABLE = "cliffs_household_government_transfer_resources"
PTC_VARIABLE = "premium_tax_credit_in_force"

_RESERVED = frozenset(
    {
        "household_market_income",
        "household_refundable_tax_credits",
        "household_tax_before_refundable_credits",
        "household_net_income",
        "household_net_income_including_health_benefits",
        "household_benefits",
        "household_health_benefits",
        "healthcare_benefit_value",
        "household_health_costs",
        "assigned_aca_ptc",
        "aca_ptc",
        "used_aca_ptc",
        PTC_VARIABLE,
        "premium_tax_credit",
        "marketplace_net_premium",
        "selected_marketplace_plan_premium_proxy",
        "chip_premium",
        "chip_gross",
        "per_capita_chip",
        "per_capita_chip_gross",
    }
)


def _sha256(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


@dataclass(frozen=True)
class AccountSpec:
    nonhealth_benefits: tuple[str, ...]
    nonptc_government_health: tuple[str, ...]
    runtime_identity_sha256: str
    reference_preparation_sha256: str
    health_price_anchor_sha256: str
    price_basis_sha256: str
    law_year: int = 2017
    reporting_year: int = 2025
    native_per_reference_dollar: Fraction = Fraction(245120, 321943)

    def __post_init__(self):
        if type(self.law_year) is not int or self.law_year != 2017:
            raise ValueError("This commissioned account supports law year 2017")
        if type(self.reporting_year) is not int or self.reporting_year != 2025:
            raise ValueError("This account reports 2025 dollars")
        if type(
            self.native_per_reference_dollar
        ) is not Fraction or self.native_per_reference_dollar != Fraction(
            245120, 321943
        ):
            raise ValueError("Use the bound published 2017/2025 CPI ratio")
        if (
            type(self.nonhealth_benefits) is not tuple
            or type(self.nonptc_government_health) is not tuple
        ):
            raise ValueError("Account component lists must be explicit tuples")
        fields = self.nonhealth_benefits + self.nonptc_government_health
        if (
            not fields
            or any(type(name) is not str or not name for name in fields)
            or len(set(fields)) != len(fields)
            or set(fields) & _RESERVED
        ):
            raise ValueError("Declare unique primitive account components")
        for name in (
            "runtime_identity_sha256",
            "reference_preparation_sha256",
            "health_price_anchor_sha256",
            "price_basis_sha256",
        ):
            if not _sha256(getattr(self, name)):
                raise ValueError(f"Missing actual {name}")

    def ledger(self):
        return {
            "law_year": self.law_year,
            "reporting_year": self.reporting_year,
            "cash_adds": [
                "household_market_income",
                "household_refundable_tax_credits",
                *self.nonhealth_benefits,
            ],
            "cash_subtracts": [
                "household_tax_before_refundable_credits",
                PTC_VARIABLE,
            ],
            "government_adds_to_cash": [
                PTC_VARIABLE,
                *self.nonptc_government_health,
            ],
            "government_premium_deductions": [],
        }

    @property
    def component_ledger_sha256(self):
        payload = json.dumps(self.ledger(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()


def make_account_reform(spec):
    """Register account compositions in an admitted model; never run here."""
    if type(spec) is not AccountSpec:
        raise ValueError("An explicit AccountSpec is required")
    from policyengine_core.reforms import Reform
    from policyengine_us.model_api import USD, YEAR, Household, Variable

    ledger = spec.ledger()

    class cliffs_household_cash_near_cash_resources(Variable):
        value_type = float
        entity = Household
        definition_period = YEAR
        unit = USD
        label = "Cash and near-cash resources excluding health transfers"
        adds = ledger["cash_adds"]
        subtracts = ledger["cash_subtracts"]

    class cliffs_household_government_transfer_resources(Variable):
        value_type = float
        entity = Household
        definition_period = YEAR
        unit = USD
        label = "Resources including health transfers at net government cost"
        adds: ClassVar[list[str]] = [CASH_VARIABLE, *ledger["government_adds_to_cash"]]

    class CliffsAccountReform(Reform):
        def apply(self):
            self.add_variable(cliffs_household_cash_near_cash_resources)
            self.add_variable(cliffs_household_government_transfer_resources)

    return CliffsAccountReform


@dataclass(frozen=True)
class GovernmentTransferAccount:
    """Weighted managed projection, followed only by inverse deflation.

    context_for must authenticate actual adapter/price receipts for this
    simulation. Matching strings alone do not establish those receipts.
    No qualification status or existing wrapper API is invented here.
    """

    spec: AccountSpec
    context_for: object

    def __call__(self, simulation, *, period=2017, map_to="household"):
        if type(self.spec) is not AccountSpec or not callable(self.context_for):
            raise ValueError("Explicit account and authenticated context required")
        if type(period) is not int or period != self.spec.law_year:
            raise ValueError("Account period must match the native law clock")
        if map_to not in {"household", "person"}:
            raise ValueError("Use a declared household or person projection")
        actual = self.context_for(simulation)
        expected = {
            "law_year": self.spec.law_year,
            "reporting_year": self.spec.reporting_year,
            "runtime_identity_sha256": self.spec.runtime_identity_sha256,
            "reference_preparation_sha256": self.spec.reference_preparation_sha256,
            "health_price_anchor_sha256": self.spec.health_price_anchor_sha256,
            "price_basis_sha256": self.spec.price_basis_sha256,
            "component_ledger_sha256": self.spec.component_ledger_sha256,
        }
        if not isinstance(actual, Mapping) or any(
            actual.get(key) != value for key, value in expected.items()
        ):
            raise ValueError("Account/source/price identity differs from the adapter")
        result = simulation.calc(GOVERNMENT_VARIABLE, period=period, map_to=map_to)
        if type(result).__name__ != "MicroSeries" or not type(
            result
        ).__module__.startswith("microdf."):
            raise TypeError("Managed calc must return a weighted MicroSeries")
        return result / float(self.spec.native_per_reference_dollar)
