"""Input-unit conversion only: no engine, policy calculation, or statistics.

The caller supplies a reviewed, complete field contract and explicit price indices.
This module does not discover inputs, classify the actual population, fetch weights,
change periods, broadcast annual amounts into months, or round currency to cents.
Fractions retain exact declared numeric ratios until a future engine adapter chooses
its own numeric representation. No such adapter is included.

Numeric facts retain their supplied finite numeric types; numeric strings are invalid
facts. Monetary strings remain explicit exact decimals. Birth facts dropped for a
fixed-age experiment, or held alongside fixed age, require a reviewed scope and reason.
The result records those dispositions without altering any retained calendar value.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import Enum
from fractions import Fraction
from types import MappingProxyType


class ContractError(ValueError):
    """An undeclared, incompatible, missing, or malformed input."""


class Kind(str, Enum):
    PRIMITIVE_MONEY = "primitive_money"
    POLICY_DERIVED = "policy_derived"
    AGE = "fixed_age"
    ID = "fixed_id"
    WEIGHT = "fixed_weight"
    CALENDAR = "fixed_calendar"
    STRUCTURE = "fixed_structure"
    DEMOGRAPHIC = "fixed_demographic"
    DIMENSIONLESS = "fixed_dimensionless"


class Disposition(str, Enum):
    SCALE = "scale_money"
    KEEP = "keep_fact"
    DROP = "drop_derived"
    BACKGROUND = "named_background_money"


ENTITIES = frozenset(
    {"person", "marital_unit", "family", "tax_unit", "spm_unit", "household"}
)
SUPPORTED_YEARS = frozenset(range(2017, 2027))
MONEY_UNITS = frozenset({"USD/year", "USD/month", "USD/hour", "USD/stock"})
FACT_UNITS = {
    Kind.AGE: frozenset({"age_years"}),
    Kind.ID: frozenset({"id"}),
    Kind.WEIGHT: frozenset({"weight"}),
    Kind.CALENDAR: frozenset({"calendar_year", "calendar_date"}),
    Kind.STRUCTURE: frozenset({"id", "count", "flag"}),
    Kind.DEMOGRAPHIC: frozenset({"category", "flag"}),
    Kind.DIMENSIONLESS: frozenset({"fraction", "count", "flag"}),
}
ALL_UNITS = MONEY_UNITS | frozenset().union(*FACT_UNITS.values())
# Representation limits bound arithmetic resources, not economic values or tax rules.
MAX_NUMERIC_BITS = 4096
MAX_DECIMAL_DIGITS = 1000
MAX_DECIMAL_EXPONENT = 1000
MAX_NUMERIC_TEXT_LENGTH = 2048


def _year(value):
    if type(value) is not int or value not in SUPPORTED_YEARS:
        raise ContractError("Year must be a declared integer in 2017–2026")
    return value


def _number(value):
    """Exact ratio of a finite declared number; bool and missing data are errors."""
    if isinstance(value, bool):
        raise ContractError("Boolean is not a monetary/numeric value")
    if isinstance(value, Fraction):
        if (
            max(value.numerator.bit_length(), value.denominator.bit_length())
            > MAX_NUMERIC_BITS
        ):
            raise ContractError("Numeric ratio exceeds representation limits")
        return value
    if isinstance(value, int):
        if value.bit_length() > MAX_NUMERIC_BITS:
            raise ContractError("Integer exceeds representation limits")
        return Fraction(value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ContractError("Non-finite numeric value")
    if not isinstance(value, (Decimal, float, str)):
        raise ContractError("Expected a finite numeric value, without defaults")
    if isinstance(value, str) and len(value) > MAX_NUMERIC_TEXT_LENGTH:
        raise ContractError("Numeric text exceeds representation limits")
    try:
        decimal = value if isinstance(value, Decimal) else Decimal(str(value))
        if not decimal.is_finite():
            raise ContractError("Non-finite numeric value")
        parts = decimal.as_tuple()
        if (
            len(parts.digits) > MAX_DECIMAL_DIGITS
            or abs(parts.exponent) > MAX_DECIMAL_EXPONENT
            or decimal.adjusted() >= MAX_DECIMAL_DIGITS
        ):
            raise ContractError("Decimal exceeds representation limits")
        return Fraction(decimal)
    except (InvalidOperation, ValueError, ZeroDivisionError) as error:
        raise ContractError("Invalid numeric value") from error


def _scope_names(values):
    if not isinstance(values, (list, tuple, set, frozenset)) or any(
        not isinstance(value, str) or not value.strip() for value in values
    ):
        raise ContractError("Scopes must be a collection of explicit names")
    return frozenset(values)


def _birth_field(name):
    return name in {"birth_year", "birth_date"} or name.endswith(
        ("_birth_year", "_birth_date")
    )


def _period_unit(period, unit):
    if not isinstance(period, str) or period not in {"year", "month", "eternity"}:
        raise ContractError("Unsupported period; no implicit period conversion")
    if not isinstance(unit, str) or unit not in ALL_UNITS:
        raise ContractError("Unsupported unit")
    if unit == "USD/month" and period != "month":
        raise ContractError("USD/month requires explicit monthly blocks")
    if unit in {"USD/year", "USD/hour", "USD/stock"} and period != "year":
        raise ContractError("This currency unit requires an annual input block")


@dataclass(frozen=True)
class PriceBasis:
    """Explicit indices, not an authoritative CPI series or a data downloader."""

    index_by_year: Mapping
    reference_year: int = 2025

    def __post_init__(self):
        if self.reference_year != 2025 or type(self.reference_year) is not int:
            raise ContractError("This contract uses reference year 2025")
        if not isinstance(self.index_by_year, Mapping):
            raise ContractError("Price indices must be an explicit mapping")
        indices = {}
        for year, value in self.index_by_year.items():
            _year(year)
            indices[year] = _number(value)
            if indices[year] <= 0:
                raise ContractError("Price indices must be positive")
        if self.reference_year not in indices:
            raise ContractError("Missing reference price index")
        object.__setattr__(self, "index_by_year", MappingProxyType(indices))

    def factor(self, target_year):
        _year(target_year)
        if target_year not in self.index_by_year:
            raise ContractError("Missing explicitly supplied target price index")
        return self.index_by_year[target_year] / self.index_by_year[self.reference_year]


@dataclass(frozen=True)
class FieldSpec:
    name: str
    entity: str
    kind: Kind
    disposition: Disposition
    unit: str
    period: str
    background_scope: str | None = None
    calendar_scope: str | None = None
    calendar_reason: str | None = None

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise ContractError("Field needs an explicit name")
        if not isinstance(self.entity, str) or self.entity not in ENTITIES:
            raise ContractError("Unsupported entity")
        try:
            object.__setattr__(self, "kind", Kind(self.kind))
            object.__setattr__(self, "disposition", Disposition(self.disposition))
        except (ValueError, TypeError) as error:
            raise ContractError("Unknown kind or disposition") from error
        _period_unit(self.period, self.unit)
        if self.kind == Kind.PRIMITIVE_MONEY:
            valid = self.disposition == Disposition.SCALE and self.unit in MONEY_UNITS
        elif self.kind == Kind.POLICY_DERIVED:
            valid = self.disposition == Disposition.DROP or (
                self.disposition == Disposition.BACKGROUND and self.unit in MONEY_UNITS
            )
        elif self.kind == Kind.CALENDAR:
            valid = self.unit in FACT_UNITS[self.kind] and (
                self.disposition == Disposition.KEEP
                or (_birth_field(self.name) and self.disposition == Disposition.DROP)
            )
        else:
            valid = (
                self.disposition == Disposition.KEEP
                and self.unit in FACT_UNITS[self.kind]
            )
        if not valid:
            raise ContractError("Kind, disposition and unit disagree")
        if self.disposition == Disposition.BACKGROUND:
            if (
                not isinstance(self.background_scope, str)
                or not self.background_scope.strip()
            ):
                raise ContractError("Derived background needs a named excluded scope")
        elif self.background_scope is not None:
            raise ContractError("Scope is only valid for named background money")
        if self.calendar_scope is not None or self.calendar_reason is not None:
            if (
                self.kind != Kind.CALENDAR
                or not _birth_field(self.name)
                or not isinstance(self.calendar_scope, str)
                or not self.calendar_scope.strip()
                or not isinstance(self.calendar_reason, str)
                or not self.calendar_reason.strip()
            ):
                raise ContractError("Birth disposition needs a named scope and reason")
        elif self.kind == Kind.CALENDAR and self.disposition == Disposition.DROP:
            raise ContractError("Dropped birth fact needs a named scope and reason")
        # These lexical backstops do not discover every possible fact/date name.
        # The caller must still review every field's complete declaration.
        if (self.name == "age" or self.name.endswith("_age")) and self.kind != Kind.AGE:
            raise ContractError("Age facts cannot be converted or reclassified")
        if self.name.endswith("_weight") and self.kind != Kind.WEIGHT:
            raise ContractError("Weight facts cannot be converted or reclassified")
        if (self.name == "id" or self.name.endswith("_id")) and self.kind not in {
            Kind.ID,
            Kind.STRUCTURE,
        }:
            raise ContractError("Identifier facts cannot be converted")
        if (
            self.name in {"birth_year", "birth_date"}
            or self.name.endswith(
                ("_origination_year", "_origination_date", "_birth_year", "_birth_date")
            )
        ) and self.kind != Kind.CALENDAR:
            raise ContractError("Calendar facts cannot be converted")


@dataclass(frozen=True)
class InputContract:
    fields: tuple[FieldSpec, ...]
    entity_counts: Mapping
    background_scopes: frozenset[str] = frozenset()
    calendar_scopes: frozenset[str] = frozenset()

    def __post_init__(self):
        if not isinstance(self.fields, (list, tuple)):
            raise ContractError("Fields must be an explicit sequence of declarations")
        fields = tuple(self.fields)
        if not all(isinstance(field, FieldSpec) for field in fields):
            raise ContractError("Every field needs a FieldSpec")
        names = [field.name for field in fields]
        if len(set(names)) != len(names):
            raise ContractError("Duplicate field declaration")
        if not isinstance(self.entity_counts, Mapping):
            raise ContractError("Entity counts must be declared")
        counts = dict(self.entity_counts)
        for entity, count in counts.items():
            if (
                not isinstance(entity, str)
                or entity not in ENTITIES
                or type(count) is not int
                or count < 0
            ):
                raise ContractError("Invalid entity/count")
        scopes = _scope_names(self.background_scopes)
        calendar_scopes = _scope_names(self.calendar_scopes)
        age_entities = {field.entity for field in fields if field.kind == Kind.AGE}
        for field in fields:
            if field.entity not in counts:
                raise ContractError("Missing entity count")
            if (
                field.disposition == Disposition.BACKGROUND
                and field.background_scope not in scopes
            ):
                raise ContractError("Background scope was not approved in the contract")
            if field.kind == Kind.CALENDAR and _birth_field(field.name):
                if (
                    field.calendar_scope is not None
                    and field.calendar_scope not in calendar_scopes
                ):
                    raise ContractError(
                        "Calendar scope was not approved in the contract"
                    )
                if field.entity in age_entities and field.calendar_scope is None:
                    raise ContractError(
                        "Fixed age with a birth fact needs a reviewed disposition"
                    )
                if (
                    field.disposition == Disposition.DROP
                    and field.entity not in age_entities
                ):
                    raise ContractError(
                        "Dropped birth fact requires a declared fixed age"
                    )
        object.__setattr__(self, "fields", fields)
        object.__setattr__(self, "entity_counts", MappingProxyType(counts))
        object.__setattr__(self, "background_scopes", scopes)
        object.__setattr__(self, "calendar_scopes", calendar_scopes)


def _fact(value, unit):
    if unit == "flag":
        if type(value) is not bool:
            raise ContractError("Flag must be bool")
    elif unit in {"id", "category"}:
        if isinstance(value, bool) or not isinstance(value, (int, str)) or value == "":
            raise ContractError(
                "Identifier/category must be a nonempty string or integer"
            )
    elif unit == "calendar_year":
        if type(value) is not int:
            raise ContractError("Calendar year must be an integer; never clamp")
    elif unit == "calendar_date":
        if not isinstance(value, str):
            raise ContractError("Calendar date must be explicit ISO text")
        try:
            date.fromisoformat(value)
        except ValueError as error:
            raise ContractError("Invalid calendar date") from error
    elif unit == "count":
        if type(value) is not int or value < 0:
            raise ContractError("Count must be a nonnegative integer")
    else:
        if isinstance(value, str):
            raise ContractError("Numeric facts require numeric values, not text")
        numeric = _number(value)
        if unit in {"weight", "age_years"} and numeric < 0:
            raise ContractError("Weight/age cannot be negative")
    return value


def _block(values, *, count, period, convert):
    def vector(items):
        if not isinstance(items, (list, tuple)) or len(items) != count:
            raise ContractError(
                "Expected an explicit vector of the declared entity size"
            )
        return tuple(convert(value) for value in items)

    if period == "month":
        if not isinstance(values, Mapping):
            raise ContractError("Monthly input requires twelve explicit month vectors")
        if any(type(month) is not int for month in values) or set(values) != set(
            range(1, 13)
        ):
            raise ContractError(
                "Monthly block must contain exactly integer months 1–12"
            )
        return MappingProxyType(
            {month: vector(values[month]) for month in range(1, 13)}
        )
    return vector(values)


@dataclass(frozen=True)
class ConvertedInputs:
    values: Mapping
    units: Mapping
    dropped_fields: tuple[str, ...]
    background_scopes: Mapping
    target_year: int
    reference_year: int
    factor: Fraction
    calendar_dispositions: Mapping


def to_native_inputs(values, *, contract, basis, target_year):
    """Convert an exactly declared input block; never infer or supply defaults."""
    if not isinstance(contract, InputContract) or not isinstance(basis, PriceBasis):
        raise ContractError("Explicit InputContract and PriceBasis are required")
    if not isinstance(values, Mapping):
        raise ContractError("Inputs must be a field mapping")
    expected = {field.name for field in contract.fields}
    if set(values) != expected:
        raise ContractError("Unknown or missing fields; no implicit defaults")
    factor = basis.factor(target_year)
    converted, units, backgrounds, dropped = {}, {}, {}, []
    calendars = {}
    for field in contract.fields:
        mapper = (
            (lambda value: _number(value) * factor)
            if field.unit in MONEY_UNITS
            else (lambda value, unit=field.unit: _fact(value, unit))
        )
        block = _block(
            values[field.name],
            count=contract.entity_counts[field.entity],
            period=field.period,
            convert=mapper,
        )
        if field.calendar_scope is not None:
            calendars[field.name] = MappingProxyType(
                {
                    "disposition": field.disposition.value,
                    "scope": field.calendar_scope,
                    "reason": field.calendar_reason,
                }
            )
        if field.disposition == Disposition.DROP:
            dropped.append(field.name)
            continue
        converted[field.name] = block
        units[field.name] = field.unit
        if field.disposition == Disposition.BACKGROUND:
            backgrounds[field.name] = field.background_scope
    return ConvertedInputs(
        MappingProxyType(converted),
        MappingProxyType(units),
        tuple(dropped),
        MappingProxyType(backgrounds),
        target_year,
        basis.reference_year,
        factor,
        MappingProxyType(calendars),
    )


def cash_to_reference(values, *, basis, native_year, unit, period, entity_count):
    """Only inverse currency conversion of caller-supplied cash, not policy compute."""
    if not isinstance(basis, PriceBasis):
        raise ContractError("Explicit PriceBasis required")
    _period_unit(period, unit)
    if unit not in MONEY_UNITS:
        raise ContractError("Cash output must have an approved currency unit")
    if type(entity_count) is not int or entity_count < 0:
        raise ContractError("Invalid entity count")
    factor = basis.factor(native_year)
    return _block(
        values,
        count=entity_count,
        period=period,
        convert=lambda value: _number(value) / factor,
    )


def earnings_shock_to_native(value, *, basis, target_year, unit):
    """A declared scalar earnings increment; no period broadcasting or model call."""
    if (
        not isinstance(basis, PriceBasis)
        or not isinstance(unit, str)
        or unit
        not in {
            "USD/year",
            "USD/month",
            "USD/hour",
        }
    ):
        raise ContractError(
            "Shock requires an approved earnings-flow unit and price basis"
        )
    return _number(value) * basis.factor(target_year)
