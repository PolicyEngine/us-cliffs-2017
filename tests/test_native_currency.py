"""Entirely synthetic fixtures: mock indices are not CPI estimates or model outputs."""

from decimal import Decimal
from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from cliffs2017.native_currency import (
    ContractError,
    Disposition,
    FieldSpec,
    InputContract,
    Kind,
    PriceBasis,
    cash_to_reference,
    earnings_shock_to_native,
    to_native_inputs,
)


@pytest.fixture
def mock_basis():
    return PriceBasis({2017: "80", 2025: "100", 2026: "110"})


def money(name="mock_earnings", *, period="year", unit="USD/year"):
    return FieldSpec(
        name, "person", Kind.PRIMITIVE_MONEY, Disposition.SCALE, unit, period
    )


def single_contract(spec):
    return InputContract((spec,), {"person": 2})


def test_synthetic_cashbook_preserves_facts_and_explicit_scope(mock_basis):
    fields = (
        money(),
        money("mock_hourly_wage", unit="USD/hour"),
        money("mock_savings", unit="USD/stock"),
        FieldSpec("age", "person", Kind.AGE, Disposition.KEEP, "age_years", "year"),
        FieldSpec("person_id", "person", Kind.ID, Disposition.KEEP, "id", "eternity"),
        FieldSpec(
            "person_weight", "person", Kind.WEIGHT, Disposition.KEEP, "weight", "year"
        ),
        FieldSpec(
            "first_home_mortgage_origination_year",
            "person",
            Kind.CALENDAR,
            Disposition.KEEP,
            "calendar_year",
            "year",
        ),
        FieldSpec(
            "mock_credit",
            "person",
            Kind.POLICY_DERIVED,
            Disposition.DROP,
            "USD/year",
            "year",
        ),
        FieldSpec(
            "mock_ss_payment",
            "person",
            Kind.POLICY_DERIVED,
            Disposition.BACKGROUND,
            "USD/year",
            "year",
            "ss_entitlement_excluded",
        ),
    )
    contract = InputContract(
        fields, {"person": 2}, frozenset({"ss_entitlement_excluded"})
    )
    original = {
        "mock_earnings": [50_000, -1_000],
        "mock_hourly_wage": ["12.50", 20],
        "mock_savings": [0, 100],
        "age": [40, 8],
        "person_id": [101, 102],
        "person_weight": [Fraction(3, 2), 7],
        "first_home_mortgage_origination_year": [2023, 0],
        "mock_credit": [300, 100],
        "mock_ss_payment": [10_000, 0],
    }
    result = to_native_inputs(
        original, contract=contract, basis=mock_basis, target_year=2017
    )
    assert result.values["mock_earnings"] == (40_000, -800)
    assert result.values["mock_hourly_wage"] == (10, 16)
    assert result.values["mock_savings"] == (0, 80)
    for name in (
        "age",
        "person_id",
        "person_weight",
        "first_home_mortgage_origination_year",
    ):
        assert result.values[name] == tuple(original[name])
    assert result.values["mock_ss_payment"] == (8_000, 0)
    assert result.dropped_fields == ("mock_credit",)
    assert "mock_credit" not in result.values
    assert result.background_scopes == {"mock_ss_payment": "ss_entitlement_excluded"}
    assert result.units["mock_hourly_wage"] == "USD/hour"
    # Snapshot caller-owned containers; neither direction mutates the other.
    original["age"][0] = 99
    assert result.values["age"] == (40, 8)
    with pytest.raises(TypeError):
        result.values["age"] = (99, 8)


@pytest.mark.parametrize("year", [2017, 2025, 2026])
@pytest.mark.parametrize("unit", ["USD/year", "USD/hour", "USD/stock"])
def test_exact_roundtrip_with_nonterminating_values(year, unit, mock_basis):
    original = [Fraction(-1, 3), Decimal("123456.7890123456789")]
    spec = money(unit=unit)
    result = to_native_inputs(
        {spec.name: original},
        contract=single_contract(spec),
        basis=mock_basis,
        target_year=year,
    )
    restored = cash_to_reference(
        result.values[spec.name],
        basis=mock_basis,
        native_year=year,
        unit=unit,
        period="year",
        entity_count=2,
    )
    assert restored == tuple(Fraction(value) for value in original)


