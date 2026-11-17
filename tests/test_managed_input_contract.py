"""Source-schema and tiny transport checks; no model or population data."""

from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from cliffs2017.managed_input_contract import build_managed_input_contract
from cliffs2017.managed_native import (
    ENTITIES,
    NativeEngineError,
    RuntimeBinding,
    _value,
    construct_managed_native,
)
from cliffs2017.native_currency import (
    ContractError,
    FieldSpec,
    InputContract,
    PriceBasis,
    to_native_inputs,
)
from cliffs2017.native_materializer import (
    FROZEN_IRMAA_STRATEGY,
    MaterializationError,
    compile_native_plan,
    prepare_reference_once,
    write_native_dataset,
)


ROOT = Path(__file__).resolve().parents[1]
DECLARATION = json.loads(
    (ROOT / "cliffs2017/managed57k_input_contract.json").read_text()
)
METADATA = json.loads(
    (ROOT / "tests/fixtures/native_input_metadata_187.json").read_text()
)


def test_actual_schema_binds_all_fields_and_the_source_specific_periods():
    contract, specs, registry = build_managed_input_contract(
        DECLARATION, actual_metadata=METADATA
    )
    assert len(contract.fields) == len(specs) == len(registry) == 192
    assert contract.entity_counts["household"] == 57240
    assert contract.entity_counts["person"] == 166321
    assert specs["person_id"].period == specs["family_id"].period == "year"
    assert specs["person_family_role"].period == "eternity"
    assert specs["takes_up_wic_if_eligible"].period == "month"
    assert registry["social_security_retirement"].role == "prepared_source"
    assert registry["is_spm_independent_minor_role"].role == "prepared_source"
    assert specs["business_is_sstb"].unit == "flag"  # source's bool is not money
    assert specs["household_vehicles_value"].unit == "USD/stock"


def test_metadata_period_drift_refuses_instead_of_reusing_structural_eternity():
    metadata = deepcopy(METADATA)
    next(row for row in metadata["records"] if row["name"] == "person_id")[
        "definition_period"
    ] = "eternity"
    with pytest.raises(MaterializationError, match="metadata/source differs"):
        build_managed_input_contract(DECLARATION, actual_metadata=metadata)


def test_physical_source_field_cannot_disappear_from_dispositions():
    declaration = deepcopy(DECLARATION)
    declaration["source_column_dispositions"].pop()
    with pytest.raises(MaterializationError, match="physical source"):
        build_managed_input_contract(declaration, actual_metadata=METADATA)


def test_existing_formula_input_route_cannot_be_reclassified_as_ordinary_raw():
    declaration = deepcopy(DECLARATION)
    next(
        row
        for row in declaration["fields"]
        if row["name"] == "social_security_retirement"
    )["role"] = "raw"
    with pytest.raises(MaterializationError, match="Stored formula outputs"):
        build_managed_input_contract(declaration, actual_metadata=METADATA)


def test_no_additional_prepared_source_formula_exception_is_inferred():
    declaration = deepcopy(DECLARATION)
    next(
        row
        for row in declaration["fields"]
        if row["name"] == "employment_income_before_lsr"
    )["role"] = "prepared_source"
    with pytest.raises(MaterializationError, match="No additional"):
        build_managed_input_contract(declaration, actual_metadata=METADATA)


def test_fractional_hours_and_weeks_stay_fixed_while_only_money_converts():
    fields = (
        FieldSpec(
            "weekly_hours",
            "person",
            "fixed_dimensionless",
            "keep_fact",
            "hours/week",
            "year",
        ),
        FieldSpec(
            "last_week_hours",
            "person",
            "fixed_dimensionless",
            "keep_fact",
            "hours",
            "year",
        ),
        FieldSpec(
            "unemployed_weeks",
            "person",
            "fixed_dimensionless",
            "keep_fact",
            "weeks",
            "year",
        ),
        FieldSpec(
            "money", "person", "primitive_money", "scale_money", "USD/year", "year"
        ),
    )
    inputs = {
        "weekly_hours": (Fraction(71, 2),),
        "last_week_hours": (Fraction(1, 3),),
        "unemployed_weeks": (Fraction(3, 2),),
        "money": (100,),
    }
    result = to_native_inputs(
        inputs,
        contract=InputContract(fields, {"person": 1}),
        basis=PriceBasis({2017: 4, 2025: 5}),
        target_year=2017,
    )
    assert dict(result.values) == {**inputs, "money": (80,)}


