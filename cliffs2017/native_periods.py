"""Compile explicitly synthetic reference inputs into immutable period packets.

This module neither loads data nor constructs an engine. Its schema is supplied by
the caller; passing validation cannot qualify that schema, a population or a model.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from cliffs2017.native_currency import (
    ENTITIES,
    MONEY_UNITS,
    SUPPORTED_YEARS,
    ContractError,
    Disposition,
    InputContract,
    Kind,
    PriceBasis,
    to_native_inputs,
)


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    return value


def _year(value):
    if type(value) is not int or value not in SUPPORTED_YEARS:
        raise ContractError("Packet years must be explicit integers in 2017–2026")
    return value


def _same_facts(actual, declared):
    if isinstance(actual, Mapping) and isinstance(declared, Mapping):
        keys = {(type(key), key) for key in actual}
        if keys != {(type(key), key) for key in declared}:
            return False
        return all(_same_facts(actual[key], declared[key]) for key in actual)
    if isinstance(actual, tuple) and isinstance(declared, tuple):
        return len(actual) == len(declared) and all(
            _same_facts(left, right) for left, right in zip(actual, declared)
        )
    return type(actual) is type(declared) and actual == declared


@dataclass(frozen=True)
class NativePeriodPacket:
    """Synthetic inputs and declarations, without runtime admission or results."""

    law_year: int
    reference_year: int
    arrays: Mapping
    entity_counts: Mapping
    units: Mapping
    converted_blocks: Mapping


def _validate_topology(contract, fixed_facts):
    if set(contract.entity_counts) != ENTITIES:
        raise ContractError("Declare counts for all six entities")
    fields = {field.name: field for field in contract.fields}
    for entity in sorted(ENTITIES):
        name = f"{entity}_id"
        field = fields.get(name)
        if (
            field is None
            or field.entity != entity
            or field.kind != Kind.ID
            or field.period != "eternity"
        ):
            raise ContractError("Each entity needs an explicit eternal ID vector")
        ids = fixed_facts[name]
        if len(set(ids)) != len(ids):
            raise ContractError("Entity IDs must be unique")
        if entity == "person":
            continue
        membership = f"person_{entity}_id"
        role = f"person_{entity}_role"
        for key in (membership, role):
            spec = fields.get(key)
            if (
                spec is None
                or spec.entity != "person"
                or spec.period != "eternity"
                or spec.disposition != Disposition.KEEP
            ):
                raise ContractError(
                    "Explicit eternal membership and role vectors required"
                )
        if fields[membership].kind not in {Kind.ID, Kind.STRUCTURE}:
            raise ContractError("Membership must be declared as an identifier")
        if fields[membership].unit != "id" or fields[role].unit != "category":
            raise ContractError("Membership/role units must be id/category")
        if not set(fixed_facts[membership]).issubset(ids):
            raise ContractError("Every membership must reference a declared group")


def build_period_packet(
    *,
    reference_blocks,
    contract,
    basis,
    law_year,
    history_years=(),
    variable_schema,
    fixed_facts,
):
    """Bind synthetic blocks to exact years without inference or projection.

    ``reference_blocks`` is a sequence of (year, complete input mapping) pairs,
    including exactly the law year and explicitly requested history years. Each
    block contains reference-2025 money; conversion uses that block's year.
    ``variable_schema`` maps every contract name to (entity, definition period).
    ``fixed_facts`` separately binds every retained nonmonetary input, including
    all entity IDs, person memberships and roles. History shares those facts.

    This deliberately limited convention supplies no pre-2017 history and no
    2026 money. Other history/currency conventions require a separate contract.
    """
    law_year = _year(law_year)
    if not isinstance(contract, InputContract) or not isinstance(basis, PriceBasis):
        raise ContractError("An InputContract and explicit PriceBasis are required")
    if not isinstance(history_years, (list, tuple)):
        raise ContractError("History years must be an explicit sequence")
    history = tuple(_year(year) for year in history_years)
    if len(set(history)) != len(history) or any(year >= law_year for year in history):
        raise ContractError("History years must be distinct and precede the law year")
    if not isinstance(reference_blocks, (list, tuple)):
        raise ContractError("Blocks must be a sequence of explicit year/input pairs")
    blocks = {}
    for item in reference_blocks:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ContractError("Each block needs a year and input mapping")
        year, values = item
        _year(year)
        if year in blocks:
            raise ContractError(
                "Duplicate year would duplicate variable/period bindings"
            )
        blocks[year] = values
    if set(blocks) != {law_year, *history}:
        raise ContractError("Missing or undeclared history/law-year block")

    expected_schema = {
        field.name: (field.entity, field.period) for field in contract.fields
    }
    if (
        not isinstance(variable_schema, Mapping)
        or dict(variable_schema) != expected_schema
    ):
        raise ContractError(
            "Variable schema must exactly match every field/entity/period"
        )
    fact_names = {
        field.name
        for field in contract.fields
        if field.disposition == Disposition.KEEP and field.unit not in MONEY_UNITS
    }
    if not isinstance(fixed_facts, Mapping) or set(fixed_facts) != fact_names:
        raise ContractError("Declare every fixed fact separately, with no extra fields")
    fixed = _freeze(fixed_facts)
    if 2026 in blocks and any(field.unit in MONEY_UNITS for field in contract.fields):
        raise ContractError(
            "2026 money has no completed approved annual price basis here"
        )
    has_age = any(field.kind == Kind.AGE for field in contract.fields)
    for field in contract.fields:
        birth = field.name in {"birth_year", "birth_date"} or field.name.endswith(
            ("_birth_year", "_birth_date")
        )
        if has_age and birth and field.calendar_scope is None:
            raise ContractError(
                "Every birth fact with fixed age needs an explicit hold/drop"
            )

    converted = {}
    arrays = {}
    for year in sorted(blocks):
        block = to_native_inputs(
            blocks[year], contract=contract, basis=basis, target_year=year
        )
        for name in fact_names:
            if not _same_facts(block.values[name], fixed[name]):
                raise ContractError(
                    "Fixed facts/topology changed across declared blocks"
                )
        # Conversion validates all vectors and scalar types before topology checks.
        _validate_topology(contract, fixed)
        converted[year] = block
        for field in contract.fields:
            if field.disposition == Disposition.DROP:
                continue
            values = block.values[field.name]
            if field.period == "eternity":
                if year != law_year:
                    continue
                bindings = {"eternity": values}
            elif field.period == "month":
                bindings = {
                    f"{year}-{month:02d}": values[month] for month in range(1, 13)
                }
            else:
                bindings = {str(year): values}
            destination = arrays.setdefault(field.name, {})
            if destination.keys() & bindings.keys():
                raise ContractError("Duplicate variable/period binding")
            destination.update(bindings)

    return NativePeriodPacket(
        law_year,
        basis.reference_year,
        MappingProxyType(
            {
                name: MappingProxyType(dict(sorted(periods.items())))
                for name, periods in sorted(arrays.items())
            }
        ),
        MappingProxyType(dict(sorted(contract.entity_counts.items()))),
        MappingProxyType(
            {
                field.name: field.unit
                for field in sorted(contract.fields, key=lambda field: field.name)
                if field.disposition != Disposition.DROP
            }
        ),
        MappingProxyType(converted),
    )
