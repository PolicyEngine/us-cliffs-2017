"""Tiny real array/weighted-selector checks; no model, data or services."""

from copy import deepcopy
import ast
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from types import ModuleType

from microdf import MicroSeries
import numpy as np
import pytest

from cliffs2017.commissioned import PERSON_FLAG
from cliffs2017.managed_native import ENTITIES, InputSpec
from cliffs2017.native_observers import (
    NativeObservers,
    ObservationError,
    TAKEUP_INPUTS,
    _sha,
    _source_chain,
    SOCIAL_SECURITY_SOURCES,
)
from cliffs2017.native_materializer import input_digest


PRE_RESPONSE_INPUTS = {
    name: name + "_before_lsr"
    for name in (
        "employment_income",
        "self_employment_income",
        "sstb_self_employment_income",
    )
}
HELD_BEHAVIORAL_RESPONSE_VARIABLES = ()


def user_set_variables(sim, period):
    return {name for name, _period in sim.data}


def create_branch(*args):
    raise AssertionError("No actual branch constructor in array fixtures")


def earnings_increments(person, period, increase):
    return {
        "employment_income": increase,
        "self_employment_income": increase * 0,
        "sstb_self_employment_income": increase * 0,
    }


class FakeHolder:
    def __init__(self, sim, name):
        self.sim, self.name = sim, name

    def _to_array(self, values, validate_nan=False):
        dtype = self.sim.data[(self.name, "2017")].dtype
        result = np.asarray(values, dtype=dtype)
        if validate_nan and result.dtype.kind == "f" and not np.isfinite(result).all():
            raise ValueError("synthetic nonfinite cast")
        return result


class FakeSim:
    def _get_set_input_periods(self, name):
        return [period for key, period in self.data if key == name]

    def _get_recorded_input_array(self, name, period):
        return self.data.get((name, str(period)))

    def get_holder(self, name):
        return FakeHolder(self, name)

    def get_array(self, name, period):
        return self.data.get((name, str(period)))


def specimen(*, amount=8.0):
    counts = {entity: 2 if entity == "person" else 1 for entity in ENTITIES}
    specs, arrays, populations = {}, {}, {}
    for index, entity in enumerate(sorted(ENTITIES)):
        ids = (21, 34) if entity == "person" else (100 + index,)
        specs[entity + "_id"] = InputSpec(entity, "year", "int64", "id")
        arrays[entity + "_id"] = {"2017": ids}
        pop = SimpleNamespace(ids=np.array(ids, dtype=np.int64), count=len(ids))
        if entity != "person":
            role = SimpleNamespace(key="member", max=None)
            pop.entity = SimpleNamespace(key=entity, flattened_roles=[role])
            pop._members_role = pop.members_role = (role,) * 2
            pop.members_entity_id = np.array([0, 0], dtype=np.int64)
            specs[f"person_{entity}_id"] = InputSpec("person", "year", "int64", "id")
            arrays[f"person_{entity}_id"] = {"2017": ids * 2}
            specs[f"person_{entity}_role"] = InputSpec(
                "person", "eternity", "str", "category"
            )
            arrays[f"person_{entity}_role"] = {"eternity": ("member", "member")}
        populations[entity] = pop
    for name, entity, unit, values in [
        ("age", "person", "age_years", (40.5, 7.0)),
        ("household_weight", "household", "weight", (1.25,)),
        *[
            (name, "person", "USD/year", (64.0, 32.0))
            for name in PRE_RESPONSE_INPUTS.values()
        ],
    ]:
        specs[name] = InputSpec(entity, "year", "float64", unit)
        arrays[name] = {"2017": values}
    for name in TAKEUP_INPUTS:
        entity = (
            "spm_unit"
            if any(x in name for x in ("tanf", "snap", "housing"))
            else "tax_unit"
            if name in {"takes_up_eitc", "takes_up_aca_if_eligible"}
            else "person"
        )
        specs[name] = InputSpec(entity, "year", "bool", "flag")
        arrays[name] = {"2017": (True,) * counts[entity]}
    plan = SimpleNamespace(
        specs=specs,
        arrays=arrays,
        entity_counts=counts,
        law_year=2017,
        reference_year=2025,
        source_sha256="a" * 64,
        contract_sha256="c" * 64,
    )
    base = FakeSim()
    base.populations = populations
    base.data = {}
    for name, periods in arrays.items():
        if name.endswith("_role"):
            continue
        for period, values in periods.items():
            dtype = np.float32 if specs[name].dtype == "float64" else specs[name].dtype
            base.data[(name, period)] = np.array(values, dtype=dtype)
    base.data[(PERSON_FLAG, "2017")] = np.array([True, False])
    base._user_input_keys = {(name, "default", period) for name, period in base.data}
    base.person = SimpleNamespace()
    selected = MicroSeries([True, False], weights=[2, 5])
    observer = NativeObservers(
        {"native_raise": amount, "source_sha256": "a" * 64},
        contract=SimpleNamespace(entity_counts=counts),
        specs=specs,
        registry={},
        tools=SimpleNamespace(
            create_branch=create_branch, split_raise=earnings_increments
        ),
        core_methods={
            name: getattr(FakeSim, name)
            for name in ("_get_set_input_periods", "_get_recorded_input_array")
        },
        holder_to_array=FakeHolder._to_array,
        mode="synthetic_test",
    )
    observer.bind_native(plan)
    observer.snapshot_pilot(base, selected)
    branch = deepcopy(base)
    target = (PRE_RESPONSE_INPUTS["employment_income"], "2017")
    branch.data[target] = branch.get_holder(target[0])._to_array(
        base.data[target] + np.array([amount, 0.0]), validate_nan=True
    )
    return observer, base, branch, selected


