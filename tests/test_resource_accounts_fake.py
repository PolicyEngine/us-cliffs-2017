"""FAKE-ONLY algebra and API-contract tests, never policy or population goldens."""

import hashlib
import json
import sys
from dataclasses import replace
from fractions import Fraction
from types import ModuleType, SimpleNamespace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from cliffs2017 import government_transfer_account as account
from cliffs2017 import reference_benchmark_prices as prices

D = Fraction(245120, 321943)


class Vector(tuple):
    """Tiny explicit-shape FAKE vector; no numpy or implicit vector broadcast."""

    def paired(self, other, operation):
        if isinstance(other, Vector):
            if len(self) != len(other):
                raise ValueError("FAKE_ONLY_SHAPE_MISMATCH")
            return Vector(operation(a, b) for a, b in zip(self, other))
        if not isinstance(other, (int, float, Fraction)):
            raise TypeError("FAKE_ONLY_UNDECLARED_SCALAR")
        return Vector(operation(a, other) for a in self)

    def __add__(self, other):
        return self.paired(other, lambda a, b: a + b)

    def __sub__(self, other):
        return self.paired(other, lambda a, b: a - b)

    def __mul__(self, other):
        return self.paired(other, lambda a, b: a * b)

    def __gt__(self, other):
        return self.paired(other, lambda a, b: a > b)


def fake_where(mask, yes, no):
    if not isinstance(mask, Vector):
        raise TypeError("FAKE_ONLY_MASK_REQUIRED")
    for value in (yes, no):
        if isinstance(value, Vector) and len(value) != len(mask):
            raise ValueError("FAKE_ONLY_SHAPE_MISMATCH")
    return Vector(
        (yes[i] if isinstance(yes, Vector) else yes)
        if truth
        else (no[i] if isinstance(no, Vector) else no)
        for i, truth in enumerate(mask)
    )


class FakeReform:
    def __init__(self):
        self.variables = {}

    def add_variable(self, variable):
        if variable.__name__ in self.variables:
            raise ValueError("FAKE_ONLY_DUPLICATE_VARIABLE")
        self.variables[variable.__name__] = variable

    def replace_variable(self, variable):
        self.variables[variable.__name__] = variable


def install_fake_engine_api(monkeypatch):
    """Only these empty, tagged modules satisfy delayed candidate imports."""
    names = (
        "policyengine_core",
        "policyengine_core.reforms",
        "policyengine_us",
        "policyengine_us.model_api",
    )
    modules = {name: ModuleType(name) for name in names}
    for name, module in modules.items():
        assert name not in sys.modules, "A real scientific module must never be loaded"
        module.__FAKE_ONLY__ = True
        module.__path__ = []
        monkeypatch.setitem(sys.modules, name, module)
    modules["policyengine_core.reforms"].Reform = FakeReform
    api = modules["policyengine_us.model_api"]
    api.Variable = type("FAKE_ONLY_Variable", (), {})
    api.Household = object()
    api.MONTH, api.YEAR, api.USD = "FAKE_MONTH", "FAKE_YEAR", "FAKE_USD"
    api.where = fake_where


@pytest.fixture
def fake_engine_api(monkeypatch):
    install_fake_engine_api(monkeypatch)


class MicroSeries:
    """Deliberately tagged fake for testing the callable's projection protocol."""

    __module__ = "microdf.fake_contract"
    __FAKE_ONLY__ = True

    def __init__(self, values, weights):
        self.values = tuple(values)
        self.weights = tuple(weights)

    def __truediv__(self, divisor):
        return MicroSeries((value / divisor for value in self.values), self.weights)


def anchor_hash(values):
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def account_spec(anchor):
    return account.AccountSpec(
        nonhealth_benefits=("FAKE_NONHEALTH",),
        nonptc_government_health=("FAKE_MEDICAID_NET", "FAKE_CHIP_NET"),
        runtime_identity_sha256="a" * 64,
        reference_preparation_sha256="b" * 64,
        health_price_anchor_sha256=anchor_hash(anchor),
        price_basis_sha256="c" * 64,
    )


