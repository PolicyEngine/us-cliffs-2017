"""Synthetic input transport only; no model, dataset file or policy outcomes."""

from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import pytest

from cliffs2017.government_transfer_account import CASH_VARIABLE, GOVERNMENT_VARIABLE
from cliffs2017.managed_native import ENTITIES, InputSpec, role_transport_from_entities
from cliffs2017.native_currency import (
    Disposition,
    FieldSpec,
    InputContract,
    Kind,
    PriceBasis,
)
from cliffs2017.native_materializer import (
    FROZEN_IRMAA_STRATEGY,
    IRMAA_INPUT,
    InputRule,
    MaterializationError,
    compile_native_plan,
    freeze_baseline_irmaa,
    prepare_reference_once,
    topology_inputs,
    verify_frozen_irmaa,
    write_native_dataset,
)
from cliffs2017.reference_benchmark_prices import FORBIDDEN_STORED_PRICE_INPUTS

SHA = "a" * 64
CONTEXT = {
    name: SHA
    for name in ("source_sha256", "runtime_identity_sha256", "source_inventory_sha256")
}


def specimen():
    fields, values, populations = [], {}, {}

    def field(name, entity, kind, unit, period, value, disposition=Disposition.KEEP):
        fields.append(FieldSpec(name, entity, kind, disposition, unit, period))
        values[name] = value

    for index, entity in enumerate(sorted(ENTITIES)):
        ids = (21, 34) if entity == "person" else (100 + index,)
        field(f"{entity}_id", entity, Kind.ID, "id", "eternity", ids)
        pop = SimpleNamespace(ids=ids, count=len(ids))
        if entity != "person":
            role = SimpleNamespace(key="member", max=None)
            pop.entity = SimpleNamespace(key=entity, flattened_roles=[role])
            pop._members_role = (role, role)
            pop.members_role = (role, role)
            pop.members_entity_id = (0, 0)
            field(
                f"person_{entity}_id",
                "person",
                Kind.STRUCTURE,
                "id",
                "eternity",
                ids * 2,
            )
            field(
                f"person_{entity}_role",
                "person",
                Kind.DEMOGRAPHIC,
                "category",
                "eternity",
                ("member", "member"),
            )
        populations[entity] = pop
    field("age", "person", Kind.AGE, "age_years", "year", (40.5, 7))
    field("household_weight", "household", Kind.WEIGHT, "weight", "year", (1.25,))
    field(
        "origination_date",
        "household",
        Kind.CALENDAR,
        "calendar_date",
        "year",
        ("2003-02-01",),
    )
    field(
        "monthly_status",
        "person",
        Kind.DEMOGRAPHIC,
        "flag",
        "month",
        {m: (m % 2 == 0, False) for m in range(1, 13)},
    )
    field(
        "earnings",
        "person",
        Kind.PRIMITIVE_MONEY,
        "USD/year",
        "year",
        (1000, Fraction(1, 7)),
        Disposition.SCALE,
    )
    field(
        "monthly_money",
        "person",
        Kind.PRIMITIVE_MONEY,
        "USD/month",
        "month",
        {m: (Fraction(m, 7), 0) for m in range(1, 13)},
        Disposition.SCALE,
    )
    field(
        "stored_policy_result",
        "household",
        Kind.POLICY_DERIVED,
        "USD/year",
        "year",
        (999,),
        Disposition.DROP,
    )
    counts = {name: population.count for name, population in populations.items()}
    contract = InputContract(tuple(fields), counts)
    registry, variables, specs = {}, {}, {}
    structural = {f.name for f in fields if f.period == "eternity"}
    for f in fields:
        role = (
            "drop"
            if f.disposition == Disposition.DROP
            else "structural"
            if f.name in structural
            else "raw"
        )
        registry[f.name] = InputRule(role, SHA)
        variables[f.name] = SimpleNamespace(
            entity=SimpleNamespace(key=f.entity),
            definition_period=f.period,
            is_input_variable=lambda: True,
        )
        if role != "drop":
            dtype = (
                "int64"
                if f.unit == "id"
                else "bool"
                if f.unit == "flag"
                else "str"
                if f.unit in {"category", "calendar_date"}
                else "float64"
            )
            specs[f.name] = InputSpec(f.entity, f.period, dtype, f.unit)
    fixed = {
        f.name: values[f.name] for f in fields if f.disposition == Disposition.KEEP
    }
    calls = []
    observed = []

    class Simulation:
        dataset = SimpleNamespace(years=[2024, 2025])
        input_variables = set(values) - {"stored_policy_result"}

        def __init__(self):
            self.populations = deepcopy(populations)

        def calc(self, name, *, period):
            observed.append((name, period))
            value = values[name]
            if isinstance(value, dict):
                return deepcopy(value[int(str(period)[-2:])])
            return deepcopy(value)

    sim = Simulation()
    system = SimpleNamespace(variables=variables)

    def managed(**kwargs):
        calls.append(kwargs)
        return sim

    args = {
        "managed_constructor": managed,
        "system_constructor": lambda **kwargs: system,
        "source_path": "/synthetic-only/source2024.h5",
        "observe_source": lambda path: {"source_year": 2024, "sha256": SHA},
        "spm": {"mode": "synthetic"},
        "registry": registry,
        "contract": contract,
        "archival_inputs": {"stored_policy_result": values["stored_policy_result"]},
        "expected_context": CONTEXT,
        "observe_context": lambda actual: dict(CONTEXT),
    }
    return SimpleNamespace(
        args=args,
        values=values,
        specs=specs,
        fixed=fixed,
        sim=sim,
        system=system,
        calls=calls,
        observed=observed,
        contract=contract,
    )


