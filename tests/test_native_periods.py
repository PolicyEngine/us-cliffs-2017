"""Synthetic packet fixtures, not population records, legal goldens or estimates."""

import csv
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cliffs2017.native_currency import (
    ENTITIES,
    ContractError,
    Disposition,
    FieldSpec,
    InputContract,
    Kind,
    PriceBasis,
    cash_to_reference,
)
from cliffs2017.native_periods import build_period_packet


def specimen(*, money=True, extra_fields=()):
    counts = {entity: 4 if entity == "person" else 2 for entity in ENTITIES}
    fields, values = [], {}

    def add(name, entity, kind, unit, period, vector):
        fields.append(FieldSpec(name, entity, kind, Disposition.KEEP, unit, period))
        values[name] = vector

    for index, entity in enumerate(sorted(ENTITIES)):
        ids = [11, 12, 21, 22] if entity == "person" else [100 + index, 200 + index]
        add(f"{entity}_id", entity, Kind.ID, "id", "eternity", ids)
        if entity != "person":
            add(
                f"person_{entity}_id",
                "person",
                Kind.STRUCTURE,
                "id",
                "eternity",
                [ids[0], ids[0], ids[1], ids[1]],
            )
            add(
                f"person_{entity}_role",
                "person",
                Kind.DEMOGRAPHIC,
                "category",
                "eternity",
                ["mock_member"] * 4,
            )
    add("age", "person", Kind.AGE, "age_years", "year", [40.7, 8, 70, 17])
    add(
        "household_weight",
        "household",
        Kind.WEIGHT,
        "weight",
        "year",
        [Fraction(3, 2), 7],
    )
    add("mock_state", "household", Kind.DEMOGRAPHIC, "category", "year", ["MO", "NY"])
    add(
        "mock_take_up",
        "person",
        Kind.DEMOGRAPHIC,
        "flag",
        "year",
        [True, False, True, False],
    )
    add(
        "loan_origination_year",
        "household",
        Kind.CALENDAR,
        "calendar_year",
        "year",
        [2010, 0],
    )
    add(
        "mock_monthly_status",
        "person",
        Kind.DEMOGRAPHIC,
        "flag",
        "month",
        {month: [month % 2 == 0, False, True, False] for month in range(1, 13)},
    )
    if money:
        fields.extend(
            (
                FieldSpec(
                    "mock_earnings",
                    "person",
                    Kind.PRIMITIVE_MONEY,
                    Disposition.SCALE,
                    "USD/year",
                    "year",
                ),
                FieldSpec(
                    "mock_monthly_payment",
                    "person",
                    Kind.PRIMITIVE_MONEY,
                    Disposition.SCALE,
                    "USD/month",
                    "month",
                ),
            )
        )
        values["mock_earnings"] = [100, 0, -10, Fraction(1, 3)]
        values["mock_monthly_payment"] = {
            month: [month, 0, 0, 0] for month in range(1, 13)
        }
    for field, vector in extra_fields:
        fields.append(field)
        values[field.name] = vector
    contract = InputContract(tuple(fields), counts)
    return contract, values


def options(*, year=2017, history=(), money=True, extra_fields=()):
    contract, values = specimen(money=money, extra_fields=extra_fields)
    fixed = {
        field.name: deepcopy(values[field.name])
        for field in contract.fields
        if field.disposition == Disposition.KEEP
    }
    return {
        "reference_blocks": [(y, deepcopy(values)) for y in (year, *history)],
        "contract": contract,
        # Hypothetical indices for pure arithmetic; never a published CPI series.
        "basis": PriceBasis({y: 80 if y == 2017 else 100 for y in range(2017, 2027)}),
        "law_year": year,
        "history_years": history,
        "variable_schema": {
            field.name: (field.entity, field.period) for field in contract.fields
        },
        "fixed_facts": fixed,
    }


@pytest.mark.parametrize("year", range(2017, 2027))
def test_all_years_bind_fixed_synthetic_facts_to_native_period_identity(year):
    packet = build_period_packet(**options(year=year, money=False))
    assert set(packet.arrays["age"]) == {str(year)}
    assert packet.arrays["age"][str(year)] == (40.7, 8, 70, 17)
    assert packet.arrays["person_id"] == {"eternity": (11, 12, 21, 22)}
    assert set(packet.arrays["mock_monthly_status"]) == {
        f"{year}-{month:02d}" for month in range(1, 13)
    }
    assert packet.reference_year == 2025
    assert packet.law_year == year


def test_explicit_history_and_distinct_months_have_no_extra_periods_or_projection():
    packet = build_period_packet(**options(year=2025, history=(2017,)))
    assert set(packet.arrays["mock_earnings"]) == {"2017", "2025"}
    assert packet.arrays["mock_earnings"]["2017"] == (80, 0, -8, Fraction(4, 15))
    assert packet.arrays["mock_earnings"]["2025"] == (100, 0, -10, Fraction(1, 3))
    assert set(packet.arrays["mock_monthly_payment"]) == {
        f"{year}-{month:02d}" for year in (2017, 2025) for month in range(1, 13)
    }
    assert packet.arrays["mock_monthly_payment"]["2017-12"][0] == Fraction(48, 5)
    assert packet.arrays["loan_origination_year"] == {
        "2017": (2010, 0),
        "2025": (2010, 0),
    }
    assert packet.arrays["household_weight"] == {
        "2017": (Fraction(3, 2), 7),
        "2025": (Fraction(3, 2), 7),
    }