class FakeSimulation:
    """Evaluate only the candidate's adds/subtracts graph on invented values."""

    def __init__(self, spec, variables, *, ptc=7, chip=11, ordinary_credit=3):
        self.spec, self.variables = spec, variables
        self.inputs = {
            "household_market_income": Vector((100, 200)),
            "FAKE_NONHEALTH": Vector((13, 17)),
            "household_refundable_tax_credits": Vector((ordinary_credit + ptc,) * 2),
            account.PTC_VARIABLE: Vector((ptc,) * 2),
            "household_tax_before_refundable_credits": Vector((5, 9)),
            "marketplace_net_premium": Vector((9000, 9001)),
            "chip_premium": Vector((8000, 8001)),
            "chip_gross": Vector((7000, 7001)),
            "assigned_aca_ptc": Vector((6000, 6001)),
        }
        self.anchor = {"FAKE_MEDICAID_NET": (19, 23), "FAKE_CHIP_NET": (chip, chip)}
        self.calls = []
        self.memberships = (0, 0, 1)

    def native(self, name):
        if name in self.anchor:
            return Vector(self.anchor[name])
        if name in self.inputs:
            value = self.inputs[name]
            if not isinstance(value, Vector) or len(value) != 2:
                raise ValueError("FAKE_ONLY_SHAPE_MISMATCH")
            return value
        variable = self.variables[name]  # Missing inputs must raise, never default.
        out = Vector((0, 0))
        for component in getattr(variable, "adds", ()):
            out = out + self.native(component)
        for component in getattr(variable, "subtracts", ()):
            out = out - self.native(component)
        return out

    def calc(self, name, *, period, map_to):
        self.calls.append((name, period, map_to))
        values = self.native(name)
        if map_to == "person":
            return MicroSeries((values[i] for i in self.memberships), (2, 2, 5))
        return MicroSeries(values, (2, 5))


def live_context(sim):
    spec = sim.spec
    return {
        "law_year": spec.law_year,
        "reporting_year": spec.reporting_year,
        "runtime_identity_sha256": spec.runtime_identity_sha256,
        "reference_preparation_sha256": spec.reference_preparation_sha256,
        "health_price_anchor_sha256": anchor_hash(sim.anchor),
        "price_basis_sha256": spec.price_basis_sha256,
        "component_ledger_sha256": spec.component_ledger_sha256,
    }


def build_fake_account(*, ptc=7, chip=11):
    anchor = {"FAKE_MEDICAID_NET": (19, 23), "FAKE_CHIP_NET": (chip, chip)}
    spec = account_spec(anchor)
    reform = account.make_account_reform(spec)()
    reform.apply()
    sim = FakeSimulation(spec, reform.variables, ptc=ptc, chip=chip)
    return sim, account.GovernmentTransferAccount(spec, live_context)


@settings(max_examples=30, database=None, deadline=None, derandomize=True)
@given(ptc=st.integers(0, 1000), change=st.integers(1, 1000))
def test_fake_credit_changes_G_once_and_leaves_C0_unchanged(ptc, change):
    with pytest.MonkeyPatch.context() as monkeypatch:
        install_fake_engine_api(monkeypatch)
        first, _ = build_fake_account(ptc=ptc)
        second, _ = build_fake_account(ptc=ptc + change)
        assert first.native(account.CASH_VARIABLE) == second.native(
            account.CASH_VARIABLE
        )
        delta = second.native(account.GOVERNMENT_VARIABLE) - first.native(
            account.GOVERNMENT_VARIABLE
        )
        assert delta == Vector((change, change))


@settings(max_examples=30, database=None, deadline=None, derandomize=True)
@given(chip=st.integers(0, 1000), change=st.integers(1, 1000))
def test_fake_chip_is_net_once_and_extra_premiums_do_not_change_G(chip, change):
    with pytest.MonkeyPatch.context() as monkeypatch:
        install_fake_engine_api(monkeypatch)
        first, _ = build_fake_account(chip=chip)
        second, _ = build_fake_account(chip=chip + change)
        second.inputs["chip_premium"] = Vector((99999, 99999))
        second.inputs["marketplace_net_premium"] = Vector((88888, 88888))
        second.inputs["chip_gross"] = Vector((77777, 77777))
        second.inputs["assigned_aca_ptc"] = Vector((66666, 66666))
        delta = second.native(account.GOVERNMENT_VARIABLE) - first.native(
            account.GOVERNMENT_VARIABLE
        )
        assert delta == Vector((change, change))