def plan_from(s):
    values, fixed, receipt = prepare_reference_once(**s.args)
    return compile_native_plan(
        values,
        contract=s.contract,
        basis=PriceBasis({2017: 4, 2025: 5}),
        specs=s.specs,
        fixed_facts=fixed,
        reference_receipt=receipt,
        contract_sha256=SHA,
        role_keys={entity: {"member"} for entity in ENTITIES - {"person"}},
        required_history=(),
    )


def test_one_managed_preparation_preserves_fixed_source_and_ignores_derived_cache():
    s = specimen()
    original = deepcopy(s.values)
    values, fixed, receipt = prepare_reference_once(**s.args)
    assert len(s.calls) == 1
    assert s.calls[0]["dataset_end_year"] == 2025
    assert s.calls[0]["start_instant"] == "2025-01-01"
    assert s.calls[0]["dataset"] == "/synthetic-only/source2024.h5"
    assert s.calls[0]["allow_unmanaged"] is True
    assert not any(name == "stored_policy_result" for name, period in s.observed)
    assert len([1 for name, period in s.observed if name == "monthly_money"]) == 12
    assert receipt["projections"] == 1
    assert values == original == s.values
    assert fixed == s.fixed


def test_formula_output_and_absent_raw_input_refuse_before_calculation():
    for defect in ("formula", "missing"):
        s = specimen()
        if defect == "formula":
            s.system.variables["earnings"].is_input_variable = lambda: False
        else:
            s.sim.input_variables.remove("earnings")
        with pytest.raises(MaterializationError, match="Stored formula"):
            prepare_reference_once(**s.args)
        assert not any(name == "earnings" for name, period in s.observed)


@pytest.mark.parametrize("name", ["age", "household_weight", "origination_date"])
def test_capture_once_prepared_facts_then_refuse_restoring_source2024_facts(name):
    s = specimen()
    s.values[name] = (
        (41.5, 8)
        if name == "age"
        else (1.5,)
        if name == "household_weight"
        else ("2004-02-01",)
    )
    values, fixed, receipt = prepare_reference_once(**s.args)
    assert fixed[name] == s.values[name] != s.fixed[name]
    assert len(s.calls) == 1
    with pytest.raises(MaterializationError, match="Fixed facts differ"):
        compile_native_plan(
            values,
            contract=s.contract,
            basis=PriceBasis({2017: 4, 2025: 5}),
            specs=s.specs,
            fixed_facts=s.fixed,
            reference_receipt=receipt,
            contract_sha256=SHA,
            required_history=(),
            role_keys={entity: {"member"} for entity in ENTITIES - {"person"}},
        )