def test_packet_snapshots_containers_and_refuses_mutation():
    args = options()
    packet = build_period_packet(**args)
    args["fixed_facts"]["age"][0] = 99
    args["reference_blocks"][0][1]["mock_earnings"][0] = 999
    assert packet.arrays["age"]["2017"][0] == 40.7
    assert packet.arrays["mock_earnings"]["2017"][0] == 80
    with pytest.raises(TypeError):
        packet.arrays["age"]["2017"] = (99, 8, 70, 17)


def test_equal_numeric_values_cannot_change_declared_fixed_fact_types():
    args = options()
    args["fixed_facts"]["age"][1] = 8.0
    with pytest.raises(ContractError, match="Fixed facts"):
        build_period_packet(**args)


@pytest.mark.parametrize(
    "mutation", ["unknown", "missing", "length", "month", "fact", "schema"]
)
def test_incomplete_or_inconsistent_declarations_fail(mutation):
    args = options()
    values = args["reference_blocks"][0][1]
    if mutation == "unknown":
        values["unreviewed"] = [0] * 4
    elif mutation == "missing":
        del values["age"]
    elif mutation == "length":
        values["age"] = [40]
    elif mutation == "month":
        del values["mock_monthly_payment"][12]
    elif mutation == "fact":
        values["age"][0] = 41
    else:
        args["variable_schema"]["age"] = ("household", "month")
    with pytest.raises(ContractError):
        build_period_packet(**args)


@pytest.mark.parametrize(
    "mutation", ["duplicate", "missing", "extra", "future", "pre2017"]
)
def test_history_is_explicit_and_duplicate_years_never_overwrite(mutation):
    args = options(year=2025, history=(2017,))
    if mutation == "duplicate":
        args["reference_blocks"].append(args["reference_blocks"][0])
    elif mutation == "missing":
        args["reference_blocks"].pop()
    elif mutation == "extra":
        args["reference_blocks"].append(
            (2024, deepcopy(args["reference_blocks"][0][1]))
        )
    elif mutation == "future":
        args["history_years"] = (2026,)
    else:
        args["history_years"] = (2016,)
    with pytest.raises(ContractError):
        build_period_packet(**args)


@pytest.mark.parametrize(
    "mutation", ["duplicate_id", "unknown_group", "topology_change"]
)
def test_entity_closure_and_fixed_topology_fail_closed(mutation):
    args = options(year=2025, history=(2017,))
    if mutation == "topology_change":
        args["reference_blocks"][1][1]["person_household_id"].reverse()
    else:
        name = "household_id" if mutation == "duplicate_id" else "person_household_id"
        vector = args["fixed_facts"][name]
        vector[0] = vector[1] if mutation == "duplicate_id" else 999
        for _, values in args["reference_blocks"]:
            values[name] = list(vector)
    with pytest.raises(ContractError):
        build_period_packet(**args)


def test_cross_entity_birth_fact_needs_a_scope_even_when_currency_guard_allows_it():
    birth = FieldSpec(
        "mock_birth_year",
        "tax_unit",
        Kind.CALENDAR,
        Disposition.KEEP,
        "calendar_year",
        "year",
    )
    args = options(extra_fields=((birth, [1985, 1955]),))
    with pytest.raises(ContractError, match="birth fact"):
        build_period_packet(**args)


def test_dropped_policy_output_stays_in_receipt_and_out_of_input_payload():
    credit = FieldSpec(
        "mock_credit",
        "tax_unit",
        Kind.POLICY_DERIVED,
        Disposition.DROP,
        "USD/year",
        "year",
    )
    packet = build_period_packet(**options(extra_fields=((credit, [500, 0]),)))
    assert "mock_credit" not in packet.arrays
    assert packet.converted_blocks[2017].dropped_fields == ("mock_credit",)


def test_published_price_file_does_not_authorize_2026_money():
    path = Path(__file__).resolve().parents[1] / "docs/price_basis.csv"
    with path.open() as handle:
        basis = PriceBasis(
            {
                int(row["year"]): row["cpi_u_annual_average"]
                for row in csv.DictReader(handle)
            }
        )
    args = options(year=2026)
    args["basis"] = basis
    with pytest.raises(ContractError, match="2026 money"):
        build_period_packet(**args)


@given(
    st.integers(min_value=-(10**6), max_value=10**6),
    st.integers(min_value=1, max_value=1000),
)
def test_arbitrary_rational_money_roundtrips_without_changing_units_or_facts(
    numerator, denominator
):
    args = options()
    original = Fraction(numerator, denominator)
    args["reference_blocks"][0][1]["mock_earnings"][0] = original
    packet = build_period_packet(**args)
    restored = cash_to_reference(
        packet.arrays["mock_earnings"]["2017"],
        basis=args["basis"],
        native_year=2017,
        unit="USD/year",
        period="year",
        entity_count=4,
    )
    assert restored[0] == original
    assert packet.units["mock_monthly_payment"] == "USD/month"
    assert packet.arrays["household_weight"]["2017"] == (Fraction(3, 2), 7)


@given(st.booleans(), st.booleans())
def test_declaration_and_block_order_do_not_change_packet(
    reverse_fields, reverse_blocks
):
    args = options(year=2025, history=(2017,))
    expected = build_period_packet(**args)
    if reverse_fields:
        args["contract"] = InputContract(
            tuple(reversed(args["contract"].fields)), args["contract"].entity_counts
        )
    if reverse_blocks:
        args["reference_blocks"].reverse()
    actual = build_period_packet(**args)
    assert actual.arrays == expected.arrays
    assert tuple(actual.arrays) == tuple(expected.arrays)