def test_fake_currency_divides_once_and_managed_projection_keeps_weights(
    fake_engine_api,
):
    sim, read = build_fake_account()
    native = sim.native(account.GOVERNMENT_VARIABLE)
    hh = read(sim, period=2017, map_to="household")
    people = read(sim, period=2017, map_to="person")
    assert hh.values == pytest.approx(tuple(value / float(D) for value in native))
    assert people.values == (hh.values[0], hh.values[0], hh.values[1])
    assert hh.weights == (2, 5) and people.weights == (2, 2, 5)
    assert sim.calls == [
        (account.GOVERNMENT_VARIABLE, 2017, "household"),
        (account.GOVERNMENT_VARIABLE, 2017, "person"),
    ]


def test_fake_live_witness_refuses_price_mutation_before_calc(fake_engine_api):
    sim, read = build_fake_account()
    read(sim)
    sim.calls.clear()
    sim.anchor["FAKE_CHIP_NET"] = (100, 100)
    with pytest.raises(ValueError, match="identity"):
        read(sim)
    assert sim.calls == []


def test_fake_static_receipt_is_demonstrably_not_a_live_witness(fake_engine_api):
    sim, _ = build_fake_account()
    receipt = live_context(sim)
    stale = account.GovernmentTransferAccount(sim.spec, lambda ignored: receipt)
    before = stale(sim).values
    sim.anchor["FAKE_CHIP_NET"] = (100, 100)
    assert stale(sim).values != before
    # This PASS documents an integration gap, not protection by a static getter.


@pytest.mark.parametrize(
    "missing",
    [
        "health_price_anchor_sha256",
        "runtime_identity_sha256",
        "component_ledger_sha256",
    ],
)
def test_fake_missing_context_refuses_before_calc(fake_engine_api, missing):
    sim, _ = build_fake_account()
    context = live_context(sim)
    del context[missing]
    read = account.GovernmentTransferAccount(sim.spec, lambda ignored: context)
    with pytest.raises(ValueError, match="identity"):
        read(sim)
    assert sim.calls == []


@pytest.mark.parametrize(
    "change",
    [
        {"nonhealth_benefits": ("FAKE_NONHEALTH", "FAKE_NONHEALTH")},
        {"nonptc_government_health": ("assigned_aca_ptc",)},
        {"nonptc_government_health": ("chip_gross",)},
        {"nonptc_government_health": ("chip_premium",)},
        {"nonptc_government_health": ("marketplace_net_premium",)},
        {"health_price_anchor_sha256": "PENDING"},
        {"native_per_reference_dollar": Fraction(1)},
    ],
)
def test_fake_invalid_account_contract_refuses(change):
    with pytest.raises(ValueError):
        replace(account_spec({"MOCK": 1}), **change)


def test_fake_missing_input_is_not_zero_or_another_component(fake_engine_api):
    sim, read = build_fake_account()
    del sim.inputs["FAKE_NONHEALTH"]
    with pytest.raises(KeyError):
        read(sim)


def test_fake_wrong_period_and_unweighted_result_refuse(fake_engine_api):
    sim, read = build_fake_account()
    with pytest.raises(ValueError, match="clock"):
        read(sim, period=2025)
    assert sim.calls == []
    sim.calc = lambda *args, **kwargs: [123, 456]
    with pytest.raises(TypeError, match="weighted"):
        read(sim)


class Lookup:
    def __init__(self, values):
        self.values = values

    def __getitem__(self, states):
        if not isinstance(states, Vector):
            raise TypeError("FAKE_ONLY_EXPLICIT_STATE_VECTOR_REQUIRED")

        def by_area(areas):
            if len(states) != len(areas):
                raise ValueError("FAKE_ONLY_SHAPE_MISMATCH")
            return Vector(
                self.values[state][area] for state, area in zip(states, areas)
            )

        return BoundLookup(by_area)


class BoundLookup:
    def __init__(self, function):
        self.function = function

    def __getitem__(self, areas):
        return self.function(areas)


class FakeHousehold:
    def __init__(self):
        self.inputs = {
            "state_code": Vector(("FAKE_A", "FAKE_B")),
            "slcsp_rating_area": Vector((1, 2)),
        }
        self.calls = []

    def __call__(self, name, period):
        self.calls.append((name, period.start.year, period.month))
        return self.inputs[name]


