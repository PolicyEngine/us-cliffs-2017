"""Pure synthetic transport/factory checks; no scientific package is imported."""

from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from cliffs2017 import managed_native as m

S = "1" * 64


def fixture():
    arrays, specs = {}, {}
    for entity in m.ENTITIES:
        arrays[f"{entity}_id"] = {"eternity": (11,)}
        specs[f"{entity}_id"] = m.InputSpec(entity, "eternity", "int64", "id")
        if entity != "person":
            arrays[f"person_{entity}_id"] = {"eternity": (11,)}
            specs[f"person_{entity}_id"] = m.InputSpec(
                "person", "eternity", "int64", "id"
            )
            arrays[f"person_{entity}_role"] = {"eternity": ("member",)}
            specs[f"person_{entity}_role"] = m.InputSpec(
                "person", "eternity", "str", "category"
            )
    arrays["employment_income"] = {"2017": (Fraction(100, 3),)}
    specs["employment_income"] = m.InputSpec("person", "year", "float64", "USD/year")
    arrays["monthly_cost"] = {
        f"2017-{month:02d}": (Fraction(month, 7),) for month in range(1, 13)
    }
    specs["monthly_cost"] = m.InputSpec("household", "month", "float64", "USD/month")
    packet = SimpleNamespace(
        law_year=2017,
        reference_year=2025,
        arrays=arrays,
        entity_counts={entity: 1 for entity in m.ENTITIES},
        units={name: spec.unit for name, spec in specs.items()},
        converted_blocks={
            2017: SimpleNamespace(
                factor=Fraction(3, 4), target_year=2017, reference_year=2025
            )
        },
    )
    options = {
        "specs": specs,
        "source_sha256": S,
        "contract_sha256": S,
        "projection_receipt": {
            "source_year": 2024,
            "reference_year": 2025,
            "projections": 1,
            "source_sha256": S,
            "receipt_sha256": S,
        },
        "role_keys": {entity: {"member"} for entity in m.ENTITIES - {"person"}},
    }
    return packet, options


def plan():
    packet, options = fixture()
    return m.prepare_packet(packet, **options)


def runtime():
    return m.RuntimeBinding(
        "a" * 40,
        {
            "policyengine": "6.20.2",
            "policyengine-us": "2.144.0",
            "policyengine-core": "3.36.0",
            "spm-calculator": "1.1.0",
        },
        S,
    )


def fake_factory(prepared, *, observer=None, arrays=None, schema=None):
    calls = []
    variables = {
        name: SimpleNamespace(
            entity=SimpleNamespace(key=spec.entity), definition_period=spec.period
        )
        for name, spec in prepared.specs.items()
    }
    if schema is not None:
        variables = schema
    system = SimpleNamespace(
        variables=variables,
        group_entities=[
            SimpleNamespace(
                key=entity, flattened_roles=[SimpleNamespace(key="member", max=None)]
            )
            for entity in m.ENTITIES - {"person"}
        ],
    )
    sentinel = object()
    sim = SimpleNamespace(
        dataset=SimpleNamespace(
            data_format="time_period_arrays",
            time_period="2017",
            load_dataset=lambda: prepared.arrays,
        ),
        calc=lambda *a, **kw: sentinel,
        default_input_period="2017",
        default_calculation_period="2017",
        branches={},
        set_input=lambda *a, **kw: None,
    )

    def system_constructor(**kw):
        calls.append(("system", kw))
        return system

    def managed_constructor(**kw):
        calls.append(("managed", kw))
        return sim

    kwargs = {
        "path": Path("/FAKE/packet.h5"),
        "dataset_sha256": S,
        "expected_runtime": runtime(),
        "observe_runtime": observer or runtime,
        "managed_constructor": managed_constructor,
        "system_constructor": system_constructor,
        "spm": {"FAKE_PROVIDER": "synthetic_only"},
        "read_packet": lambda path: (S, prepared.arrays if arrays is None else arrays),
    }
    kwargs["context_receipts"] = {
        name: S
        for name in (
            "runtime_identity_sha256",
            "reference_preparation_sha256",
            "health_price_anchor_sha256",
            "price_basis_sha256",
            "component_ledger_sha256",
        )
    }
    kwargs["observe_context"] = lambda sim: {
        **kwargs["context_receipts"],
        "law_year": 2017,
        "reporting_year": 2025,
        "native_price_factor": (3, 4),
    }
    return calls, sim, sentinel, kwargs


