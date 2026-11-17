"""Explicit native-packet transport through the existing managed constructor.

No policy logic or projection lives here. Importing this module loads stdlib only.
The owner supplies authenticated runtime/source receipts and the maintained public
managed constructor. Neither this module nor a fake test certifies those receipts.
"""

import math
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from types import MappingProxyType


class NativeEngineError(ValueError):
    """An unbound runtime, dataset, period or input contract."""


ENTITIES = frozenset(
    {"person", "household", "tax_unit", "spm_unit", "family", "marital_unit"}
)
PACKAGES = frozenset(
    {"policyengine", "policyengine-us", "policyengine-core", "spm-calculator"}
)


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise NativeEngineError("An exact sha256 is required")
    return value


def _freeze(value):
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if hasattr(value, "tolist"):
        return _freeze(value.tolist())
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class RuntimeBinding:
    """Exact installed identities, tied upstream to a source admission receipt."""

    country_commit: str
    versions: Mapping
    source_receipt_sha256: str

    def __post_init__(self):
        if not re.fullmatch(r"[a-f0-9]{40}", self.country_commit):
            raise NativeEngineError("An exact country commit is required")
        if set(self.versions) != PACKAGES or any(
            not isinstance(value, str) or not value.strip()
            for value in self.versions.values()
        ):
            raise NativeEngineError("Bind wrapper, country, Core and SPM versions")
        _digest(self.source_receipt_sha256)
        object.__setattr__(self, "versions", _freeze(self.versions))


@dataclass(frozen=True)
class InputSpec:
    entity: str
    period: str
    dtype: str
    unit: str

    def __post_init__(self):
        if (
            self.entity not in ENTITIES
            or self.period not in {"year", "month", "eternity"}
            or self.dtype not in {"int64", "float64", "bool", "str"}
        ):
            raise NativeEngineError("Unsupported explicit entity/period/encoding")
        if not isinstance(self.unit, str) or not self.unit:
            raise NativeEngineError("Declare every input's unit")


@dataclass(frozen=True)
class PacketPlan:
    law_year: int
    reference_year: int
    arrays: Mapping
    specs: Mapping
    entity_counts: Mapping
    source_sha256: str
    projection_receipt_sha256: str
    contract_sha256: str
    native_price_factor: Fraction
    lookback_declarations: Mapping


def _value(value, dtype, unit=None):
    if dtype == "bool":
        if type(value) is not bool:
            raise NativeEngineError("Boolean encoding requires actual booleans")
        return value
    if dtype == "str":
        if not isinstance(value, str) or (not value and unit != "code"):
            raise NativeEngineError(
                "Only explicit code fields may contain empty strings"
            )
        return value
    if dtype == "int64":
        if type(value) is not int or not -(2**63) <= value < 2**63:
            raise NativeEngineError("ID/integer encoding must be exact int64")
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float, Fraction)):
        raise NativeEngineError("float64 transport requires finite numeric values")
    try:
        encoded = float(value)
    except (OverflowError, ValueError) as error:
        raise NativeEngineError("Numeric transport overflow") from error
    if not math.isfinite(encoded) or (value != 0 and encoded == 0):
        raise NativeEngineError("Nonfinite or underflowed numeric transport")
    # This is an explicit representation check, not currency-to-cents rounding.
    exact = Fraction(value)
    if abs(Fraction(encoded) - exact) > max(Fraction(1, 10**9), abs(exact) / 10**12):
        raise NativeEngineError("Numeric encoding exceeds declared transport tolerance")
    return encoded


def _structural_values(arrays, specs, name):
    period = specs[name].period
    if period not in {"year", "eternity"}:
        raise NativeEngineError(
            "Structural IDs require an explicit annual or eternal period"
        )
    return arrays[name]["2017" if period == "year" else "eternity"]