def test_exact_selected_raw_raise_preserves_weighted_selector_and_all_fixed_inputs(
    monkeypatch,
):
    def forbidden_tolist(self):
        raise AssertionError("Never strip a weighted selection series")

    monkeypatch.setattr(MicroSeries, "tolist", forbidden_tolist)
    observer, base, branch, selected = specimen()
    assert observer.audit_facts(base, branch, selected) is True
    assert observer.precision_report["status"] == "EXACT"
    assert observer.precision_report["max_native_earnings_error"] == 0
    assert observer.audit_facts(base, None, selected) is True
    assert selected.weights.tolist() == [2, 5]


@pytest.mark.parametrize(
    "defect", ["weight", "topology", "unselected", "wrong_target", "override"]
)
def test_unintended_branch_changes_refuse_without_policy_or_statistics(defect):
    observer, base, branch, selected = specimen()
    if defect == "weight":
        branch.data[("household_weight", "2017")][0] = 2
    elif defect == "topology":
        branch.populations["person"].ids[:] = [34, 21]
    elif defect == "unselected":
        branch.data[(PRE_RESPONSE_INPUTS["employment_income"], "2017")][1] += 1
    elif defect == "wrong_target":
        branch.data[(PRE_RESPONSE_INPUTS["employment_income"], "2017")][0] += 1
    else:
        branch.data[("unlisted_tax_override", "2017")] = np.array([1.0])
        branch._user_input_keys.add(("unlisted_tax_override", "default", "2017"))
    with pytest.raises(ObservationError):
        observer.audit_facts(base, branch, selected)


def test_actual_float32_cast_residual_reports_refusal_and_never_adopts_ulp_tolerance():
    observer, base, branch, selected = specimen(amount=1 / 7)
    assert observer.audit_facts(base, branch, selected) is True
    report = observer.precision_report
    assert report["status"] == "precision_refused"
    assert (
        0
        < report["max_native_earnings_error"]
        <= report["max_derived_cast_ulp_bound_native"]
    )
    assert report["zero_tolerance"] is True
    assert report["bound_applied_to_cutoffs_or_tolerance"] is False