def test_factory_returns_managed_surface_and_fresh_clock_without_projection():
    prepared = plan()
    calls, sim, sentinel, kwargs = fake_factory(prepared)
    actual = m.construct_managed_native(prepared, **kwargs)
    assert actual is sim
    assert actual.calc("FAKE", period=2017, map_to="person") is sentinel
    assert calls[0][0] == "system" and calls[0][1]["start_instant"] == "2017-01-01"
    assert calls[1][1]["tax_benefit_system"] is not None
    assert calls[1][1]["allow_unmanaged"] is True
    assert calls[1][1]["native_input_period"] == "2017"
    assert (
        calls[1][1]["default_input_period"]
        == calls[1][1]["default_calculation_period"]
        == "2017"
    )
    assert (
        "dataset_end_year" not in calls[1][1] and "scoping_strategy" not in calls[1][1]
    )
    assert (
        actual.cliffs_native["bundle_country_pair_certifies_transformed_dataset"]
        is False
    )
    assert m.native_context(actual)["native_price_factor"] == (3, 4)
    with pytest.raises(TypeError):
        m.native_context(actual)["law_year"] = 2025


def test_mismatch_refuses_before_system_or_managed_constructor():
    prepared = plan()
    calls, _, _, kwargs = fake_factory(
        prepared, observer=lambda: replace(runtime(), country_commit="b" * 40)
    )
    with pytest.raises(m.NativeEngineError, match="runtime/source"):
        m.construct_managed_native(prepared, **kwargs)
    assert calls == []


@pytest.mark.parametrize(
    "periods",
    [
        {"2017": (1,)},
        {"2017-01": (1,)},
        {f"2018-{month:02d}": (1,) for month in range(1, 13)},
    ],
)
def test_monthly_vectors_are_explicit_and_never_broadcast(periods):
    packet, options = fixture()
    packet.arrays["monthly_cost"] = periods
    with pytest.raises(m.NativeEngineError, match="period"):
        m.prepare_packet(packet, **options)


@pytest.mark.parametrize(
    "kind", ["extra", "length", "dangling", "role", "reprojection"]
)
def test_input_transport_refuses_unbound_change(kind):
    packet, options = fixture()
    if kind == "extra":
        packet.arrays["unknown"] = {"2017": (0,)}
    if kind == "length":
        packet.arrays["employment_income"]["2017"] = (1, 2)
    if kind == "dangling":
        packet.arrays["person_household_id"]["eternity"] = (99,)
    if kind == "role":
        packet.arrays["person_household_role"]["eternity"] = ("unknown",)
    if kind == "reprojection":
        options["projection_receipt"]["projections"] = 2
    with pytest.raises(m.NativeEngineError):
        m.prepare_packet(packet, **options)


def test_explicit_lookback_is_separate_and_frozen():
    packet, options = fixture()
    options.update(
        lookback_arrays={"employment_income": {"2015": (99,)}},
        lookback_declarations={
            ("employment_income", "2015"): {
                "consumer": "FAKE_IRMAA_only",
                "unit": "USD/year",
                "convention": "already_native_nominal",
                "shock_linkage": "frozen_instantaneous",
            }
        },
    )
    prepared = m.prepare_packet(packet, **options)
    assert prepared.arrays["employment_income"]["2015"] == (99.0,)
    assert "2016" not in prepared.arrays["employment_income"]
    options["lookback_declarations"] = {}
    with pytest.raises(m.NativeEngineError, match="declaration"):
        m.prepare_packet(packet, **options)


def test_actual_unknown_variable_refuses_before_managed_constructor():
    prepared = plan()
    calls, _, _, kwargs = fake_factory(prepared, schema={})
    with pytest.raises(m.NativeEngineError, match="actual variable"):
        m.construct_managed_native(prepared, **kwargs)
    assert [name for name, _ in calls] == ["system"]