def test_months_remain_distinct_and_roundtrip_without_annual_broadcast(mock_basis):
    original = {month: [month, month * 10] for month in range(1, 13)}
    spec = money("mock_monthly_cost", period="month", unit="USD/month")
    result = to_native_inputs(
        {spec.name: original},
        contract=single_contract(spec),
        basis=mock_basis,
        target_year=2017,
    )
    assert result.values[spec.name][1] == (Fraction(4, 5), 8)
    assert result.values[spec.name][12] == (Fraction(48, 5), 96)
    restored = cash_to_reference(
        result.values[spec.name],
        basis=mock_basis,
        native_year=2017,
        unit="USD/month",
        period="month",
        entity_count=2,
    )
    assert dict(restored) == {
        month: tuple(values) for month, values in original.items()
    }


def test_same_real_shock_is_difference_in_converted_primitives(mock_basis):
    spec = money()
    contract = single_contract(spec)
    baseline = to_native_inputs(
        {spec.name: [10_000, 0]}, contract=contract, basis=mock_basis, target_year=2017
    )
    shocked = to_native_inputs(
        {spec.name: [11_000, 0]}, contract=contract, basis=mock_basis, target_year=2017
    )
    converted_shock = earnings_shock_to_native(
        1_000, basis=mock_basis, target_year=2017, unit="USD/year"
    )
    assert (
        shocked.values[spec.name][0] - baseline.values[spec.name][0]
        == converted_shock
        == 800
    )


@pytest.mark.parametrize(
    "bad_inputs", [{}, {"mock_earnings": [1, 2], "unreviewed": [1, 2]}]
)
def test_no_missing_field_defaults_or_unknown_field_passthrough(bad_inputs, mock_basis):
    with pytest.raises(ContractError, match="Unknown or missing"):
        to_native_inputs(
            bad_inputs,
            contract=single_contract(money()),
            basis=mock_basis,
            target_year=2017,
        )


@pytest.mark.parametrize("bad", [[1], [1, 2, 3], [[1], [2]], "12", None])
def test_rejects_wrong_shape_or_nonnumeric_nested_values(bad, mock_basis):
    with pytest.raises(ContractError):
        to_native_inputs(
            {"mock_earnings": bad},
            contract=single_contract(money()),
            basis=mock_basis,
            target_year=2017,
        )


@pytest.mark.parametrize(
    "bad", [None, True, float("inf"), float("nan"), "NaN", Decimal("Infinity")]
)
def test_missing_boolean_or_nonfinite_money_is_never_coerced_to_zero(bad, mock_basis):
    with pytest.raises(ContractError):
        to_native_inputs(
            {"mock_earnings": [1, bad]},
            contract=single_contract(money()),
            basis=mock_basis,
            target_year=2017,
        )


@pytest.mark.parametrize(
    "bad_block", [[1, 2], {1: [1, 2]}, {month: [1] for month in range(1, 13)}]
)
def test_monthly_inputs_require_twelve_complete_vectors(bad_block, mock_basis):
    spec = money(period="month", unit="USD/month")
    with pytest.raises(ContractError):
        to_native_inputs(
            {spec.name: bad_block},
            contract=single_contract(spec),
            basis=mock_basis,
            target_year=2017,
        )


@pytest.mark.parametrize("year", [2016, 2027, True, "2017", 2018])
def test_unsupported_or_unpriced_year_fails(year, mock_basis):
    with pytest.raises(ContractError):
        to_native_inputs(
            {"mock_earnings": [1, 2]},
            contract=single_contract(money()),
            basis=mock_basis,
            target_year=year,
        )


@pytest.mark.parametrize(
    "indices", [{2025: 0}, {2025: -1}, {2025: "NaN"}, {2017: 80}, {True: 80, 2025: 100}]
)
def test_price_basis_never_supplies_or_accepts_invalid_indices(indices):
    with pytest.raises(ContractError):
        PriceBasis(indices)


def test_price_basis_is_snapshot_of_declared_mapping():
    original = {2017: 80, 2025: 100}
    basis = PriceBasis(original)
    original[2017] = 999
    assert basis.factor(2017) == Fraction(4, 5)


@pytest.mark.parametrize("disposition", [Disposition.KEEP, Disposition.SCALE, "guess"])
def test_derived_output_cannot_be_kept_or_scaled_as_primitive(disposition):
    with pytest.raises(ContractError):
        FieldSpec(
            "mock_credit",
            "person",
            Kind.POLICY_DERIVED,
            disposition,
            "USD/year",
            "year",
        )