def test_baseline_drift_and_provenance_method_replacement_cannot_be_hidden():
    observer, base, branch, selected = specimen()
    base.data[("age", "2017")][0] += 1
    with pytest.raises(ObservationError, match="Baseline"):
        observer.audit_facts(base, branch, selected)
    observer, base, branch, selected = specimen()
    branch._get_recorded_input_array = lambda *args: np.array([True])
    with pytest.raises(ObservationError, match="method changed"):
        observer.audit_facts(base, branch, selected)


@dataclass
class FakeAccount:
    health_price_anchor_sha256: str = "a" * 64
    components: tuple = ("synthetic",)


def test_bindings_hash_actual_materialized_decisions_and_artifact_not_fake_values():
    observer, _, _, _ = specimen()
    arguments = (
        {"receipt_sha256": "c" * 64},
        FakeAccount(),
        SimpleNamespace(
            receipt={
                "sha256": "b" * 64,
                "source_sha256": observer.plan.source_sha256,
                "contract_sha256": observer.plan.contract_sha256,
                "decoded_input_sha256": input_digest(observer.plan.arrays),
            }
        ),
        {"raise_real": 1000},
    )
    first = observer.bindings(*arguments)
    assert len(first) == 7 and first["baseline_sha256"] == "b" * 64
    name = next(iter(TAKEUP_INPUTS))
    observer.plan.arrays[name]["2017"] = (False,) * len(
        observer.plan.arrays[name]["2017"]
    )
    with pytest.raises(ObservationError, match="correspondence differs"):
        observer.bindings(*arguments)
    arguments[2].receipt.update(
        sha256="d" * 64, decoded_input_sha256=input_digest(observer.plan.arrays)
    )
    second = observer.bindings(*arguments)
    assert first["takeup_draws_sha256"] != second["takeup_draws_sha256"]
    receipt = observer.aggregate_receipt()
    assert receipt["raw_records_or_IDs_returned"] is False
    assert "stored participation decisions" in receipt["takeup_binding_meaning"]


def test_runtime_observer_reads_metadata_and_sources_then_detects_drift(tmp_path):
    observer, _, _, _ = specimen()
    packages, distributions = [], {}
    for name in (
        "policyengine",
        "policyengine-us",
        "policyengine-core",
        "spm-calculator",
    ):
        root = tmp_path / (name + ".dist-info")
        root.mkdir()
        (root / "METADATA").write_text("Name: " + name + "\nVersion: SYNTHETIC\n")
        direct = {"vcs_info": {"commit_id": "a" * 40}}
        (root / "direct_url.json").write_text(json.dumps(direct))
        distributions[name] = SimpleNamespace(
            _path=root,
            metadata={"Name": name},
            version="SYNTHETIC",
            locate_file=lambda relative: tmp_path / relative,
        )
        packages.append(
            {
                "name": name,
                "version": "SYNTHETIC",
                "metadata_sha256": _sha(root / "METADATA"),
                "direct_url": direct,
            }
        )
    source = tmp_path / "source.py"
    source.write_text("# synthetic software source\n")
    observer.config.update(
        {
            "runtime_identity": {
                "packages": sorted(packages, key=lambda p: p["name"]),
                "pins": {"country_commit": "a" * 40},
                "python": sys.version,
                "executable_sha256": _sha(Path(sys.executable).resolve()),
            },
            "source_hashes": {"source.py": _sha(source)},
        }
    )
    observer.metadata = SimpleNamespace(
        distributions=lambda: distributions.values(),
        distribution=lambda name: distributions[name],
        version=lambda name: "SYNTHETIC",
    )
    first = observer.observe_runtime()
    assert first.country_commit == "a" * 40
    source.write_text("# changed synthetic source\n")
    with pytest.raises(ObservationError, match="source bytes differ"):
        observer.observe_runtime()