def test_observed_context_must_remain_current_through_collection():
    s = specimen()
    calls = []

    def observe(sim):
        calls.append(sim)
        return (
            dict(CONTEXT) if len(calls) == 1 else {**CONTEXT, "source_sha256": "b" * 64}
        )

    s.args["observe_context"] = observe
    with pytest.raises(MaterializationError, match="live source context"):
        prepare_reference_once(**s.args)


def test_missing_actual_roles_cannot_be_filled_with_default_role():
    s = specimen()
    s.sim.populations["tax_unit"]._members_role = None
    with pytest.raises(MaterializationError, match="Observed flattened"):
        topology_inputs(s.sim)


def test_compiler_uses_exact_currency_and_keeps_twelve_nonuniform_months():
    s = specimen()
    plan = plan_from(s)
    assert plan.arrays["earnings"]["2017"] == (800.0, float(Fraction(4, 35)))
    assert set(plan.arrays["monthly_money"]) == {f"2017-{m:02d}" for m in range(1, 13)}
    assert plan.arrays["monthly_money"]["2017-12"] == (float(Fraction(48, 35)), 0.0)
    assert plan.arrays["origination_date"]["2017"] == ("2003-02-01",)
    assert plan.arrays["household_weight"]["2017"] == (1.25,)
    assert "stored_policy_result" not in plan.arrays
    assert plan.native_price_factor == Fraction(4, 5)


def test_stale_preparation_receipt_and_unselected_history_refuse():
    s = specimen()
    values, fixed, receipt = prepare_reference_once(**s.args)
    options = {
        "contract": s.contract,
        "basis": PriceBasis({2017: 4, 2025: 5}),
        "specs": s.specs,
        "fixed_facts": fixed,
        "reference_receipt": receipt,
        "contract_sha256": SHA,
        "role_keys": {entity: {"member"} for entity in ENTITIES - {"person"}},
        "required_history": (),
    }
    with pytest.raises(MaterializationError, match="history remains closed"):
        compile_native_plan(values, **{**options, "required_history": ("IRMAA2015",)})
    options["reference_receipt"] = {**receipt, "projections": 2}
    with pytest.raises(MaterializationError, match="receipt changed"):
        compile_native_plan(values, **options)


class MemoryFiles:
    def __init__(self):
        self.claims = set()

    def claim(self, path):
        if path in self.claims:
            raise MaterializationError("Synthetic path already owned")
        self.claims.add(path)
        return path

    def owns(self, path, token):
        return path == token and path in self.claims

    def digest(self, path):
        assert path in self.claims
        return "b" * 64


class Vector:
    def __init__(self, values):
        self.values = tuple(values)
        kind, size = (
            ("b", 1)
            if type(values[0]) is bool
            else ("i", 8)
            if type(values[0]) is int
            else ("f", 8)
            if type(values[0]) is float
            else ("O", 8)
        )
        self.dtype = SimpleNamespace(kind=kind, itemsize=size)
        self.shape = (len(values),)

    def tolist(self):
        # HDF vlen UTF8 reads back bytes; exercise actual normalization explicitly.
        return [v.encode() if type(v) is str else v for v in self.values]


class MemoryDataset:
    TIME_PERIOD_ARRAYS = "time_period_arrays"
    defect = None

    def __init__(self, *, require):
        assert require is False

    def save_dataset(self, data):
        self.data = deepcopy(data)
        if self.defect == "leaky_error":
            raise ValueError("SECRET_POPULATION_VECTOR [12345, 67890]")

    def load_dataset(self):
        result = {
            name: {period: Vector(vector) for period, vector in periods.items()}
            for name, periods in self.data.items()
        }
        if self.defect == "float32":
            result["earnings"]["2017"].dtype.itemsize = 4
        elif self.defect == "missing_month":
            del result["monthly_money"]["2017-02"]
        elif self.defect == "changed_value":
            result["age"]["2017"] = Vector([99.0, 99.0])
        return result


