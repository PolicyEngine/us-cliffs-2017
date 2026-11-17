"""Fake Core-shaped storage tests; no model, population or legal goldens."""

import struct
from dataclasses import dataclass, replace
from types import SimpleNamespace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from cliffs2017 import native_witness as witness


@dataclass(frozen=True)
class FakePeriod:
    text: str

    def __str__(self):
        return self.text

    @property
    def unit(self):
        return (
            "eternity"
            if self.text == "eternity"
            else "month"
            if len(self.text) == 7
            else "year"
        )


class FakeArray:
    """Invented fixed input, with explicit bytes/dtype/shape for protocol tests."""

    def __init__(self, values, *, kind="f", shape=None):
        self.values = list(values)
        self.dtype = SimpleNamespace(kind=kind, str="<f8" if kind == "f" else "<i8")
        self.shape = shape if shape is not None else (len(self.values),)

    def tolist(self):
        return list(self.values)

    def tobytes(self, *, order):
        assert order == "C"
        fmt = "d" if self.dtype.kind == "f" else "q"
        return struct.pack("<" + fmt * len(self.values), *self.values)


def fake_price_formula(*unused):
    raise AssertionError("Witness must never calculate a price")


def alternate_fake_formula(*unused):
    raise AssertionError("Witness must reject a changed formula before calculation")


class FakeVariable:
    def __init__(self, *, entity="household", period="year", formula=None, adds=None):
        self.entity = SimpleNamespace(key=entity)
        self.definition_period = period
        self.value_type = float
        self.formula = formula
        self.adds = adds
        self.subtracts = None
        self.is_neutralized = False

    def get_formula(self, period):
        return self.formula


class FakeLeaf:
    def __init__(self, value):
        self.values = {"2025-01-01": value}

    def get_at_instant(self, instant):
        return self.values[instant]


class FakeParameters:
    def __init__(self):
        self.leaf = FakeLeaf(100.0)

    def get_child(self, path):
        assert path == "FAKE.reference_price"
        return self.leaf


class FakeSimulation:
    def __init__(self):
        variables = {
            witness.CASH_VARIABLE: FakeVariable(adds=["FAKE_CASH"]),
            witness.GOVERNMENT_VARIABLE: FakeVariable(adds=[witness.CASH_VARIABLE]),
            "slcsp_age_0": FakeVariable(period="month", formula=fake_price_formula),
            "lcbp_age_0": FakeVariable(period="month", formula=fake_price_formula),
            "FAKE_HEALTH_UNIT": FakeVariable(),
            witness.IRMAA_INPUT: FakeVariable(
                entity="tax_unit", formula=fake_price_formula
            ),
            # A named ingress may legitimately override a formula. It is not a price/account.
            "is_spm_independent_minor_role": FakeVariable(
                entity="person", formula=fake_price_formula
            ),
        }
        self.tax_benefit_system = SimpleNamespace(
            variables=variables, parameters=FakeParameters()
        )
        self.supplied = {
            "FAKE_HEALTH_UNIT": {FakePeriod("2017"): FakeArray([2.0, 4.0])},
            witness.IRMAA_INPUT: {FakePeriod("2017"): FakeArray([6.0, 8.0])},
        }
        self.computed_cache = {}

    def _get_set_input_periods(self, name):
        return list(self.supplied.get(name, {}))

    def _get_recorded_input_array(self, name, period):
        # Actual Core takes its Period object here, not the declaration string.
        assert isinstance(period, FakePeriod)
        return self.supplied.get(name, {}).get(period)

    def get_input_variables(self, include_computed_variables=False):
        # Deliberately emulate the structural-input filter that misses formula overrides.
        return []

    def calc(self, *args, **kwargs):
        raise AssertionError("Witness must not calculate")

    def set_input(self, *args, **kwargs):
        raise AssertionError("Witness must not mutate inputs")