def test_background_requires_both_named_scope_and_contract_approval():
    with pytest.raises(ContractError):
        FieldSpec(
            "mock_credit",
            "person",
            Kind.POLICY_DERIVED,
            Disposition.BACKGROUND,
            "USD/year",
            "year",
        )
    field = FieldSpec(
        "mock_credit",
        "person",
        Kind.POLICY_DERIVED,
        Disposition.BACKGROUND,
        "USD/year",
        "year",
        "excluded_payment_policy",
    )
    with pytest.raises(ContractError, match="not approved"):
        single_contract(field)


@pytest.mark.parametrize(
    "name",
    ["age", "person_weight", "person_id", "first_home_mortgage_origination_year"],
)
def test_known_facts_cannot_be_misdeclared_as_money(name):
    with pytest.raises(ContractError):
        money(name)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"unit": "USD"},
        {"unit": "USD/month", "period": "year"},
        {"unit": "USD/year", "period": "month"},
        {"period": "day"},
    ],
)
def test_unit_and_period_contract_has_no_implicit_conversions(kwargs):
    with pytest.raises(ContractError):
        money(**kwargs)


def test_dropped_derived_fields_are_still_shape_validated(mock_basis):
    field = FieldSpec(
        "mock_credit",
        "person",
        Kind.POLICY_DERIVED,
        Disposition.DROP,
        "USD/year",
        "year",
    )
    with pytest.raises(ContractError):
        to_native_inputs(
            {"mock_credit": [1]},
            contract=single_contract(field),
            basis=mock_basis,
            target_year=2017,
        )


@pytest.mark.parametrize(
    "counts", [{}, {"person": True}, {"person": -1}, {"person": 2, "unknown_entity": 3}]
)
def test_declared_entity_shapes_are_required(counts):
    with pytest.raises(ContractError):
        InputContract((money(),), counts)


def test_duplicate_declarations_fail_before_conversion():
    with pytest.raises(ContractError):
        InputContract((money(), money()), {"person": 2})


def test_inverse_is_cash_only_and_shock_is_flow_only(mock_basis):
    with pytest.raises(ContractError):
        cash_to_reference(
            [1, 2],
            basis=mock_basis,
            native_year=2017,
            unit="weight",
            period="year",
            entity_count=2,
        )
    with pytest.raises(ContractError):
        earnings_shock_to_native(
            1, basis=mock_basis, target_year=2017, unit="USD/stock"
        )


def test_explicit_calendar_dates_and_structural_flags_are_unchanged(mock_basis):
    fields = (
        FieldSpec(
            "birth_date",
            "person",
            Kind.CALENDAR,
            Disposition.KEEP,
            "calendar_date",
            "year",
        ),
        FieldSpec(
            "mock_member_id",
            "person",
            Kind.STRUCTURE,
            Disposition.KEEP,
            "id",
            "eternity",
        ),
        FieldSpec(
            "mock_role", "person", Kind.STRUCTURE, Disposition.KEEP, "flag", "year"
        ),
    )
    original = {
        "birth_date": ["2020-05-02", "1985-03-01"],
        "mock_member_id": [101, 101],
        "mock_role": [False, True],
    }
    result = to_native_inputs(
        original,
        contract=InputContract(fields, {"person": 2}),
        basis=mock_basis,
        target_year=2017,
    )
    assert result.values == {name: tuple(values) for name, values in original.items()}


@pytest.mark.parametrize("bad_weight", [-1, float("nan"), None, True])
def test_given_weights_are_validated_but_never_scaled_or_defaulted(
    bad_weight, mock_basis
):
    field = FieldSpec(
        "person_weight", "person", Kind.WEIGHT, Disposition.KEEP, "weight", "year"
    )
    with pytest.raises(ContractError):
        to_native_inputs(
            {field.name: [0, bad_weight]},
            contract=single_contract(field),
            basis=mock_basis,
            target_year=2017,
        )


def test_boolean_month_key_is_not_an_integer_month(mock_basis):
    field = money(period="month", unit="USD/month")
    invalid = {True if month == 1 else month: [1, 2] for month in range(1, 13)}
    with pytest.raises(ContractError):
        to_native_inputs(
            {field.name: invalid},
            contract=single_contract(field),
            basis=mock_basis,
            target_year=2017,
        )


@pytest.mark.parametrize("reference_year", [2024, True, "2025"])
def test_reference_year_is_explicit_and_supported(reference_year):
    with pytest.raises(ContractError):
        PriceBasis({2017: 80, 2025: 100}, reference_year=reference_year)