def prepare_packet(
    packet,
    *,
    specs,
    source_sha256,
    projection_receipt,
    contract_sha256,
    lookback_arrays=None,
    lookback_declarations=None,
    role_keys,
):
    """Validate a PR5-shaped law2017 packet and separately declared native history.

    Pre2017 history is NOT added to PR5's compiler. A separate declaration for
    each supplied variable/period must name its consumer and already-native
    unit convention. No prior period, month, population row or CPI is inferred.
    """
    if (
        type(packet.law_year) is not int
        or packet.law_year != 2017
        or packet.reference_year != 2025
    ):
        raise NativeEngineError("This client seam is law2017/reference2025 only")
    if set(packet.entity_counts) != ENTITIES or any(
        type(count) is not int or count <= 0 for count in packet.entity_counts.values()
    ):
        raise NativeEngineError("Positive counts for all six entities required")
    _digest(source_sha256)
    _digest(contract_sha256)
    if not isinstance(projection_receipt, Mapping) or projection_receipt != {
        "source_year": 2024,
        "reference_year": 2025,
        "projections": 1,
        "source_sha256": source_sha256,
        "receipt_sha256": projection_receipt.get("receipt_sha256"),
    }:
        raise NativeEngineError("Bind the single2024-to2025 reference projection")
    _digest(projection_receipt["receipt_sha256"])
    if set(specs) != set(packet.arrays) or not all(
        isinstance(spec, InputSpec) for spec in specs.values()
    ):
        raise NativeEngineError("Exactly one complete input declaration per field")
    if dict(packet.units) != {name: spec.unit for name, spec in specs.items()}:
        raise NativeEngineError("Packet units differ from the field contract")
    converted = packet.converted_blocks.get(2017)
    factor = getattr(converted, "factor", None)
    if (
        not isinstance(factor, Fraction)
        or factor <= 0
        or converted.target_year != 2017
        or converted.reference_year != 2025
    ):
        raise NativeEngineError(
            "Bind the packet's exact2017/reference2025 price factor"
        )
    arrays = {name: dict(periods) for name, periods in packet.arrays.items()}
    declarations = dict(lookback_declarations or {})
    histories = dict(lookback_arrays or {})
    if any(name not in specs or not periods for name, periods in histories.items()):
        raise NativeEngineError("Unknown or empty lookback field")
    expected_history = {
        (name, period) for name, periods in histories.items() for period in periods
    }
    if set(declarations) != expected_history:
        raise NativeEngineError("Every lookback binding needs its own declaration")
    for (name, period), declaration in declarations.items():
        if name not in specs or not re.fullmatch(r"201[0-6]", period):
            raise NativeEngineError(
                "Only explicit pre2017 annual lookback bindings here"
            )
        if (
            specs[name].period != "year"
            or declaration
            != {
                "consumer": declaration.get("consumer"),
                "unit": specs[name].unit,
                "convention": "already_native_nominal",
                "shock_linkage": "frozen_instantaneous",
            }
            or not declaration["consumer"]
        ):
            raise NativeEngineError(
                "Lookback needs consumer/native unit/frozen-shock contract"
            )
        if period in arrays[name]:
            raise NativeEngineError("Duplicate variable/period binding")
        arrays[name][period] = histories[name][period]
    encoded = {}
    for name, periods in arrays.items():
        spec = specs[name]
        current = (
            {"eternity"}
            if spec.period == "eternity"
            else {"2017"}
            if spec.period == "year"
            else {f"2017-{month:02d}" for month in range(1, 13)}
        )
        permitted = current | {
            period for field, period in declarations if field == name
        }
        if set(periods) != permitted:
            raise NativeEngineError(
                "Missing, extra or implicitly broadcast input period"
            )
        encoded[name] = {}
        for period, values in periods.items():
            if (
                not isinstance(values, (list, tuple))
                or len(values) != packet.entity_counts[spec.entity]
            ):
                raise NativeEngineError("Wrong input vector/entity length")
            encoded[name][period] = tuple(
                _value(value, spec.dtype, spec.unit) for value in values
            )
    for entity in ENTITIES:
        name = f"{entity}_id"
        spec = specs.get(name)
        if (
            not isinstance(spec, InputSpec)
            or spec.period not in {"year", "eternity"}
            or spec != InputSpec(entity, spec.period, "int64", "id")
        ):
            raise NativeEngineError(
                "Every entity needs exact annual or eternal int64 IDs"
            )
        ids = _structural_values(encoded, specs, name)
        if len(set(ids)) != len(ids):
            raise NativeEngineError("Duplicate entity IDs")
        if entity == "person":
            continue
        membership, role = f"person_{entity}_id", f"person_{entity}_role"
        member_spec = specs.get(membership)
        if (
            not isinstance(member_spec, InputSpec)
            or member_spec.period not in {"year", "eternity"}
            or member_spec != InputSpec("person", member_spec.period, "int64", "id")
            or specs.get(role) != InputSpec("person", "eternity", "str", "category")
        ):
            raise NativeEngineError(
                "Explicit annual/eternal membership and eternal role declarations required"
            )
        if set(_structural_values(encoded, specs, membership)) != set(ids):
            raise NativeEngineError("Dangling membership")
        if entity not in role_keys or not set(encoded[role]["eternity"]).issubset(
            role_keys[entity]
        ):
            raise NativeEngineError("Unknown group role key")
        if entity != "household":
            nested = {}
            for group_id, household_id in zip(
                _structural_values(encoded, specs, membership),
                _structural_values(encoded, specs, "person_household_id"),
            ):
                if group_id in nested and nested[group_id] != household_id:
                    raise NativeEngineError("A group spans multiple households")
                nested[group_id] = household_id
    return PacketPlan(
        2017,
        2025,
        _freeze(encoded),
        _freeze(specs),
        _freeze(packet.entity_counts),
        source_sha256,
        projection_receipt["receipt_sha256"],
        contract_sha256,
        factor,
        _freeze(declarations),
    )


