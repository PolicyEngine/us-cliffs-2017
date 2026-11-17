"""Fake callback sequencing only; source proofs here bind synthetic fixtures."""

from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_health_valuation as fake

from cliffs2017 import health_valuation, native_health_hooks as hooks
from cliffs2017.government_transfer_account import AccountSpec
from cliffs2017.native_materializer import FROZEN_IRMAA_STRATEGY, input_digest
from cliffs2017.native_witness import WitnessError


class System:
    def __init__(self, parameter_path):
        self.variables = {}
        self.leaf = SimpleNamespace(
            name="FAKE.price", file_path=str(parameter_path), value=100.0
        )
        self.leaf.get_at_instant = lambda instant: self.leaf.value
        self.parameters = SimpleNamespace(get_child=lambda path: self.leaf)
        for name in set(hooks.REFERENCE_ORIGINALS) | set(hooks.NATIVE_ORIGINALS):
            self.variables[name] = variable(
                entity="tax_unit" if name == hooks.IRMAA_INPUT else "person",
                formula=fake.source_formula,
            )

    def apply_reform_set(self, reforms):
        if isinstance(reforms, tuple):
            for reform in reforms:
                self.apply_reform_set(reform)
        else:
            reforms.apply(self)

    def add_variable(self, cls):
        self.variables[cls.__name__] = variable(
            entity=cls.entity.key,
            period=cls.definition_period,
            formula=cls.__dict__.get("formula"),
            defined_for=cls.defined_for,
            adds=getattr(cls, "adds", None),
        )


def variable(
    *, entity="household", period="year", formula=None, defined_for=None, adds=None
):
    return SimpleNamespace(
        entity=SimpleNamespace(key=entity),
        definition_period=period,
        value_type=float,
        get_formula=lambda period: formula,
        defined_for=defined_for,
        adds=adds,
        subtracts=None,
        is_neutralized=False,
        dtype=fake.Float32,
    )


def reference_reform(**kwargs):
    return health_valuation.make_reference_health_unit_reform(
        **kwargs, model_api=fake.API, reform_type=fake.Reform
    )


def valuation_reform():
    return health_valuation.make_health_valuation_reform(
        model_api=fake.API, reform_type=fake.Reform
    )


def account_reform(spec):
    class Account:
        def apply(system):
            system.variables[hooks.CASH_VARIABLE] = variable(adds=["FAKE.cash"])
            system.variables[hooks.GOVERNMENT_VARIABLE] = variable(
                adds=[hooks.CASH_VARIABLE]
            )

    return Account


def price_reform():
    class Prices:
        def apply(system):
            for name in ("slcsp_age_0", "lcbp_age_0"):
                system.variables[name] = variable(
                    period="month", formula=fake.source_formula
                )

    return Prices


def proof(function):
    import inspect

    path = Path(inspect.getsourcefile(function))
    return path.name, sha256(path.read_bytes()).hexdigest()


def pipeline(monkeypatch, tmp_path):
    """Use actual hook implementations with deliberately fake constructor/APIs."""
    monkeypatch.setattr(hooks, "make_reference_health_unit_reform", reference_reform)
    monkeypatch.setattr(hooks, "make_health_valuation_reform", valuation_reform)
    monkeypatch.setattr(hooks, "make_account_reform", account_reform)
    monkeypatch.setattr(hooks, "make_reference_benchmark_reform", price_reform)
    monkeypatch.setattr(hooks, "PARAMETER_WATCH", (("FAKE.price", "2025-01-01"),))
    param = tmp_path / "FAKE-only-parameter.yaml"
    param.write_text("Synthetic test configuration; no legal or empirical values.\n")
    runtime = SimpleNamespace(
        versions={"policyengine-core": "3.36.0"}, source_receipt_sha256="a" * 64
    )
    observed = [runtime]
    readers = {
        "get_holder": fake.ReferenceSimulation.get_holder,
        "get_array": fake.ReferenceHolder.get_array,
        "get_known_periods": fake.ReferenceHolder.get_known_periods,
    }
    methods = {name: getattr(fake.Simulation, name) for name in hooks.CORE_METHODS}
    proofs = {
        name: proof(function) for name, function in {**readers, **methods}.items()
    }
    proofs.update(
        {
            name: proof(fake.source_formula)
            for name in set(hooks.REFERENCE_ORIGINALS) | set(hooks.NATIVE_ORIGINALS)
        }
    )
    proofs.update(
        {
            "health_valuation": proof(reference_reform),
            "government_transfer_account": proof(account_reform),
            "reference_benchmark_prices": proof(price_reform),
            "FAKE.price": (param.name, sha256(param.read_bytes()).hexdigest()),
        }
    )
    reference = hooks.ReferenceHealthSetup(
        expected_runtime=runtime,
        observe_runtime=lambda: observed[0],
        person_count=2,
        source_proofs=proofs,
        core_readers=readers,
    )
    reference_system = reference.prepare_system(System(param))
    reference_sim = fake.ReferenceSimulation()
    reference_sim.tax_benefit_system = reference_system
    reference_sim.default_calculation_period = "2025"
    reference.capture_reference(reference_sim)
    anchor = reference.anchor_digest
    spec = AccountSpec(
        nonhealth_benefits=("FAKE.cash",),
        nonptc_government_health=tuple(sorted(hooks.HEALTH_OUTPUTS)),
        runtime_identity_sha256="a" * 64,
        reference_preparation_sha256="b" * 64,
        health_price_anchor_sha256=anchor,
        price_basis_sha256="c" * 64,
    )
    native = hooks.NativeHealthHooks(
        reference=reference,
        account_spec=spec,
        core_methods=methods,
        source_proofs=proofs,
    )
    sim = fake.Simulation()
    sim.tax_benefit_system = native.prepare_system(System(param))
    sim.default_calculation_period = "2017"
    fixed = native.prepare_health(sim)
    return reference, native, sim, fixed, anchor, observed