def test_reference_observer_records_actual_default2024_without_resetting_clock():
    observer, base, _, _ = specimen()
    base.dataset = SimpleNamespace(years=[2024, 2025], time_period=2024)
    base.default_calculation_period = base.default_input_period = 2024
    base.input_variables = {name for name, _ in base.data}
    variables = {
        name: SimpleNamespace(
            entity=SimpleNamespace(key=spec.entity),
            definition_period=spec.period,
            is_input_variable=lambda: True,
        )
        for name, spec in observer.specs.items()
    }
    base.tax_benefit_system = SimpleNamespace(
        variables=variables,
        group_entities=[
            SimpleNamespace(
                key=entity, flattened_roles=[SimpleNamespace(key="member", max=None)]
            )
            for entity in ENTITIES - {"person"}
        ],
    )
    observer.registry = {
        name: SimpleNamespace(
            role="structural"
            if name.endswith("_id") or name.endswith("_role")
            else "raw",
            source_evidence_sha256="a" * 64,
        )
        for name in observer.specs
    }
    observer.observe_runtime = lambda: SimpleNamespace(source_receipt_sha256="b" * 64)
    actual = observer.observe_reference(base)
    assert actual == observer.expected_reference_context
    assert base.default_calculation_period == base.default_input_period == 2024
    assert (
        observer.aggregate_receipt()["reference"]["default_calculation_period"]
        == "2024"
    )
    assert set(observer.role_keys) == ENTITIES - {"person"}


@dataclass(frozen=True)
class Year:
    number: int
    unit: str = "year"
    size: int = 1

    @property
    def start(self):
        return self.number

    def __str__(self):
        return str(self.number)


def year(value):
    return value if isinstance(value, Year) else Year(int(value))


class MemoryStorage:
    """Only supplied, nonderived memory slots; no data or formula cache."""

    def __init__(self):
        self._arrays = {}

    def has(self, period, branch):
        return f"{branch}:{period}" in self._arrays

    def get(self, period, branch):
        return self._arrays.get(f"{branch}:{period}")

    def is_derived(self, period, branch):
        return False

    def get_known_branch_periods(self):
        return [
            (key.rsplit(":", 1)[0], year(key.rsplit(":", 1)[1])) for key in self._arrays
        ]

    def _unmark_dropped_keys(self):
        pass

    _stop_sharing_dropped_keys = _forget_dropped_numbers = _unmark_dropped_keys


class SourceHolder:
    def __init__(self, sim, name):
        self.simulation = sim
        self.variable = SimpleNamespace(name=name)
        self._memory_storage, self._disk_storage = MemoryStorage(), None

    def _storage_period(self, period):
        return year(period)

    def _stores_user_input(self, period, branch, tier=None):
        return (
            self._memory_storage.has(period, branch)
            and (self.variable.name, branch, year(period))
            in self.simulation._user_input_keys
        )

    def _evict_fast_cache(self, period, branch):
        pass