def configuration(sim):
    context = {key: "a" * 64 for key in witness.CONTEXT_DIGESTS}
    context.update(law_year=2017, reporting_year=2025)
    variables = tuple(
        witness.VariableExpectation(
            name,
            "2017",
            variable.formula,
            variable.entity.key,
            variable.definition_period,
            adds=variable.adds,
        )
        for name, variable in sim.tax_benefit_system.variables.items()
        if name in witness.REQUIRED_VARIABLES
    )
    fixed = tuple(
        witness.FixedInput.from_array(
            name, "2017", entity, purpose, sim.supplied[name][FakePeriod("2017")]
        )
        for name, entity, purpose in (
            ("FAKE_HEALTH_UNIT", "household", "health_unit_value"),
            (witness.IRMAA_INPUT, "tax_unit", "frozen_irmaa"),
        )
    )
    return context, {
        "core_version": "3.36.0",
        "core_methods": {
            name: getattr(FakeSimulation, name) for name in witness.CORE_METHODS
        },
        "variables": variables,
        "parameters": {("FAKE.reference_price", "2025-01-01"): 100.0},
        "fixed_inputs": fixed,
    }


def prepared():
    sim = FakeSimulation()
    context, options = configuration(sim)
    return sim, witness.LiveContextWitness(context, **options)


def test_fake_valid_baseline_and_branch_require_no_calculation_or_mutation():
    baseline, observe = prepared()
    branch = FakeSimulation()
    assert observe(baseline) == observe(branch)
    observe.audit(baseline, branch, object())
    observe.audit(baseline, None, object())


@settings(max_examples=30, database=None, deadline=None, derandomize=True)
@given(
    values=st.lists(st.integers(-1000, 1000), min_size=1, max_size=8),
    delta=st.integers(1, 100),
)
def test_fake_fixed_array_changes_always_refuse_and_exact_restore_accepts(
    values, delta
):
    sim = FakeSimulation()
    sim.supplied["FAKE_HEALTH_UNIT"][FakePeriod("2017")] = FakeArray(values)
    context, options = configuration(sim)
    observe = witness.LiveContextWitness(context, **options)
    observe(sim)
    sim.supplied["FAKE_HEALTH_UNIT"][FakePeriod("2017")].values[0] += delta
    with pytest.raises(witness.WitnessError, match="fixed input changed"):
        observe(sim)
    sim.supplied["FAKE_HEALTH_UNIT"][FakePeriod("2017")] = FakeArray(values)
    assert observe(sim) == context


@pytest.mark.parametrize(
    "name",
    [witness.CASH_VARIABLE, witness.GOVERNMENT_VARIABLE, "slcsp_age_0", "lcbp_age_0"],
)
def test_fake_supplied_formula_override_refuses_even_when_structural_input_list_misses_it(
    name,
):
    sim, observe = prepared()
    sim.supplied[name] = {FakePeriod("2017"): FakeArray([999.0, 999.0])}
    assert sim.get_input_variables(False) == []
    with pytest.raises(witness.WitnessError, match="supplied derived"):
        observe(sim)


def test_fake_computed_price_cache_and_named_source_role_ingress_do_not_refuse():
    sim, observe = prepared()
    sim.computed_cache["slcsp_age_0"] = FakeArray([999.0, 999.0])
    sim.supplied["is_spm_independent_minor_role"] = {
        FakePeriod("eternity"): FakeArray([1, 0], kind="i")
    }
    observe(sim)


@pytest.mark.parametrize(
    "change", ["formula", "adds", "entity", "period", "value_type", "neutralized"]
)
def test_fake_active_variable_definition_changes_refuse(change):
    sim, observe = prepared()
    variable = sim.tax_benefit_system.variables["slcsp_age_0"]
    if change == "formula":
        variable.formula = alternate_fake_formula
    elif change == "adds":
        variable.adds = ["FAKE_OTHER"]
    elif change == "entity":
        variable.entity = SimpleNamespace(key="person")
    elif change == "period":
        variable.definition_period = "year"
    elif change == "value_type":
        variable.value_type = int
    else:
        variable.is_neutralized = True
    with pytest.raises(
        witness.WitnessError, match="formula changed|definition changed"
    ):
        observe(sim)