def synthetic_role_transport():
    return role_transport_from_entities(
        [
            SimpleNamespace(
                key=entity, flattened_roles=[SimpleNamespace(key="member", max=None)]
            )
            for entity in ENTITIES - {"person"}
        ]
    )


def write(plan, **kwargs):
    return write_native_dataset(
        plan,
        Path("/synthetic-only/native.h5"),
        serializer_source_sha256=SHA,
        role_transport=synthetic_role_transport(),
        dataset_type=MemoryDataset,
        files=MemoryFiles(),
        mode="synthetic_test",
        **kwargs,
    )


def test_core_writer_protocol_returns_descriptor_with_authoritative_clock_and_all_types():
    plan = plan_from(specimen())
    # This synthetic writer fixture puts a history subgroup before current inputs.
    # It does not admit any historical income to the compiler or the real study.
    arrays = {"aaa_history": {"2015": (123.0,)}, **plan.arrays}
    specs = {
        "aaa_history": InputSpec("tax_unit", "year", "float64", "USD/year"),
        **plan.specs,
    }
    result = write(replace(plan, arrays=arrays, specs=specs))
    assert result.dataset.time_period == "2017"
    assert result.dataset.data["aaa_history"]["2015"] == [123.0]
    assert result.receipt["descriptor_time_period"] == "2017"
    assert (
        result.receipt["observed_transport_types"]["earnings"]["2017"]["itemsize"] == 8
    )
    assert result.receipt["status"] == "SYNTHETIC_SERIALIZER_DOUBLE_NOT_A_DATASET"
    assert result.receipt["certification"] == "not_attested"


@pytest.mark.parametrize(
    "defect", ["float32", "missing_month", "changed_value", "leaky_error"]
)
def test_serializer_failure_preserves_claim_and_never_emits_input_vectors(defect):
    plan = plan_from(specimen())
    files = MemoryFiles()
    broken = type("BrokenMemoryDataset", (MemoryDataset,), {"defect": defect})
    with pytest.raises(MaterializationError) as caught:
        write_native_dataset(
            plan,
            Path("/synthetic-only/native.h5"),
            serializer_source_sha256=SHA,
            role_transport=synthetic_role_transport(),
            dataset_type=broken,
            files=files,
            mode="synthetic_test",
        )
    assert files.claims == {Path("/synthetic-only/native.h5")}
    assert "SECRET_POPULATION_VECTOR" not in str(caught.value)
    assert "12345" not in str(caught.value)
    assert caught.value.__suppress_context__ is True


def test_existing_artifact_and_relative_path_refuse_without_overwriting():
    plan = plan_from(specimen())
    files = MemoryFiles()
    options = {
        "serializer_source_sha256": SHA,
        "role_transport": synthetic_role_transport(),
        "dataset_type": MemoryDataset,
        "files": files,
        "mode": "synthetic_test",
    }
    with pytest.raises(MaterializationError, match="absolute"):
        write_native_dataset(plan, "relative.h5", **options)
    assert files.claims == set()
    write_native_dataset(plan, "/synthetic-only/native.h5", **options)
    with pytest.raises(MaterializationError, match="already owned"):
        write_native_dataset(plan, "/synthetic-only/native.h5", **options)


def test_synthetic_dataset_cannot_claim_native_serializer_identity():
    with pytest.raises(MaterializationError, match="authenticated maintained Core"):
        write_native_dataset(
            plan_from(specimen()),
            "/synthetic-only/native.h5",
            serializer_source_sha256=SHA,
            role_transport=synthetic_role_transport(),
            dataset_type=MemoryDataset,
            files=MemoryFiles(),
        )


class SyntheticSeries:
    def __init__(self, values):
        self.values = list(values)

    def tolist(self):
        return list(self.values)

    def copy(self):
        return SyntheticSeries(self.values)