def genuine_ssa_source_fixture():
    """Execute pinned source functions over memory stores, not a country import.

    The fixture has no derived caches. Its cache-purge dependency therefore does
    nothing; routing, exact deletion, source-view and provenance code are genuine.
    """
    directory = Path(__file__).parent / "fixtures"
    ssa = directory / "ssa-inputs.source.txt"
    core = directory / "core-simulation.source.txt"
    assert (
        _sha(ssa) == "f794e9ff0061fd2dedd37df64067e8d12f92fcb3c33264e8fa9b4a2da8ed8107"
    )
    module = ModuleType("cliffs_ssa_source_fixture")
    sys.modules[module.__name__] = module
    namespace = module.__dict__
    namespace.update(
        dataclass=dataclass,
        wraps=wraps,
        List=list,
        Period=Year,
        to_period=year,
        SOCIAL_SECURITY_COMPONENTS=tuple(sorted(SOCIAL_SECURITY_SOURCES)),
        _REPORTED_COMPONENTS=tuple(
            name + "_reported" for name in sorted(SOCIAL_SECURITY_SOURCES)
        ),
        _SOURCE_BRANCH="__social_security_source__",
        _reported_request=ContextVar("synthetic_ssa_request", default=None),
        _purge_derived_arrays=lambda *args: 0,
    )
    tree = ast.parse(core.read_text())
    cls = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Simulation"
    )
    originals = [
        deepcopy(node)
        for node in cls.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_get_set_input_periods", "_get_recorded_input_array"}
    ]
    exec(
        compile(ast.Module(body=originals, type_ignores=[]), str(core), "exec"),
        namespace,
    )
    physical = {
        "recorded_periods": namespace["_get_set_input_periods"],
        "recorded_array": namespace["_get_recorded_input_array"],
    }

    def store(holder, period, array, branch, *, is_input):
        holder._memory_storage._arrays[f"{branch}:{period}"] = array.copy()
        if is_input:
            holder.simulation._user_input_keys.add(
                (holder.variable.name, branch, year(period))
            )

    physical["set"] = store
    namespace["_PHYSICAL"] = physical
    tree = ast.parse(ssa.read_text())
    selected = {
        "_Value",
        "_enabled",
        "_holder",
        "_branches",
        "_source_branches",
        "_physical_periods",
        "_physical_value",
        "_explicit_periods",
        "_public_periods",
        "_explicit_before",
        "_allow_fallback",
        "_effective_value",
        "_delete_exact",
        "_store_source",
        "_refresh_input_variables",
        "migrate_social_security_inputs",
    }
    bodies = [
        deepcopy(node)
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in selected
    ]
    install = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "install_social_security_input_compatibility"
    )
    bodies += [
        deepcopy(node)
        for node in install.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"recorded_periods", "recorded_array"}
    ]
    exec(compile(ast.Module(body=bodies, type_ignores=[]), str(ssa), "exec"), namespace)

    class Migrated:
        branch_name = "default"
        _get_set_input_periods = namespace["recorded_periods"]
        _get_recorded_input_array = namespace["recorded_array"]

        def __init__(self):
            self._user_input_keys = set()
            self.persons = SimpleNamespace(_holders={})
            self.tax_benefit_system = SimpleNamespace(
                _social_security_input_compatibility=True
            )
            self.input_variables = []

        def _get_visible_branch_names(self):
            return ["default"]

        def get_holder(self, name):
            return self.persons._holders[name]

    sim = Migrated()
    for index, name in enumerate(sorted(SOCIAL_SECURITY_SOURCES)):
        for key in (name, name + "_reported"):
            sim.persons._holders[key] = SourceHolder(sim, key)
        store(
            sim.get_holder(name),
            Year(2017),
            np.array([index + 10, index + 20], dtype=np.float32),
            "default",
            is_input=True,
        )
    namespace["migrate_social_security_inputs"](sim, include_baseline=False)
    return sim, namespace, ssa, core


def test_genuine_country_ssa_migration_and_wrapped_raw_view_preserve_only_source_inputs():
    sim, namespace, ssa, core = genuine_ssa_source_fixture()
    observer, _, _, _ = specimen()
    observer.core_methods = {
        name: getattr(type(sim), name)
        for name in ("_get_set_input_periods", "_get_recorded_input_array")
    }
    try:
        for name in sorted(SOCIAL_SECURITY_SOURCES):
            assert sim._get_set_input_periods(name) == []  # no final benefit override
            assert [
                str(period) for period in sim._get_set_input_periods(name + "_reported")
            ] == ["2017"]
            assert (
                sim.get_holder(name)._memory_storage.get(Year(2017), "default") is None
            )
            hidden = sim.get_holder(name)._memory_storage.get(
                Year(2017), "__social_security_source__default"
            )
            assert np.array_equal(observer._raw(sim, name, "2017"), hidden)
        for method in observer.core_methods.values():
            assert _source_chain(method) == [_sha(ssa), _sha(core)]
    finally:
        sys.modules.pop(namespace["__name__"], None)