def test_file_readback_and_postconstructor_changes_refuse():
    prepared = plan()
    calls, _, _, kwargs = fake_factory(prepared, arrays={})
    with pytest.raises(m.NativeEngineError, match="decoded"):
        m.construct_managed_native(prepared, **kwargs)
    assert not calls
    calls, sim, _, kwargs = fake_factory(prepared)
    sim.dataset.load_dataset = dict
    with pytest.raises(m.NativeEngineError, match="projected"):
        m.construct_managed_native(prepared, **kwargs)


def test_existing_managed_compatibility_refusal_propagates():
    prepared = plan()
    _, _, _, kwargs = fake_factory(prepared)

    def refuse(**kw):
        raise RuntimeError("FAKE existing compatibility refusal")

    kwargs["managed_constructor"] = refuse
    with pytest.raises(RuntimeError, match="existing compatibility"):
        m.construct_managed_native(prepared, **kwargs)


def test_missing_actual_context_witness_is_not_qualification():
    prepared = plan()
    _, sim, _, kwargs = fake_factory(prepared)
    kwargs["observe_context"] = lambda sim: {}
    with pytest.raises(m.NativeEngineError, match="context witness"):
        m.construct_managed_native(prepared, **kwargs)
    assert not hasattr(sim, "cliffs_native")


@given(st.integers(min_value=-(2**63), max_value=2**63 - 1))
@settings(database=None, derandomize=True)
def test_identifier_encoding_preserves_exact_int64(value):
    assert m._value(value, "int64") == value


@given(
    st.integers(min_value=-(10**8), max_value=10**8),
    st.integers(min_value=1, max_value=1000),
)
@settings(database=None, derandomize=True)
def test_fraction_encoding_is_finite_and_within_declared_tolerance(
    numerator, denominator
):
    value = Fraction(numerator, denominator)
    encoded = m._value(value, "float64")
    assert abs(Fraction(encoded) - value) <= max(
        Fraction(1, 10**9), abs(value) / 10**12
    )


@pytest.mark.parametrize(
    "value", [True, float("nan"), float("inf"), Fraction(1, 10**400), 2**64]
)
def test_refuses_bad_numeric_representation(value):
    with pytest.raises(m.NativeEngineError):
        m._value(value, "int64" if value == 2**64 else "float64")


class CountedRoles(tuple):
    """Bound vector traversals, rather than assert a particular implementation."""

    def __new__(cls, values):
        instance = super().__new__(cls, values)
        instance.traversals = 0
        return instance

    def __iter__(self):
        self.traversals += 1
        return super().__iter__()


def many_person_plan(count):
    original = plan()
    arrays = {}
    for name, periods in original.arrays.items():
        if original.specs[name].entity != "person":
            arrays[name] = dict(periods)
            continue
        arrays[name] = {}
        for period, values in periods.items():
            vector = tuple(range(count)) if name == "person_id" else values * count
            arrays[name][period] = (
                CountedRoles(vector) if name.endswith("_role") else vector
            )
    return replace(
        original,
        arrays=arrays,
        entity_counts={**original.entity_counts, "person": count},
    )


def test_role_capacity_validation_has_bounded_whole_vector_traversals():
    prepared = many_person_plan(1000)
    _, _, _, kwargs = fake_factory(prepared)
    m.construct_managed_native(prepared, **kwargs)
    for entity in m.ENTITIES - {"person"}:
        assert prepared.arrays[f"person_{entity}_role"]["eternity"].traversals <= 4


def test_actual_role_capacity_refuses_before_managed_construction():
    prepared = many_person_plan(2)
    calls, _, _, kwargs = fake_factory(prepared)
    system = kwargs["system_constructor"]()
    for entity in system.group_entities:
        entity.flattened_roles[0].max = 1
    with pytest.raises(m.NativeEngineError, match="capacity exceeded"):
        m.construct_managed_native(prepared, **kwargs)
    assert not any(name == "managed" for name, args in calls)


@pytest.mark.parametrize("clock", ["descriptor", "input", "calculation"])
def test_changed_constructor_clock_is_not_accepted_as_native(clock):
    prepared = plan()
    _, sim, _, kwargs = fake_factory(prepared)
    if clock == "descriptor":
        sim.dataset.time_period = "2015"
    elif clock == "input":
        sim.default_input_period = "2025"
    else:
        sim.default_calculation_period = "2017-01"
    with pytest.raises(m.NativeEngineError, match="explicit native2017 clock"):
        m.construct_managed_native(prepared, **kwargs)