def test_supplied_empty_geographic_sentinel_survives_but_category_does_not():
    field = FieldSpec(
        "geography", "household", "fixed_demographic", "keep_fact", "code", "year"
    )
    result = to_native_inputs(
        {"geography": ("",)},
        contract=InputContract((field,), {"household": 1}),
        basis=PriceBasis({2017: 4, 2025: 5}),
        target_year=2017,
    )
    assert result.values["geography"] == ("",)
    assert _value(result.values["geography"][0], "str", "code") == ""
    with pytest.raises(NativeEngineError):
        _value("", "str", "category")


@pytest.mark.parametrize("unit", ["hours", "hours/week", "weeks"])
def test_invalid_work_time_is_not_silently_repaired(unit):
    field = FieldSpec(
        "work_time", "person", "fixed_dimensionless", "keep_fact", unit, "year"
    )
    with pytest.raises(ContractError, match="cannot be negative"):
        to_native_inputs(
            {"work_time": (-1,)},
            contract=InputContract((field,), {"person": 1}),
            basis=PriceBasis({2017: 4, 2025: 5}),
            target_year=2017,
        )


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


def test_complete_192_field_toy_annual_packet_writer_and_constructor_chain():
    # Keep actual variable metadata; explicitly replace only source cohort sizes
    # with two toy persons and one group of each kind. No survey values exist.
    declaration = deepcopy(DECLARATION)
    declaration["entity_counts"] = {
        entity: 2 if entity == "person" else 1 for entity in ENTITIES
    }
    contract, specs, registry = build_managed_input_contract(
        declaration, actual_metadata=METADATA
    )
    inputs, populations = {}, {}
    for index, entity in enumerate(sorted(ENTITIES)):
        ids = (21, 34) if entity == "person" else (100 + index,)
        population = SimpleNamespace(ids=ids, count=len(ids))
        if entity != "person":
            roles = (SimpleNamespace(key="member"), SimpleNamespace(key="member"))
            population._members_role = population.members_role = roles
            population.members_entity_id = (0, 0)
        populations[entity] = population
    for row in declaration["fields"]:
        if row["role"] == "structural":
            continue
        count = contract.entity_counts[row["entity"]]
        if row["dtype"] == "bool":
            value = tuple(False for _ in range(count))
        elif row["dtype"] == "str":
            members = row["metadata_signature"].get("enum_members") or {}
            value = tuple(next(iter(members)) if members else "" for _ in range(count))
        elif row["unit"] == "calendar_year":
            value = tuple(2000 for _ in range(count))
        elif row["dtype"] == "int64":
            value = tuple(1 for _ in range(count))
        else:
            value = tuple(10.0 for _ in range(count))
        inputs[row["name"]] = (
            {
                month: tuple(month % 2 == 0 for _ in range(count))
                for month in range(1, 13)
            }
            if row["period"] == "month"
            else value
        )
    variables = {
        row["name"]: SimpleNamespace(
            entity=SimpleNamespace(key=row["entity"]),
            definition_period=row["period"],
            is_input_variable=lambda: True,
        )
        for row in declaration["fields"]
    }
    reference_system = SimpleNamespace(variables=variables)
    source_columns = {
        row["name"]: SourceColumn(inputs[row["name"]], row["source_dtype"])
        for row in declaration["fields"]
        if row["role"] == "prepared_source"
    }
    prepared_year = SimpleNamespace(
        time_period="2025", person=SourceTable(source_columns)
    )
    reference = SimpleNamespace(
        populations=populations,
        dataset=SimpleNamespace(
            years=[2024, 2025], get_year=lambda year: prepared_year
        ),
        input_variables=set(inputs),
    )
    reads, calls = [], []

    def calc(name, *, period):
        reads.append((name, period))
        value = inputs[name]
        return value[int(str(period)[-2:])] if isinstance(value, dict) else value

    reference.calc = calc
    stamp = "a" * 64
    context = {
        name: stamp
        for name in (
            "source_sha256",
            "runtime_identity_sha256",
            "source_inventory_sha256",
        )
    }
    values, fixed, receipt = prepare_reference_once(
        managed_constructor=lambda **kw: reference,
        system_constructor=lambda **kw: reference_system,
        source_path="/synthetic-only/reference.h5",
        observe_source=lambda path: {"source_year": 2024, "sha256": stamp},
        spm={"SYNTHETIC": "only"},
        registry=registry,
        contract=contract,
        archival_inputs={},
        expected_context=context,
        observe_context=lambda sim: context,
    )
    assert len(reads) > 0 and not any(name in source_columns for name, _ in reads)
    plan = compile_native_plan(
        values,
        contract=contract,
        basis=PriceBasis({2017: 4, 2025: 5}),
        specs=specs,
        fixed_facts=fixed,
        reference_receipt=receipt,
        contract_sha256=stamp,
        role_keys={entity: {"member"} for entity in ENTITIES - {"person"}},
        required_history=(FROZEN_IRMAA_STRATEGY,),
    )
    assert len(plan.arrays) == 192
    assert plan.arrays["person_id"] == {"2017": (21, 34)}
    assert set(plan.arrays["family_id"]) == {"2017"}
    assert set(plan.arrays["person_family_id"]) == {"2017"}
    assert set(plan.arrays["person_family_role"]) == {"eternity"}
    assert len(plan.arrays["takes_up_wic_if_eligible"]) == 12
    assert plan.arrays["takes_up_wic_if_eligible"]["2017-01"] == (False, False)
    assert plan.arrays["takes_up_wic_if_eligible"]["2017-02"] == (True, True)
    assert plan.arrays["block_geoid"]["2017"] == ("",)
    written = write_native_dataset(
        plan,
        Path("/synthetic-only/native.h5"),
        serializer_source_sha256=stamp,
        dataset_type=MemoryDataset,
        files=MemoryFiles(),
        mode="synthetic_test",
    )
    native_system = SimpleNamespace(
        variables=variables,
        group_entities=[
            SimpleNamespace(
                key=entity, flattened_roles=[SimpleNamespace(key="member", max=None)]
            )
            for entity in ENTITIES - {"person"}
        ],
    )
    native = SimpleNamespace(
        dataset=written.dataset,
        default_input_period="2017",
        default_calculation_period="2017",
        calc=lambda *a, **kw: None,
        set_input=lambda *a, **kw: None,
        branches={},
    )
    binding = RuntimeBinding(
        "a" * 40,
        {
            name: "SYNTHETIC"
            for name in (
                "policyengine",
                "policyengine-us",
                "policyengine-core",
                "spm-calculator",
            )
        },
        stamp,
    )
    contexts = {
        name: stamp
        for name in (
            "runtime_identity_sha256",
            "reference_preparation_sha256",
            "health_price_anchor_sha256",
            "price_basis_sha256",
            "component_ledger_sha256",
        )
    }

    def constructor(**kwargs):
        calls.append(kwargs)
        return native

    result = construct_managed_native(
        plan,
        path=written.dataset.file_path,
        dataset_sha256=written.receipt["sha256"],
        expected_runtime=binding,
        observe_runtime=lambda: binding,
        managed_constructor=constructor,
        system_constructor=lambda **kw: native_system,
        spm={"SYNTHETIC": "only"},
        read_packet=lambda path: (
            written.receipt["sha256"],
            written.dataset.load_dataset(),
        ),
        context_receipts=contexts,
        observe_context=lambda sim: {
            **contexts,
            "law_year": 2017,
            "reporting_year": 2025,
            "native_price_factor": (4, 5),
        },
    )
    assert result is native and len(calls) == 1
    assert (
        calls[0]["native_input_period"]
        == calls[0]["default_calculation_period"]
        == "2017"
    )
    assert result.dataset.time_period == "2017"
    assert written.receipt["status"] == "SYNTHETIC_SERIALIZER_DOUBLE_NOT_A_DATASET"
    assert (
        result.cliffs_native["bundle_country_pair_certifies_transformed_dataset"]
        is False
    )
