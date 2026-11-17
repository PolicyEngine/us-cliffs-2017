"""Synthetic bridge contracts only; no engine, input artifact or policy values."""

from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from types import SimpleNamespace

import pytest

from cliffs2017.commissioned import REQUIRED_BINDINGS
from cliffs2017.government_transfer_account import GOVERNMENT_VARIABLE, AccountSpec
from cliffs2017.managed_native import ENTITIES, InputSpec, PacketPlan, RuntimeBinding
from cliffs2017.native_materializer import IRMAA_INPUT, WrittenDataset
from cliffs2017.native_runtime import (
    BridgeError,
    NativeInputs,
    NativeTools,
    make_native_runtime,
)

SHA = "a" * 64
FACTOR = Fraction(245120, 321943)


class MicroSeries:
    __module__ = "microdf.synthetic"

    def __init__(self, values, weights=(2,)):
        self.data, self.weights = tuple(values), tuple(weights)

    def tolist(self):
        return list(self.data)

    def copy(self):
        return MicroSeries(self.data, self.weights)

    def __mul__(self, amount):
        return MicroSeries(tuple(value * amount for value in self.data), self.weights)

    def __truediv__(self, amount):
        return MicroSeries(tuple(value / amount for value in self.data), self.weights)


def specimen():
    arrays, specs = {}, {}
    for entity in ENTITIES:
        arrays[f"{entity}_id"] = {"eternity": (11,)}
        specs[f"{entity}_id"] = InputSpec(entity, "eternity", "int64", "id")
        if entity != "person":
            arrays[f"person_{entity}_id"] = {"eternity": (11,)}
            specs[f"person_{entity}_id"] = InputSpec(
                "person", "eternity", "int64", "id"
            )
            arrays[f"person_{entity}_role"] = {"eternity": ("member",)}
            specs[f"person_{entity}_role"] = InputSpec(
                "person", "eternity", "str", "category"
            )
    plan = PacketPlan(
        2017, 2025, arrays, specs, {e: 1 for e in ENTITIES}, SHA, SHA, SHA, FACTOR, {}
    )
    spec = AccountSpec(("synthetic_cash",), ("synthetic_health",), SHA, SHA, SHA, SHA)
    context = {
        "law_year": 2017,
        "reporting_year": 2025,
        "runtime_identity_sha256": SHA,
        "reference_preparation_sha256": SHA,
        "health_price_anchor_sha256": SHA,
        "price_basis_sha256": SHA,
        "component_ledger_sha256": spec.component_ledger_sha256,
        "native_price_factor": (FACTOR.numerator, FACTOR.denominator),
    }
    events, constructed, helper_calls = [], [], []

    class System:
        def __init__(self):
            self.variables = {
                name: SimpleNamespace(
                    entity=SimpleNamespace(key=s.entity), definition_period=s.period
                )
                for name, s in specs.items()
            }
            self.variables[IRMAA_INPUT] = SimpleNamespace(
                entity=SimpleNamespace(key="tax_unit"), definition_period="year"
            )
            self.group_entities = [
                SimpleNamespace(
                    key=e, flattened_roles=[SimpleNamespace(key="member", max=None)]
                )
                for e in ENTITIES - {"person"}
            ]

        def parameters(self, year):
            return SimpleNamespace(
                gov=SimpleNamespace(
                    simulation=SimpleNamespace(
                        medicare_irmaa_uses_current_year_income=False
                    )
                )
            )

        def add_variable(self, variable):
            self.variables[variable.__name__] = variable

    class Simulation:
        def __init__(self, system):
            self.tax_benefit_system = system
            self.dataset = SimpleNamespace(
                data_format="time_period_arrays",
                time_period="2017",
                load_dataset=lambda: arrays,
            )
            self.default_input_period = self.default_calculation_period = "2017"
            self.populations = {"tax_unit": SimpleNamespace(count=1)}
            self.inputs, self.branches, self.imputations = {}, {}, 0
            self.valid = True

        def _get_set_input_periods(self, name):
            return ["2017"] if name in self.inputs else []

        def set_input(self, name, period, vector):
            self.inputs[name] = vector.copy()

        def calc(self, name, *, period, map_to):
            assert period == 2017
            if name == IRMAA_INPUT:
                if name not in self.inputs:
                    self.imputations += 1
                    events.append("impute")
                return self.inputs.get(name, MicroSeries((1000,))).copy()
            assert name == GOVERNMENT_VARIABLE
            return MicroSeries((100,))

    def system(**kwargs):
        events.append(("system", kwargs))
        return System()

    def managed(**kwargs):
        events.append(("managed", kwargs))
        actual = Simulation(kwargs["tax_benefit_system"])
        constructed.append(actual)
        return actual

    def create_branch(sim, period, name, changes):
        helper_calls.append((period, name, changes))
        branch = Simulation(sim.tax_benefit_system)
        branch.inputs = deepcopy(sim.inputs)
        branch.cliffs_native = sim.cliffs_native
        sim.branches[name] = branch
        return branch

    class Witness:
        def __call__(self, sim):
            events.append("live-witness")
            if not sim.valid:
                raise BridgeError("synthetic current state changed")
            return dict(context)

        def audit(self, baseline, branch, selected):
            self(baseline)
            self(branch)

    def prepare_system(actual):
        events.append("final-definitions")
        return actual

    def health(sim):
        events.append("health")
        return ("explicit-synthetic-fixed-input",)

    def witness(sim, health_inputs, irmaa):
        assert health_inputs == ("explicit-synthetic-fixed-input",)
        assert IRMAA_INPUT in sim.inputs and "not observed" in irmaa["provenance"]
        events.append("witness-built")
        return Witness()

    def hourly(sim, *, is_weighted, period):
        result = MicroSeries((10,))
        assert period == 2017 and is_weighted(result)
        return result

    tools = NativeTools(
        managed,
        system,
        SimpleNamespace(Variable=object, Person=object, Household=object, YEAR="year"),
        create_branch,
        lambda person, period, increase: {"unchanged_helper": increase},
        lambda value: isinstance(value, MicroSeries),
    )
    artifact = WrittenDataset(
        SimpleNamespace(),
        {
            "status": "SYNTHETIC_SERIALIZER_DOUBLE_NOT_A_DATASET",
            "path": "/synthetic/native.h5",
            "sha256": SHA,
        },
    )
    runtime_binding = RuntimeBinding(
        "b" * 40,
        {
            "policyengine": "6.20.2",
            "policyengine-us": "2.144.0",
            "policyengine-core": "3.36.0",
            "spm-calculator": "1.1.0",
        },
        SHA,
    )
    args = {
        "prepared_inputs": lambda: NativeInputs(
            plan, artifact, lambda path: (SHA, arrays)
        ),
        "tools": tools,
        "expected_runtime": runtime_binding,
        "observe_runtime": lambda: runtime_binding,
        "account_spec": spec,
        "bindings": {name: SHA for name in REQUIRED_BINDINGS},
        "spm": {"synthetic": True},
        "prepare_system": prepare_system,
        "prepare_health": health,
        "pre_freeze_context": lambda sim: dict(context),
        "witness_builder": witness,
        "audit_facts": lambda base, branch, selected: None,
        "hourly_wages_real": hourly,
        "mode": "synthetic_test",
    }
    return SimpleNamespace(
        args=args,
        events=events,
        constructed=constructed,
        helper_calls=helper_calls,
        context=context,
        plan=plan,
        artifact=artifact,
    )