def final_witness(native, sim, fixed):
    sim.inputs[hooks.IRMAA_INPUT] = fake.Array([6.0, 8.0])

    def read_prior_input(name, *, period, map_to):
        assert (name, period, map_to) == (hooks.IRMAA_INPUT, 2017, "tax_unit")
        return tuple(sim.inputs[name].tolist())

    sim.calc = read_prior_input
    receipt = {
        "strategy": FROZEN_IRMAA_STRATEGY,
        "benefit_year": 2017,
        "income_year": 2015,
        "current_context": native.context,
        "frozen_values_sha256": input_digest((6.0, 8.0)),
    }
    return native.witness_builder(sim, fixed, receipt)


def test_actual_callbacks_sequence_without_fake_pre_freeze_irmaa_expectation(
    monkeypatch, tmp_path
):
    reference, native, sim, fixed, anchor, _ = pipeline(monkeypatch, tmp_path)
    assert hooks.IRMAA_INPUT not in sim.inputs
    assert native.pre_freeze_context(sim) == native.context
    assert (
        reference.anchor_digest == anchor
    )  # Native receipt additions keep identity stable.
    assert "native_year" in reference.capture.receipt
    observe = final_witness(native, sim, fixed)
    assert observe(sim) == native.context
    assert {item.name for item in observe.fixed_inputs} == hooks.HEALTH_INPUTS | {
        hooks.IRMAA_INPUT
    }
    expected_masks = {item.name: item.defined_for for item in observe.variables}
    assert all(expected_masks[name] is None for name in hooks.HEALTH_INPUTS)
    assert set(expected_masks[name] for name in hooks.HEALTH_OUTPUTS) == {
        "medicaid_enrolled",
        "chip_enrolled",
        "medicare_enrolled",
    }


@pytest.mark.parametrize(
    "change", ["mask", "parameter", "health_input", "derived_override"]
)
def test_pre_freeze_actual_state_changes_refuse(monkeypatch, tmp_path, change):
    _, native, sim, _, _, _ = pipeline(monkeypatch, tmp_path)
    if change == "mask":
        sim.tax_benefit_system.variables[
            health_valuation.CHIP_VALUE
        ].defined_for = "FAKE.other"
    elif change == "parameter":
        sim.tax_benefit_system.leaf.value += 1
    elif change == "health_input":
        sim.inputs[health_valuation.CHIP_UNIT].values[0] += 1
    else:
        sim.inputs[health_valuation.CHIP_VALUE] = fake.Array([999, 999])
    with pytest.raises(WitnessError):
        native.pre_freeze_context(sim)


@pytest.mark.parametrize("change", ["irmaa", "derived_health"])
def test_final_live_witness_rechecks_supplied_inputs(monkeypatch, tmp_path, change):
    _, native, sim, fixed, _, _ = pipeline(monkeypatch, tmp_path)
    observe = final_witness(native, sim, fixed)
    name = hooks.IRMAA_INPUT if change == "irmaa" else health_valuation.MEDICAID_VALUE
    sim.inputs[name] = fake.Array([7.0, 8.0])
    with pytest.raises(WitnessError):
        observe(sim)


def test_changed_runtime_refuses_at_the_actual_callback(monkeypatch, tmp_path):
    _, native, sim, _, _, observed = pipeline(monkeypatch, tmp_path)
    observed[0] = object()
    with pytest.raises(WitnessError, match="runtime/source"):
        native.pre_freeze_context(sim)


def test_source_proof_checks_real_fixture_bytes_and_rejects_wrong_hash():
    with pytest.raises(WitnessError, match="source bytes"):
        hooks._source(fake.source_formula, (Path(fake.__file__).name, "0" * 64))


def test_deferred_core_loader_preserves_exact_method_objects_without_imports():
    class Simulation(fake.Simulation):
        get_holder = fake.ReferenceSimulation.get_holder

    readers, inputs = hooks.load_core_readers(
        simulation_type=Simulation, holder_type=fake.ReferenceHolder
    )
    assert readers == {
        "get_holder": fake.ReferenceSimulation.get_holder,
        "get_array": fake.ReferenceHolder.get_array,
        "get_known_periods": fake.ReferenceHolder.get_known_periods,
    }
    assert inputs == {
        name: getattr(fake.Simulation, name) for name in hooks.CORE_METHODS
    }
    with pytest.raises(WitnessError, match="both explicit"):
        hooks.load_core_readers(simulation_type=Simulation)