class SyntheticIrmaaSimulation:
    def __init__(self):
        self.default_calculation_period = "2017"
        self.branches = {}
        self.inputs = {}
        self.imputations = 0
        self.current_income = 40000.0
        self.populations = {"tax_unit": SimpleNamespace(count=2)}
        self.mode = False
        self.tax_benefit_system = SimpleNamespace(
            variables={
                IRMAA_INPUT: SimpleNamespace(
                    entity=SimpleNamespace(key="tax_unit"), definition_period="year"
                )
            },
            parameters=lambda year: SimpleNamespace(
                gov=SimpleNamespace(
                    simulation=SimpleNamespace(
                        medicare_irmaa_uses_current_year_income=self.mode
                    )
                )
            ),
        )

    def _get_set_input_periods(self, name):
        return ["2017"] if name in self.inputs else []

    def calc(self, name, *, period, map_to):
        assert name == IRMAA_INPUT and period == 2017 and map_to == "tax_unit"
        if name in self.inputs:
            return SyntheticSeries(self.inputs[name])
        self.imputations += 1
        return SyntheticSeries([self.current_income, 15000.0])

    def set_input(self, name, period, vector):
        assert name == IRMAA_INPUT and period == 2017
        assert isinstance(vector, SyntheticSeries)
        self.inputs[name] = vector.tolist()


def test_frozen_model_imputed_prior_magi_is_not_recomputed_after_earnings_shock():
    sim = SyntheticIrmaaSimulation()
    sim.branches["baseline"] = SyntheticIrmaaSimulation()
    context = {"source": SHA}
    args = {
        "expected_context": context,
        "observe_context": lambda actual: dict(context),
    }
    receipt = freeze_baseline_irmaa(sim, **args)
    assert sim.imputations == 1
    assert receipt["strategy"] == FROZEN_IRMAA_STRATEGY
    assert "not observed" in receipt["provenance"]
    assert sim.branches["baseline"].inputs == sim.inputs
    branch = SyntheticIrmaaSimulation()
    branch.inputs = deepcopy(sim.inputs)
    branch.current_income = 90000.0
    verify_frozen_irmaa(branch, receipt, **args)
    assert branch.imputations == 0
    branch.inputs[IRMAA_INPUT][0] += 1
    with pytest.raises(MaterializationError, match="Prior MAGI changed"):
        verify_frozen_irmaa(branch, receipt, **args)


@pytest.mark.parametrize(
    "defect",
    [
        "wrong_clock",
        "existing_perturbation",
        "current_income_mode",
        "existing_override",
    ],
)
def test_prior_income_freeze_refuses_incompatible_existing_state(defect):
    sim = SyntheticIrmaaSimulation()
    if defect == "wrong_clock":
        sim.default_calculation_period = "2015"
    elif defect == "existing_perturbation":
        sim.branches["raise"] = object()
    elif defect == "current_income_mode":
        sim.mode = True
    else:
        sim.inputs[IRMAA_INPUT] = [1.0, 2.0]
    with pytest.raises(MaterializationError):
        freeze_baseline_irmaa(
            sim,
            expected_context={"source": SHA},
            observe_context=lambda actual: {"source": SHA},
        )
    assert sim.imputations == 0


def test_computed_cache_with_equal_value_is_not_supplied_prior_income_proof():
    sim = SyntheticIrmaaSimulation()
    args = {
        "expected_context": {"source": SHA},
        "observe_context": lambda actual: {"source": SHA},
    }
    receipt = freeze_baseline_irmaa(sim, **args)
    sim.inputs.clear()
    with pytest.raises(MaterializationError, match="explicit2017 input"):
        verify_frozen_irmaa(sim, receipt, **args)
    assert sim.imputations == 1


class SourceColumn:
    def __init__(self, values, dtype):
        self.values, self.dtype = values, dtype

    def tolist(self):
        return list(self.values)


class SourceTable:
    def __init__(self, fields):
        self.fields = fields
        self.columns = tuple(fields)

    def __getitem__(self, name):
        return self.fields[name]