def test_factory_orders_managed_setup_once_and_installs_live_context_after_irmaa():
    s = specimen()
    runtime = make_native_runtime(**s.args)
    sim = runtime.factory()
    assert len(s.constructed) == 1 and sim.imputations == 1
    assert s.events.index("final-definitions") < next(
        i for i, e in enumerate(s.events) if isinstance(e, tuple) and e[0] == "managed"
    )
    assert (
        s.events.index("health")
        < s.events.index("impute")
        < s.events.index("witness-built")
    )
    managed = next(e[1] for e in s.events if isinstance(e, tuple) and e[0] == "managed")
    assert (
        managed["native_input_period"] == "2017" and managed["allow_unmanaged"] is True
    )
    assert "dataset_end_year" not in managed
    runtime.install(sim)
    assert "cliffs_candidate_mask" in sim.tax_benefit_system.variables
    with pytest.raises(BridgeError, match="one prepared baseline"):
        runtime.factory()


def test_account_currency_and_hourly_series_preserve_weights_without_double_conversion():
    s = specimen()
    runtime = make_native_runtime(**s.args)
    sim = runtime.factory()
    account = runtime.account(sim, period=2017, map_to="person")
    assert account.data == (100 / float(FACTOR),) and account.weights == (2,)
    wage = runtime.hourly_wages_real(sim)
    assert wage.data == (10,) and wage.weights == (2,)
    assert runtime.to_reference(runtime.to_native(wage)).data == pytest.approx((10,))
    assert runtime.to_native(wage).weights == wage.weights