def test_fake_in_place_parameter_mutation_refuses():
    sim, observe = prepared()
    sim.tax_benefit_system.parameters.leaf.values["2025-01-01"] = 101.0
    with pytest.raises(witness.WitnessError, match="parameter value changed"):
        observe(sim)


@pytest.mark.parametrize(
    "change",
    ["missing", "not_recorded", "entity", "period", "dtype", "shape", "nonfinite"],
)
def test_fake_fixed_input_provenance_and_representation_changes_refuse(change):
    sim, observe = prepared()
    name, period = "FAKE_HEALTH_UNIT", FakePeriod("2017")
    if change == "missing":
        sim.supplied[name][period] = None
    elif change == "not_recorded":
        sim.computed_cache[name] = sim.supplied.pop(name)
    elif change == "entity":
        sim.tax_benefit_system.variables[name].entity = SimpleNamespace(key="person")
    elif change == "period":
        sim.tax_benefit_system.variables[name].definition_period = "month"
    elif change == "dtype":
        sim.supplied[name][period] = FakeArray([2, 4], kind="i")
    elif change == "shape":
        sim.supplied[name][period].shape = (1, 2)
    else:
        sim.supplied[name][period].values[0] = float("nan")
    with pytest.raises(witness.WitnessError):
        observe(sim)


def test_fake_frozen_irmaa_is_allowed_but_branch_reimputation_refuses_post_audit():
    baseline, observe = prepared()
    branch = FakeSimulation()
    observe(branch)
    branch.supplied[witness.IRMAA_INPUT][FakePeriod("2017")] = FakeArray([7.0, 8.0])
    with pytest.raises(witness.WitnessError, match="fixed input changed"):
        observe.audit(baseline, branch, None)


@pytest.mark.parametrize("change", ["missing_method", "overridden_method"])
def test_fake_core_provenance_api_drift_refuses(change):
    sim, observe = prepared()
    if change == "missing_method":
        sim._get_set_input_periods = None
    else:
        sim._get_set_input_periods = lambda name: []
    with pytest.raises(witness.WitnessError, match="Core input-provenance"):
        observe(sim)


@pytest.mark.parametrize(
    "name", [witness.CASH_VARIABLE, witness.GOVERNMENT_VARIABLE, "slcsp_age_0"]
)
def test_fake_declared_derived_input_guard_checks_names_without_touching_values(name):
    with pytest.raises(witness.WitnessError, match="supplied derived"):
        witness.reject_declared_price_inputs({name: object()})
    witness.reject_declared_price_inputs(
        {witness.IRMAA_INPUT: object(), "is_spm_independent_minor_role": object()}
    )


@pytest.mark.parametrize(
    "missing", ["variables", "parameters", "health", "irmaa", "digest", "core_version"]
)
def test_fake_incomplete_witness_declarations_refuse(missing):
    sim = FakeSimulation()
    context, options = configuration(sim)
    if missing == "variables":
        options["variables"] = ()
    elif missing == "parameters":
        options["parameters"] = {}
    elif missing in ("health", "irmaa"):
        purpose = "health_unit_value" if missing == "health" else "frozen_irmaa"
        options["fixed_inputs"] = tuple(
            x for x in options["fixed_inputs"] if x.purpose != purpose
        )
    elif missing == "digest":
        context.pop("health_price_anchor_sha256")
    else:
        options["core_version"] = "UNKNOWN"
    with pytest.raises(witness.WitnessError):
        witness.LiveContextWitness(context, **options)


def test_fake_wrong_irmaa_period_cannot_become_a_frozen_history_exception():
    sim = FakeSimulation()
    _, options = configuration(sim)
    irmaa = next(x for x in options["fixed_inputs"] if x.purpose == "frozen_irmaa")
    with pytest.raises(witness.WitnessError, match="benefit-year2017"):
        replace(irmaa, period="2015")
