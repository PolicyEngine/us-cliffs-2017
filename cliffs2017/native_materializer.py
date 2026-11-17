"""Materialize declared raw inputs through PR5 and Core's Dataset writer.

This module imports no model, Core, numpy, pandas or HDF library. Native callers
inject the authenticated managed constructor and current-state observer. The
future writer imports Core only when no Dataset class is supplied. Test doubles
produce explicitly synthetic receipts, never dataset qualification.
"""

import hashlib
import inspect
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from cliffs2017.government_transfer_account import CASH_VARIABLE, GOVERNMENT_VARIABLE
from cliffs2017.managed_native import ENTITIES, PacketPlan, prepare_packet
from cliffs2017.native_currency import MONEY_UNITS, Disposition, InputContract
from cliffs2017.native_periods import build_period_packet
from cliffs2017.reference_benchmark_prices import FORBIDDEN_STORED_PRICE_INPUTS


class MaterializationError(ValueError):
    """A source, input, history, projection or serializer contract is missing."""


# Exact source-owned C price contract. This is an input boundary, not a live-state
# witness: account execution still needs its source-authenticated current observer.
FORBIDDEN_STORED_INPUTS = FORBIDDEN_STORED_PRICE_INPUTS | {
    CASH_VARIABLE,
    GOVERNMENT_VARIABLE,
}
FROZEN_IRMAA_STRATEGY = "freeze_baseline_model_imputed_2015_magi"
IRMAA_INPUT = "medicare_irmaa_magi_two_years_prior"
PREPARED_SOURCE_INPUTS = {
    "social_security_retirement": ("person", "year", "float64"),
    "social_security_disability": ("person", "year", "float64"),
    "social_security_survivors": ("person", "year", "float64"),
    "social_security_dependents": ("person", "year", "float64"),
    "is_spm_independent_minor_role": ("person", "eternity", "bool"),
}


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise MaterializationError("An exact source receipt digest is required")
    return value


def _plain(value):
    """Copy input transport values, not weighted statistics or policy outputs."""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if hasattr(value, "tolist"):
        return _plain(value.tolist())
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return tuple(_plain(item) for item in value)
    if value is None or isinstance(value, float) and not math.isfinite(value):
        raise MaterializationError("Missing/nonfinite input facts cannot become zero")
    return value


def _tag(value):
    value = _plain(value)
    if isinstance(value, Mapping):
        return ["mapping", [[key, _tag(value[key])] for key in sorted(value)]]
    if isinstance(value, tuple):
        return ["vector", [_tag(item) for item in value]]
    if type(value) is Fraction:
        return ["fraction", value.numerator, value.denominator]
    if type(value) is float:
        return ["float", value.hex()]
    if type(value) in (bool, int, str):
        return [type(value).__name__, value]
    raise MaterializationError("Unsupported input representation")