def test_live_witness_is_rechecked_for_account_and_each_branch_audit():
    s = specimen()
    runtime = make_native_runtime(**s.args)
    sim = runtime.factory()
    branch = runtime.create_branch(sim, 2017, "owned_raise", {"wages": 1})
    runtime.audit(sim, branch, None)
    assert branch.inputs[IRMAA_INPUT].data == sim.inputs[IRMAA_INPUT].data
    branch.valid = False
    with pytest.raises(BridgeError, match="current state changed"):
        runtime.account(branch, period=2017, map_to="person")
    with pytest.raises(BridgeError):
        runtime.audit(sim, branch, None)
    # commissioned.run owns successful branches and releases them in finally.
    del sim.branches["owned_raise"]


def test_partial_branch_failure_releases_only_its_owned_name():
    s = specimen()

    def broken(sim, period, name, changes):
        sim.branches[name] = object()
        raise RuntimeError("synthetic helper failure")

    s.args["tools"] = replace(s.args["tools"], create_branch=broken)
    runtime = make_native_runtime(**s.args)
    sim = runtime.factory()
    foreign = object()
    sim.branches["foreign"] = foreign
    with pytest.raises(RuntimeError, match="helper failure"):
        runtime.create_branch(sim, 2017, "owned_zero", {})
    assert sim.branches == {"foreign": foreign}
    with pytest.raises(BridgeError, match="new owned branch"):
        runtime.create_branch(sim, 2017, "foreign", {})
    assert sim.branches["foreign"] is foreign


@pytest.mark.parametrize(
    "capability",
    [
        "prepared_inputs",
        "prepare_health",
        "pre_freeze_context",
        "witness_builder",
        "hourly_wages_real",
        "audit_facts",
    ],
)
def test_missing_actual_preparation_capability_refuses_before_any_engine(capability):
    s = specimen()
    s.args[capability] = None
    with pytest.raises(BridgeError, match="Missing actual capability"):
        make_native_runtime(**s.args)
    assert s.constructed == []


def test_synthetic_artifact_cannot_be_relabelled_native():
    s = specimen()
    s.args["mode"] = "native"
    runtime = make_native_runtime(**s.args)
    with pytest.raises(BridgeError, match="synthetic or unbound"):
        runtime.factory()
    assert s.constructed == []


def test_wrong_input_currency_and_failed_factory_do_not_reprepare_silently():
    s = specimen()
    bad = replace(s.plan, native_price_factor=Fraction(1))
    s.args["prepared_inputs"] = lambda: NativeInputs(
        bad, s.artifact, lambda path: (SHA, bad.arrays)
    )
    runtime = make_native_runtime(**s.args)
    with pytest.raises(BridgeError, match="currency differs"):
        runtime.factory()
    with pytest.raises(BridgeError, match="one prepared baseline"):
        runtime.factory()
    assert s.constructed == []