@settings(max_examples=50, deadline=100, database=None, derandomize=True)
@given(
    endowments=st.lists(
        st.one_of(
            st.integers(-1_000_000, 1_000_000),
            st.decimals(
                "-1000000", "1000000", places=4, allow_nan=False, allow_infinity=False
            ),
        ),
        min_size=1,
        max_size=6,
    ),
    reference_price=st.decimals(
        "1", "10000", places=3, allow_nan=False, allow_infinity=False
    ),
    native_price=st.decimals(
        "1", "10000", places=3, allow_nan=False, allow_infinity=False
    ),
    year=st.integers(2017, 2026),
    unit=st.sampled_from(["USD/year", "USD/month", "USD/hour", "USD/stock"]),
)
def test_property_mock_money_roundtrip(
    endowments, reference_price, native_price, year, unit
):
    """Unit conversion is invertible for synthetic signed money in any supported year."""
    indices = {2025: reference_price}
    if year != 2025:
        indices[year] = native_price
    basis = PriceBasis(indices)
    period = "month" if unit == "USD/month" else "year"
    field = money("mock_property_money", period=period, unit=unit)
    contract = InputContract((field,), {"person": len(endowments)})
    # Explicit distinct months; this does not broadcast one annual total.
    original = (
        {
            month: [Fraction(value) + Fraction(month, 100) for value in endowments]
            for month in range(1, 13)
        }
        if period == "month"
        else endowments
    )
    native = to_native_inputs(
        {field.name: original}, contract=contract, basis=basis, target_year=year
    )
    restored = cash_to_reference(
        native.values[field.name],
        basis=basis,
        native_year=year,
        unit=unit,
        period=period,
        entity_count=len(endowments),
    )
    if period == "month":
        assert dict(restored) == {
            month: tuple(values) for month, values in original.items()
        }
    else:
        assert restored == tuple(Fraction(value) for value in original)
    assert native.units[field.name] == unit
    assert native.target_year == year


@settings(max_examples=50, deadline=100, database=None, derandomize=True)
@given(
    endowment=st.one_of(
        st.integers(-1_000_000, 1_000_000),
        st.decimals(
            "-1000000", "1000000", places=4, allow_nan=False, allow_infinity=False
        ),
    ),
    shock=st.decimals(
        "-10000", "10000", places=4, allow_nan=False, allow_infinity=False
    ),
    reference_price=st.integers(1, 10000),
    native_price=st.integers(1, 10000),
    year=st.integers(2017, 2026),
    age=st.integers(0, 110),
    mock_weight=st.decimals(
        "0", "1000", places=3, allow_nan=False, allow_infinity=False
    ),
    origination_year=st.integers(0, 2035),
)
def test_property_mock_shock_is_linear_and_facts_are_fixed(
    endowment,
    shock,
    reference_price,
    native_price,
    year,
    age,
    mock_weight,
    origination_year,
):
    """A synthetic real shock changes money only, even with future contract dates."""
    indices = {2025: reference_price}
    if year != 2025:
        indices[year] = native_price
    basis = PriceBasis(indices)
    fields = (
        money(),
        FieldSpec("age", "person", Kind.AGE, Disposition.KEEP, "age_years", "year"),
        FieldSpec("person_id", "person", Kind.ID, Disposition.KEEP, "id", "eternity"),
        FieldSpec(
            "person_weight", "person", Kind.WEIGHT, Disposition.KEEP, "weight", "year"
        ),
        FieldSpec(
            "first_home_mortgage_origination_year",
            "person",
            Kind.CALENDAR,
            Disposition.KEEP,
            "calendar_year",
            "year",
        ),
    )
    contract = InputContract(fields, {"person": 1})
    original = {
        "mock_earnings": [endowment],
        "age": [age],
        "person_id": [101],
        "person_weight": [mock_weight],
        "first_home_mortgage_origination_year": [origination_year],
    }
    shocked_input = {
        **original,
        "mock_earnings": [Fraction(endowment) + Fraction(shock)],
    }
    baseline = to_native_inputs(
        original, contract=contract, basis=basis, target_year=year
    )
    shocked = to_native_inputs(
        shocked_input, contract=contract, basis=basis, target_year=year
    )
    assert shocked.values["mock_earnings"][0] - baseline.values["mock_earnings"][
        0
    ] == earnings_shock_to_native(
        shock,
        basis=basis,
        target_year=year,
        unit="USD/year",
    )
    for name in (
        "age",
        "person_id",
        "person_weight",
        "first_home_mortgage_origination_year",
    ):
        assert baseline.values[name] == shocked.values[name] == tuple(original[name])