class FakeParameters:
    def __init__(self):
        silver = Lookup({"FAKE_A": {1: 100}, "FAKE_B": {1: 200, 2: 300}})
        bronze = Lookup({"FAKE_A": {1: 40}, "FAKE_B": {1: 80, 2: 120}})
        self.reference = SimpleNamespace(
            gov=SimpleNamespace(
                aca=SimpleNamespace(
                    state_rating_area_cost=silver,
                    lcbp=SimpleNamespace(state_rating_area_cost=bronze),
                )
            )
        )
        self.calls = []

    def __call__(self, date):
        self.calls.append(date)
        if date != "2025-01-01":
            raise KeyError("FAKE_ONLY_NO_COUPLED_2018_SOURCE_FALLBACK")
        return self.reference


def period(year=2017, month=1):
    return SimpleNamespace(start=SimpleNamespace(year=year), month=month)


def price_registry(existing=None):
    reform = prices.make_reference_benchmark_reform()()
    reform.variables.update(existing or {})
    reform.apply()
    return reform.variables


def test_fake_reference_base_changes_but_native_age_rule_stays_untouched(
    fake_engine_api,
):
    class FakeNativeAgeRule:
        @staticmethod
        def formula(p):
            return Fraction(3, 5) if p.start.year == 2017 else Fraction(4, 5)

    registry = price_registry({"slcsp_age_curve_multiplier": FakeNativeAgeRule})
    household, params = FakeHousehold(), FakeParameters()
    assert set(registry) == {"slcsp_age_0", "lcbp_age_0", "slcsp_age_curve_multiplier"}
    assert registry["slcsp_age_curve_multiplier"] is FakeNativeAgeRule
    for month in range(1, 13):
        p = period(month=month)
        silver = registry["slcsp_age_0"].formula(household, p, params)
        bronze = registry["lcbp_age_0"].formula(household, p, params)
        assert silver == pytest.approx((100 * float(D), 300 * float(D)))
        assert bronze == pytest.approx((40 * float(D), 120 * float(D)))
        native_curve = registry["slcsp_age_curve_multiplier"].formula(p)
        assert silver[0] * native_curve == pytest.approx(
            100 * float(D) * Fraction(3, 5)
        )
        assert silver[0] * native_curve != pytest.approx(
            100 * float(D) * Fraction(4, 5)
        )
    assert params.calls == ["2025-01-01"] * 24
    # The invented 3/5 and4/5 factors are MOCK semantics, never legal age factors.


@pytest.mark.parametrize("name", ["state_code", "slcsp_rating_area"])
def test_fake_missing_geography_input_does_not_default(fake_engine_api, name):
    household = FakeHousehold()
    del household.inputs[name]
    with pytest.raises(KeyError):
        price_registry()["slcsp_age_0"].formula(household, period(), FakeParameters())


def test_fake_shape_mismatch_refuses_in_injected_vector_contract(fake_engine_api):
    household = FakeHousehold()
    household.inputs["slcsp_rating_area"] = Vector((1,))
    with pytest.raises(ValueError, match="SHAPE"):
        price_registry()["slcsp_age_0"].formula(household, period(), FakeParameters())


def test_fake_missing_bronze_source_never_reuses_silver(fake_engine_api):
    params = FakeParameters()
    del params.reference.gov.aca.lcbp.state_rating_area_cost
    with pytest.raises(AttributeError):
        price_registry()["lcbp_age_0"].formula(FakeHousehold(), period(), params)


def test_fake_unknown_area_zero_is_a_recorded_limit_not_a_validated_price(
    fake_engine_api,
):
    household = FakeHousehold()
    household.inputs["slcsp_rating_area"] = Vector((0, 2))
    actual = price_registry()["slcsp_age_0"].formula(
        household, period(), FakeParameters()
    )
    assert actual[0] == 0 and actual[1] > 0


def test_fake_native_out_of_year_price_read_refuses(fake_engine_api):
    with pytest.raises(ValueError, match="law year"):
        price_registry()["slcsp_age_0"].formula(
            FakeHousehold(), period(2018), FakeParameters()
        )


def test_fake_stored_price_can_shadow_reform_without_external_input_guard(
    fake_engine_api,
):
    registry = price_registry()
    stored = {"slcsp_age_0": Vector((99999, 99999))}
    # Mimic only Core's documented input-before-formula precedence.
    observed = (
        stored["slcsp_age_0"]
        if "slcsp_age_0" in stored
        else registry["slcsp_age_0"].formula(
            FakeHousehold(), period(), FakeParameters()
        )
    )
    assert observed == Vector((99999, 99999))
    assert set(stored) & prices.FORBIDDEN_STORED_PRICE_INPUTS
    # The caller must enforce this denylist before constructing the simulation.