def input_digest(value):
    return hashlib.sha256(
        json.dumps(_tag(value), separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True)
class InputRule:
    """An explicit source registry entry, not permission from an inferred name."""

    role: str
    source_evidence_sha256: str
    source_dtype: str | None = None

    def __post_init__(self):
        if self.role not in {"raw", "structural", "drop", "prepared_source"}:
            raise MaterializationError(
                "Reported/formula overrides need a separate admitted source route"
            )
        _digest(self.source_evidence_sha256)
        if self.role == "prepared_source" and self.source_dtype not in {
            "float64",
            "bool",
        }:
            raise MaterializationError("Bind the actual named source column dtype")


def topology_inputs(sim):
    """Read actual Core population IDs, membership indices and flattened roles."""
    if set(sim.populations) != ENTITIES:
        raise MaterializationError("Exactly six source populations are required")
    values, counts = {}, {}
    for entity, population in sim.populations.items():
        ids = _plain(population.ids)
        if not isinstance(ids, tuple) or len(set(ids)) != len(ids):
            raise MaterializationError("Source IDs must be unique explicit vectors")
        counts[entity] = len(ids)
        values[f"{entity}_id"] = ids
        if entity == "person":
            continue
        # Do not let Core's members_role property invent its default first role.
        if population._members_role is None:
            raise MaterializationError(
                "Observed flattened role assignments are required"
            )
        indices = _plain(population.members_entity_id)
        if len(indices) != sim.populations["person"].count or any(
            type(index) is not int or not 0 <= index < len(ids) for index in indices
        ):
            raise MaterializationError("Invalid source membership indices")
        values[f"person_{entity}_id"] = tuple(ids[index] for index in indices)
        values[f"person_{entity}_role"] = tuple(
            role.key for role in population.members_role
        )
    return values, counts


def prepare_reference_once(
    *,
    managed_constructor,
    system_constructor,
    source_path,
    observe_source,
    spm,
    registry,
    contract,
    archival_inputs,
    expected_context,
    observe_context,
):
    """Use one managed2024→2025 preparation, then read only admitted raw fields.

    The observer must derive actual source/runtime/cohort facts. Matching caller
    strings does not qualify them. This helper never treats a 'qualified' flag as
    proof and never interprets all sim.input_variables as approved raw inputs.
    """
    source_path = Path(source_path)
    if (
        not isinstance(contract, InputContract)
        or not source_path.is_absolute()
        or source_path.suffix != ".h5"
    ):
        raise MaterializationError(
            "Bind the selected explicit local reference artifact"
        )
    fields = {field.name: field for field in contract.fields}
    if FORBIDDEN_STORED_INPUTS & {
        name for name, field in fields.items() if field.disposition != Disposition.DROP
    }:
        raise MaterializationError(
            "Stored price inputs would mask reference-price formulas"
        )
    if set(registry) != set(fields) or not all(
        isinstance(rule, InputRule) for rule in registry.values()
    ):
        raise MaterializationError(
            "One reviewed registry entry per input field is required"
        )
    required_context = {
        "source_sha256",
        "runtime_identity_sha256",
        "source_inventory_sha256",
    }
    if (
        not isinstance(expected_context, Mapping)
        or set(expected_context) != required_context
    ):
        raise MaterializationError("Bind source/runtime/original input inventory")
    for value in expected_context.values():
        _digest(value)
    if observe_source(source_path) != {
        "source_year": 2024,
        "sha256": expected_context["source_sha256"],
    }:
        raise MaterializationError("Actual local reference source/year differs")
    if not isinstance(spm, Mapping) or not spm:
        raise MaterializationError("Bind the source SPM selection")
    system = system_constructor(start_instant="2025-01-01", spm=dict(spm))
    sim = managed_constructor(
        dataset=str(source_path),
        allow_unmanaged=True,
        tax_benefit_system=system,
        start_instant="2025-01-01",
        dataset_end_year=2025,
        spm=dict(spm),
    )
    if observe_context(sim) != expected_context:
        raise MaterializationError("Actual managed source/runtime/inventory differs")
    if list(sim.dataset.years) != [2024, 2025]:
        raise MaterializationError(
            "Expected one source2024→reference2025 preparation only"
        )
    topology, counts = topology_inputs(sim)
    if counts != dict(contract.entity_counts):
        raise MaterializationError("The closed source cohort changed")
    fixed_names = {
        field.name
        for field in contract.fields
        if field.disposition == Disposition.KEEP and field.unit not in MONEY_UNITS
    }
    values = {}
    dropped, ingress = [], {}
    for name, field in fields.items():
        rule = registry[name]
        if rule.role == "drop":
            if field.disposition != Disposition.DROP or name not in archival_inputs:
                raise MaterializationError(
                    "Dropped inputs need actual archival facts, not defaults"
                )
            values[name] = _plain(archival_inputs[name])
            dropped.append(name)
            continue
        if field.disposition == Disposition.DROP:
            raise MaterializationError("A dropped field cannot enter the native inputs")
        if rule.role == "structural":
            if name not in topology:
                raise MaterializationError(
                    "Only actual IDs/memberships/roles are structural"
                )
            values[name] = topology[name]
        elif rule.role == "prepared_source":
            route = PREPARED_SOURCE_INPUTS.get(name)
            if route != (field.entity, field.period, rule.source_dtype):
                raise MaterializationError(
                    "Only the five source-bound ingress routes are supported"
                )
            variable = system.variables.get(name)
            if (
                variable is None
                or variable.entity.key != field.entity
                or str(variable.definition_period).lower() != field.period
            ):
                raise MaterializationError("Named source input entity/period changed")
            single = sim.dataset.get_year(2025)
            if str(single.time_period) != "2025":
                raise MaterializationError(
                    "Read only the once-prepared reference2025 source"
                )
            table = getattr(single, field.entity)
            if name not in table.columns:
                raise MaterializationError("The actual named source column is absent")
            column = table[name]
            if str(column.dtype) != rule.source_dtype:
                raise MaterializationError("Prepared source dtype changed")
            values[name] = _plain(column)
            if (
                not isinstance(values[name], tuple)
                or len(values[name]) != counts[field.entity]
            ):
                raise MaterializationError("Named source vector/entity count differs")
            ingress[name] = {
                "entity": field.entity,
                "column": name,
                "source_year": 2025,
                "target_definition_period": field.period,
                "dtype": str(column.dtype),
                "source_evidence_sha256": rule.source_evidence_sha256,
            }
        else:
            variable = system.variables.get(name)
            if (
                variable is None
                or not variable.is_input_variable()
                or name not in sim.input_variables
            ):
                raise MaterializationError(
                    "Stored formula outputs cannot override native policy"
                )
            if (
                variable.entity.key != field.entity
                or str(variable.definition_period).lower() != field.period
            ):
                raise MaterializationError("Actual input entity/period differs")
            if field.period == "month":
                values[name] = {
                    month: _plain(sim.calc(name, period=f"2025-{month:02d}"))
                    for month in range(1, 13)
                }
            else:
                values[name] = _plain(
                    sim.calc(
                        name, period="eternity" if field.period == "eternity" else 2025
                    )
                )
    if set(archival_inputs) != set(dropped) or observe_context(sim) != expected_context:
        raise MaterializationError("Archival inventory or live source context changed")
    # The maintained preparation may uprate source2024 facts. Capture its actual
    # reference2025 result once; never restore old weights or project it again.
    fixed_facts = {name: values[name] for name in sorted(fixed_names)}
    receipt = {
        "source_year": 2024,
        "reference_year": 2025,
        "projections": 1,
        "source_sha256": expected_context["source_sha256"],
        "source_family": "populace_us_2024",
        "managed_call": {
            "dataset": str(source_path),
            "allow_unmanaged": True,
            "dataset_end_year": 2025,
            "start_instant": "2025-01-01",
        },
        "input_sha256": input_digest(values),
        "topology_sha256": input_digest(topology),
        "fixed_facts_sha256": input_digest(fixed_facts),
        "fixed_facts_convention": "captured from once-prepared reference2025; freeze across law/shocks",
        "registry_sha256": input_digest(
            {
                name: (
                    rule.role,
                    rule.source_evidence_sha256,
                    rule.source_dtype or "none",
                )
                for name, rule in registry.items()
            }
        ),
        "prepared_source_ingress": ingress,
        "context": dict(expected_context),
        "dropped_fields": tuple(sorted(dropped)),
    }
    receipt["receipt_sha256"] = input_digest(receipt)
    return values, fixed_facts, receipt


def compile_native_plan(
    values,
    *,
    contract,
    basis,
    specs,
    fixed_facts,
    reference_receipt,
    contract_sha256,
    role_keys,
    required_history,
):
    """Reuse unchanged PR5 and D validation; leave unselected history closed."""
    if not isinstance(required_history, (tuple, list)) or any(
        not isinstance(name, str) or not name for name in required_history
    ):
        raise MaterializationError("Declare actual required history explicitly")
    if tuple(required_history) not in ((), (FROZEN_IRMAA_STRATEGY,)):
        raise MaterializationError(
            "Unselected pre2017 history remains closed; no automatic extension or zero fill"
        )
    receipt_copy = dict(reference_receipt)
    receipt_sha256 = receipt_copy.pop("receipt_sha256", None)
    if receipt_sha256 != input_digest(receipt_copy):
        raise MaterializationError("Reference preparation receipt changed")
    if reference_receipt.get("input_sha256") != input_digest(values):
        raise MaterializationError(
            "Reference values differ from their preparation receipt"
        )
    if reference_receipt.get("fixed_facts_sha256") != input_digest(fixed_facts):
        raise MaterializationError("Fixed facts differ from the preparation receipt")
    packet = build_period_packet(
        reference_blocks=[(2017, values)],
        contract=contract,
        basis=basis,
        law_year=2017,
        history_years=(),
        variable_schema={
            field.name: (field.entity, field.period) for field in contract.fields
        },
        fixed_facts=fixed_facts,
    )
    projection = {
        name: reference_receipt[name]
        for name in (
            "source_year",
            "reference_year",
            "projections",
            "source_sha256",
            "receipt_sha256",
        )
    }
    return prepare_packet(
        packet,
        specs=specs,
        source_sha256=projection["source_sha256"],
        projection_receipt=projection,
        contract_sha256=contract_sha256,
        role_keys=role_keys,
    )


def verify_frozen_irmaa(sim, receipt, *, expected_context, observe_context):
    """Audit the supplied input itself, including on a perturbation branch.

    This uses version-bound Core input provenance rather than known periods,
    which also include computed caches. No static constructor flag substitutes
    for the caller's actual current-state observer.
    """
    if (
        receipt.get("strategy") != FROZEN_IRMAA_STRATEGY
        or receipt.get("benefit_year") != 2017
        or receipt.get("income_year") != 2015
        or receipt.get("current_context") != expected_context
        or observe_context(sim) != expected_context
    ):
        raise MaterializationError("Current model/price/input context changed")
    periods = sim._get_set_input_periods(IRMAA_INPUT)
    if "2017" not in {str(period) for period in periods}:
        raise MaterializationError("Frozen IRMAA must remain an explicit2017 input")
    actual = _plain(sim.calc(IRMAA_INPUT, period=2017, map_to="tax_unit"))
    if input_digest(actual) != receipt["frozen_values_sha256"]:
        raise MaterializationError(
            "Prior MAGI changed in a contemporaneous earnings branch"
        )
    return receipt


def freeze_baseline_irmaa(sim, *, expected_context, observe_context):
    """Root-selected experiment control, not observed2015 income.

    Run once on the unperturbed native2017 simulation after final reforms. Use
    the model's existing imputation, then hold it fixed before all raises/jobs.
    No currency conversion, history fabrication or private weighting occurs.
    """
    if observe_context(sim) != expected_context or not expected_context:
        raise MaterializationError("Bind actual current native model and price context")
    if str(sim.default_calculation_period) != "2017" or set(sim.branches) - {
        "baseline"
    }:
        raise MaterializationError(
            "Freeze only unperturbed native2017 before earnings branches"
        )
    if sim._get_set_input_periods(IRMAA_INPUT):
        raise MaterializationError("Refuse to replace an existing prior-MAGI input")
    variable = sim.tax_benefit_system.variables[IRMAA_INPUT]
    if (
        variable.entity.key != "tax_unit"
        or str(variable.definition_period).lower() != "year"
    ):
        raise MaterializationError("Target prior-MAGI input entity/period changed")
    parameters = sim.tax_benefit_system.parameters(2017)
    if parameters.gov.simulation.medicare_irmaa_uses_current_year_income is not False:
        raise MaterializationError(
            "Current-income IRMAA mode conflicts with frozen prior income"
        )
    result = sim.calc(IRMAA_INPUT, period=2017, map_to="tax_unit")
    values = _plain(result)
    if (
        not isinstance(values, tuple)
        or len(values) != sim.populations["tax_unit"].count
    ):
        raise MaterializationError("Expected a complete tax-unit prior-MAGI vector")
    if any(type(value) not in (float, int) for value in values):
        raise MaterializationError(
            "Prior-MAGI imputation must be finite numeric values"
        )
    if set(sim.branches) - {"baseline"}:
        raise MaterializationError("Imputation created an unexpected earnings branch")
    # Preserve the actual array's dtype at the supported public set_input surface.
    vector = result.copy()
    sim.set_input(IRMAA_INPUT, 2017, vector)
    receipt = {
        "strategy": FROZEN_IRMAA_STRATEGY,
        "benefit_year": 2017,
        "income_year": 2015,
        "unit": "model-imputed2015_nominal_USD/year",
        "provenance": "unperturbed native model imputation; not observed income",
        "frozen_values_sha256": input_digest(values),
        "current_context": dict(expected_context),
    }
    if "baseline" in sim.branches:
        sim.branches["baseline"].set_input(IRMAA_INPUT, 2017, vector.copy())
    verify_frozen_irmaa(
        sim, receipt, expected_context=expected_context, observe_context=observe_context
    )
    if observe_context(sim) != expected_context:
        raise MaterializationError("Current context changed while freezing prior MAGI")
    return receipt


class PrivateFiles:
    """Future admitted artifact I/O; never remove a failed artifact."""

    def claim(self, path):
        if not path.parent.is_dir() or path.is_symlink():
            raise MaterializationError(
                "Use an existing private parent and new regular file"
            )
        with path.open("xb"):
            pass
        status = path.stat()
        return status.st_dev, status.st_ino

    def owns(self, path, token):
        if path.is_symlink():
            return False
        status = path.stat()
        return token == (status.st_dev, status.st_ino)

    def digest(self, path):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()


@dataclass(frozen=True)
class WrittenDataset:
    """An authoritative Core descriptor plus receipt, not a certified source.

    The Dataset object retains time_period=2017 before Core construction. The
    current managed facade accepts only paths and cannot yet use this descriptor;
    do not discard it and infer the clock from a first field instead.
    """

    dataset: object
    receipt: Mapping


def _readback_types(decoded, plan):
    if not isinstance(decoded, Mapping) or set(decoded) != set(plan.arrays):
        raise MaterializationError("Serializer changed the field inventory")
    observed = {}
    for name, periods in plan.arrays.items():
        if not isinstance(decoded[name], Mapping) or set(decoded[name]) != set(periods):
            raise MaterializationError("Serializer changed explicit periods")
        observed[name] = {}
        for period, values in periods.items():
            vector = decoded[name][period]
            dtype = getattr(vector, "dtype", None)
            kind = getattr(dtype, "kind", None)
            size = getattr(dtype, "itemsize", None)
            expected = plan.specs[name].dtype
            valid = (
                expected == "int64"
                and kind == "i"
                and size == 8
                or expected == "float64"
                and kind == "f"
                and size == 8
                or expected == "bool"
                and kind == "b"
                and size == 1
                or expected == "str"
                and kind in {"O", "S", "U"}
            )
            if not valid or tuple(getattr(vector, "shape", ())) != (len(values),):
                raise MaterializationError("Serializer changed transport dtype/shape")
            observed[name][period] = {
                "kind": kind,
                "itemsize": size,
                "length": len(values),
            }
    return observed


def write_native_dataset(
    plan,
    path,
    *,
    serializer_source_sha256,
    dataset_type=None,
    files=None,
    observe_serializer=None,
    mode="native",
):
    """Call Core Dataset.save_dataset/load_dataset, not a handwritten H5 layout.

    This writes actual input data only in a separately admitted native unit.
    Pure tests inject a memory-only Dataset and file store, explicitly labelled.
    """
    if not isinstance(plan, PacketPlan) or (plan.law_year, plan.reference_year) != (
        2017,
        2025,
    ):
        raise MaterializationError("A validated native2017 PacketPlan is required")
    if FORBIDDEN_STORED_INPUTS & set(plan.arrays):
        raise MaterializationError(
            "Stored price inputs would mask reference-price formulas"
        )
    path = Path(path)
    if not path.is_absolute() or path.suffix != ".h5":
        raise MaterializationError("Use an explicit new absolute native artifact path")
    _digest(serializer_source_sha256)
    if mode not in {"native", "synthetic_test"}:
        raise MaterializationError("Unknown writer purpose")
    if dataset_type is None:
        from policyengine_core.data import Dataset

        dataset_type = Dataset
    if files is None:
        files = PrivateFiles()
    if mode == "native":
        source = inspect.getsourcefile(dataset_type)
        if (
            dataset_type.__module__ != "policyengine_core.data.dataset"
            or source is None
        ):
            raise MaterializationError(
                "Use the source-authenticated maintained Core Dataset"
            )
        if (
            hashlib.sha256(Path(source).read_bytes()).hexdigest()
            != serializer_source_sha256
        ):
            raise MaterializationError("Core serializer source changed")
        if (
            not callable(observe_serializer)
            or observe_serializer(dataset_type) != serializer_source_sha256
        ):
            raise MaterializationError("Actual loaded serializer witness is missing")
    data = {
        name: {period: list(values) for period, values in periods.items()}
        for name, periods in plan.arrays.items()
    }
    token = files.claim(path)
    # Core.save_dataset owns file/group/key creation; set its documented attributes.
    NativeDataset = type(
        "CliffsNativeInputs",
        (dataset_type,),
        {
            "name": "cliffs_native_2017",
            "label": "Declared native2017 input packet",
            "data_format": dataset_type.TIME_PERIOD_ARRAYS,
            "file_path": path,
            "time_period": "2017",
        },
    )
    try:
        dataset = NativeDataset(require=False)
        if (
            not files.owns(path, token)
            or dataset.data_format != dataset_type.TIME_PERIOD_ARRAYS
            or dataset.time_period != "2017"
            or Path(dataset.file_path) != path
        ):
            raise MaterializationError("Artifact ownership or format changed")
        dataset.save_dataset(data)
        raw_decoded = dataset.load_dataset()
        observed_types = _readback_types(raw_decoded, plan)
        decoded = _plain(raw_decoded)
        if input_digest(decoded) != input_digest(plan.arrays):
            raise MaterializationError(
                "Core serialization changed explicit inputs/periods"
            )
        if not files.owns(path, token):
            raise MaterializationError("Artifact path no longer belongs to this writer")
        if dataset.time_period != "2017" or Path(dataset.file_path) != path:
            raise MaterializationError("Authoritative dataset descriptor changed")
        artifact_sha256 = files.digest(path)
    except (OSError, ValueError, TypeError, RuntimeError, OverflowError) as error:
        # Core's error may include complete input vectors. Never echo its text.
        raise MaterializationError(
            "Core materialization refused; preserved artifact; " + type(error).__name__
        ) from None
    receipt = {
        "status": "SYNTHETIC_SERIALIZER_DOUBLE_NOT_A_DATASET"
        if mode == "synthetic_test"
        else "PRIVATE_NATIVE_INPUT_ARTIFACT_NOT_CERTIFIED",
        "path": str(path),
        "sha256": artifact_sha256,
        "format": dataset.data_format,
        "law_year": 2017,
        "reference_year": 2025,
        "source_sha256": plan.source_sha256,
        "projection_receipt_sha256": plan.projection_receipt_sha256,
        "contract_sha256": plan.contract_sha256,
        "CPI_factor": (
            plan.native_price_factor.numerator,
            plan.native_price_factor.denominator,
        ),
        "serializer_source_sha256": serializer_source_sha256,
        "decoded_input_sha256": input_digest(decoded),
        "observed_transport_types": observed_types,
        "fields": {
            name: {
                "entity": spec.entity,
                "period": spec.period,
                "dtype": spec.dtype,
                "unit": spec.unit,
            }
            for name, spec in plan.specs.items()
        },
        "entity_counts": dict(plan.entity_counts),
        "descriptor_time_period": dataset.time_period,
        "constructor_clock_qualification": "NOT_RUN; managed facade needs an explicit pre-construction local period capability",
        "certification": "not_attested",
    }
    return WrittenDataset(dataset, receipt)