def source_ingress_specimen():
    s = specimen()
    source = {}
    additions = []
    names = (
        "social_security_retirement",
        "social_security_disability",
        "social_security_survivors",
        "social_security_dependents",
        "is_spm_independent_minor_role",
    )
    for name in names:
        role = name == "is_spm_independent_minor_role"
        period, dtype = ("eternity", "bool") if role else ("year", "float64")
        field = FieldSpec(
            name,
            "person",
            Kind.DEMOGRAPHIC if role else Kind.PRIMITIVE_MONEY,
            Disposition.KEEP if role else Disposition.SCALE,
            "flag" if role else "USD/year",
            period,
        )
        additions.append(field)
        source[name] = SourceColumn((False, True) if role else (127.5, 0.0), dtype)
        s.args["registry"][name] = InputRule("prepared_source", SHA, dtype)
        s.system.variables[name] = SimpleNamespace(
            entity=SimpleNamespace(key="person"),
            definition_period=period,
            is_input_variable=lambda: False,
        )
    s.args["contract"] = InputContract(
        (*s.contract.fields, *additions), s.contract.entity_counts
    )
    single = SimpleNamespace(time_period="2025", person=SourceTable(source))
    s.sim.dataset = SimpleNamespace(
        years=[2024, 2025], get_year=lambda year: single if year == 2025 else None
    )
    return s, source


def test_five_named_ingress_fields_use_prepared_source_not_computed_formulas():
    s, source = source_ingress_specimen()
    values, fixed, receipt = prepare_reference_once(**s.args)
    assert set(receipt["prepared_source_ingress"]) == set(source)
    for name, column in source.items():
        assert values[name] == tuple(column.values)
        assert not any(observed_name == name for observed_name, period in s.observed)
    assert fixed["is_spm_independent_minor_role"] == (False, True)
    assert "social_security_retirement" not in fixed


def test_named_source_ingress_refuses_changed_dtype_and_arbitrary_formula_name():
    s, source = source_ingress_specimen()
    source["social_security_retirement"].dtype = "float32"
    with pytest.raises(MaterializationError, match="dtype changed"):
        prepare_reference_once(**s.args)
    s, source = source_ingress_specimen()
    s.args["registry"]["earnings"] = InputRule("prepared_source", SHA, "float64")
    with pytest.raises(MaterializationError, match="Only the five"):
        prepare_reference_once(**s.args)


@pytest.mark.parametrize(
    "name", [CASH_VARIABLE, GOVERNMENT_VARIABLE, *sorted(FORBIDDEN_STORED_PRICE_INPUTS)]
)
def test_public_account_and_price_inputs_cannot_mask_formula_reforms(name):
    s = specimen()
    field = FieldSpec(
        name, "household", Kind.PRIMITIVE_MONEY, Disposition.SCALE, "USD/year", "year"
    )
    s.args["contract"] = InputContract(
        (*s.contract.fields, field), s.contract.entity_counts
    )
    s.args["registry"][name] = InputRule("raw", SHA)
    with pytest.raises(MaterializationError, match="Stored price inputs"):
        prepare_reference_once(**s.args)


def test_reference_capture_receives_same_full_sim_once_before_input_collection():
    s = specimen()
    captured = []

    def capture(actual):
        assert actual is s.sim
        assert actual.dataset.years == [2024, 2025]
        assert {
            name: population.count for name, population in actual.populations.items()
        } == dict(s.contract.entity_counts)
        assert s.observed == []
        captured.append(actual)

    result = prepare_reference_once(**s.args, capture_reference=capture)
    assert len(result) == 3 and captured == [s.sim] and len(s.calls) == 1
    other = specimen()
    other.args["contract"] = InputContract(
        other.contract.fields, {**other.contract.entity_counts, "person": 3}
    )
    with pytest.raises(MaterializationError, match="closed source cohort"):
        prepare_reference_once(
            **other.args, capture_reference=lambda actual: captured.append(actual)
        )
    assert captured == [s.sim]


def test_reference_capture_failure_propagates_without_collecting_or_reprojecting():
    s = specimen()
    before = deepcopy(s.values)
    failure = RuntimeError("synthetic reference capture refused")
    captured = []

    def capture(actual):
        assert actual is s.sim
        captured.append(actual)
        raise failure

    with pytest.raises(RuntimeError) as caught:
        prepare_reference_once(**s.args, capture_reference=capture)
    assert caught.value is failure
    assert captured == [s.sim] and len(s.calls) == 1
    assert s.observed == [] and s.values == before