def construct_managed_native(
    plan,
    *,
    path,
    dataset_sha256,
    expected_runtime,
    observe_runtime,
    managed_constructor,
    system_constructor,
    spm,
    read_packet,
    context_receipts,
    observe_context,
):
    """Use maintained constructors; receipt equality never bypasses their guards.

    Callers import the ordinary public policyengine surface normally. Any
    import/compatibility refusal propagates before these callables exist.
    ``observe_runtime`` must use the root-admitted exact software/source proof,
    not a fabricated version/commit. Pure tests inject deliberately fake proof.
    ``read_packet`` reads back serialization and returns (sha256, arrays).
    """
    if not isinstance(plan, PacketPlan) or not isinstance(
        expected_runtime, RuntimeBinding
    ):
        raise NativeEngineError("Prepared packet and explicit runtime binding required")
    if observe_runtime() != expected_runtime:
        raise NativeEngineError("Actual runtime/source identity differs")
    context_names = {
        "runtime_identity_sha256",
        "reference_preparation_sha256",
        "health_price_anchor_sha256",
        "price_basis_sha256",
        "component_ledger_sha256",
    }
    if (
        not isinstance(context_receipts, Mapping)
        or set(context_receipts) != context_names
    ):
        raise NativeEngineError(
            "Explicit account/source/price context receipts required"
        )
    for value in context_receipts.values():
        _digest(value)
    if (
        context_receipts["runtime_identity_sha256"]
        != expected_runtime.source_receipt_sha256
        or context_receipts["reference_preparation_sha256"] != plan.contract_sha256
    ):
        raise NativeEngineError("Context does not bind the runtime/input preparation")
    _digest(dataset_sha256)
    path = Path(path)
    if not path.is_absolute() or path.suffix != ".h5":
        raise NativeEngineError("Explicit absolute local packet file required")
    observed_sha, observed_arrays = read_packet(path)
    if observed_sha != dataset_sha256 or _freeze(observed_arrays) != plan.arrays:
        raise NativeEngineError("Packet bytes or decoded period arrays differ")
    if not isinstance(spm, Mapping) or not spm:
        raise NativeEngineError("Explicit source-backed SPM selection required")
    system = system_constructor(start_instant="2017-01-01", spm=dict(spm))
    structural = {
        f"person_{entity}_{part}"
        for entity in ENTITIES - {"person"}
        for part in ("role",)
    }
    for name, spec in plan.specs.items():
        if name in structural:
            continue  # Core uses role columns to construct populations, not variables.
        variable = system.variables.get(name)
        if (
            variable is None
            or variable.entity.key != spec.entity
            or str(variable.definition_period).lower() != spec.period
        ):
            raise NativeEngineError("Unknown input or actual variable schema mismatch")
    for entity in system.group_entities:
        roles = plan.arrays[f"person_{entity.key}_role"]["eternity"]
        members = _structural_values(plan.arrays, plan.specs, f"person_{entity.key}_id")
        accepted = {role.key: role.max for role in entity.flattened_roles}
        role_counts = Counter(zip(members, roles))
        for (member, role), count in role_counts.items():
            if role not in accepted:
                raise NativeEngineError("Role is not an actual flattened role key")
            maximum = accepted[role]
            if maximum is not None and count > maximum:
                raise NativeEngineError("Role capacity exceeded")
    # No dataset_end_year, RowFilterStrategy or re-projection of prepared data.
    sim = managed_constructor(
        dataset=str(path),
        allow_unmanaged=True,
        tax_benefit_system=system,
        start_instant="2017-01-01",
        spm=dict(spm),
        native_input_period="2017",
        default_input_period="2017",
        default_calculation_period="2017",
    )
    if observe_runtime() != expected_runtime:
        raise NativeEngineError("Runtime/source identity changed during construction")
    if getattr(sim.dataset, "data_format", None) != "time_period_arrays":
        raise NativeEngineError("Constructor changed native input representation")
    if (
        str(sim.dataset.time_period) != "2017"
        or str(sim.default_input_period) != "2017"
        or str(sim.default_calculation_period) != "2017"
    ):
        raise NativeEngineError("Constructor changed the explicit native2017 clock")
    if _freeze(sim.dataset.load_dataset()) != plan.arrays:
        raise NativeEngineError(
            "Constructor projected, migrated or changed explicit inputs"
        )
    expected_context = {
        **dict(context_receipts),
        "law_year": 2017,
        "reporting_year": 2025,
        "native_price_factor": (
            plan.native_price_factor.numerator,
            plan.native_price_factor.denominator,
        ),
    }
    if _freeze(observe_context(sim)) != _freeze(expected_context):
        raise NativeEngineError("Actual account/price context witness differs")
    # Keep the wrapper's genuine provenance; add an honest transformed-input record.
    sim.cliffs_native = {
        **expected_context,
        "law_year": 2017,
        "reference_year": 2025,
        "dataset_selection": "explicit_unmanaged_transformed_local",
        "dataset_sha256": dataset_sha256,
        "parent_source_sha256": plan.source_sha256,
        "projection_receipt_sha256": plan.projection_receipt_sha256,
        "input_contract_sha256": plan.contract_sha256,
        "native_price_factor": (
            plan.native_price_factor.numerator,
            plan.native_price_factor.denominator,
        ),
        "runtime_country_commit": expected_runtime.country_commit,
        "runtime_versions": dict(expected_runtime.versions),
        "runtime_source_receipt_sha256": expected_runtime.source_receipt_sha256,
        "bundle_country_pair_certifies_transformed_dataset": False,
    }
    return sim  # Return the genuine calc/MicroSeries/map_to surface unchanged.


def native_context(sim):
    """Read the adapter's immutable context; no new calculation or certification."""
    context = getattr(sim, "cliffs_native", None)
    if (
        not isinstance(context, Mapping)
        or context.get("law_year") != 2017
        or context.get("reference_year") != 2025
    ):
        raise NativeEngineError("No native2017/reference2025 context")
    return _freeze(context)
