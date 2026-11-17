"""UNRUN source-shaped role ingress regression; no scientific imports.

Core3.36 SimulationBuilder.join_with_persons: integer columns index the actual
ordered flattened Role objects. These doubles preserve that object identity;
they do not pretend that a raw0/string/bytes is a loaded Role.
"""

from copy import deepcopy
from itertools import product
from types import SimpleNamespace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from cliffs2017 import managed_native as m
from cliffs2017.native_materializer import MaterializationError, topology_inputs
from test_managed_native import fake_factory, plan
from test_native_materializer import plan_from, specimen, write


def groups():
    result = []
    for entity in sorted(m.ENTITIES - {"person"}):
        group = SimpleNamespace(key=entity)
        group.flattened_roles = [
            SimpleNamespace(key="head", max=1, entity=group),
            SimpleNamespace(key="child", max=None, entity=group),
        ]
        result.append(group)
    return result


def explicit_arrays():
    return {
        **{
            f"person_{entity}_role": {"eternity": ("child", "head", "child")}
            for entity in m.ENTITIES - {"person"}
        },
        "age": {"2015": (38, 10, 40), "2017": (40, 12, 42)},
        "monthly": {f"2017-{month:02d}": (month,) for month in range(1, 13)},
    }


def source_shaped_join(group, memberships, ordinals):
    # Independent oracle for Core's documented integer branch. Not a string
    # fallback and not an executed copy/import of the scientific implementation.
    return SimpleNamespace(
        entity=group,
        ids=(101, 202, 303),
        count=3,
        members_entity_id=memberships,
        _members_role=tuple(group.flattened_roles[index] for index in ordinals),
    )


def test_nonfirst_role_ordinals_round_trip_and_all_joins_preserve_logical_facts():
    metadata = groups()
    transport = m.role_transport_from_entities(metadata)
    logical = explicit_arrays()
    physical = m.role_transport_arrays(logical, transport)
    assert all(
        physical[f"person_{entity}_role"]["eternity"] == (1, 0, 1)
        for entity in m.ENTITIES - {"person"}
    )
    assert m.role_transport_arrays(physical, transport, decode=True) == logical
    assert (
        physical["age"] == logical["age"] and physical["monthly"] == logical["monthly"]
    )
    populations = {"person": SimpleNamespace(ids=(7, 8, 9), count=3)}
    for group in metadata:
        populations[group.key] = source_shaped_join(group, (1, 0, 1), (1, 0, 1))
    values, counts = topology_inputs(SimpleNamespace(populations=populations))
    assert counts == {entity: 3 for entity in m.ENTITIES}
    for entity in m.ENTITIES - {"person"}:
        assert values[f"person_{entity}_id"] == (202, 101, 202)
        assert values[f"person_{entity}_role"] == ("child", "head", "child")


def test_small_set_oracle_for_all_three_person_role_vectors():
    transport = m.role_transport_from_entities(groups())
    for expected in product(("head", "child"), repeat=3):
        logical = explicit_arrays()
        for entity in m.ENTITIES - {"person"}:
            logical[f"person_{entity}_role"] = {"eternity": expected}
        physical = m.role_transport_arrays(logical, transport)
        assert physical["person_family_role"]["eternity"] == tuple(
            {"head": 0, "child": 1}[key] for key in expected
        )
        assert m.role_transport_arrays(physical, transport, decode=True) == logical


@pytest.mark.parametrize("invalid", [-1, 2, True, 0.0, "0", b"0", None, (0,)])
def test_invalid_physical_roles_refuse_without_first_role_fallback(invalid):
    transport = m.role_transport_from_entities(groups())
    physical = dict(m.role_transport_arrays(explicit_arrays(), transport))
    physical["person_family_role"] = {"eternity": (invalid, 0, 1)}
    with pytest.raises(m.NativeEngineError, match="physical role"):
        m.role_transport_arrays(physical, transport, decode=True)


@pytest.mark.parametrize(
    "invalid", [0, "head", b"head", SimpleNamespace(key="head", max=1)]
)
def test_loaded_population_requires_actual_role_identity_not_same_key(invalid):
    populations = {"person": SimpleNamespace(ids=(7, 8, 9), count=3)}
    for group in groups():
        populations[group.key] = source_shaped_join(group, (1, 0, 1), (1, 0, 1))
    populations["family"]._members_role = (
        invalid,
        *populations["family"]._members_role[1:],
    )
    with pytest.raises(MaterializationError, match="loaded group role"):
        topology_inputs(SimpleNamespace(populations=populations))


def test_role_count_and_capacity_are_audited_after_actual_shaped_ingress():
    populations = {"person": SimpleNamespace(ids=(7, 8, 9), count=3)}
    for group in groups():
        populations[group.key] = source_shaped_join(group, (1, 0, 1), (1, 0, 1))
    family = populations["family"]
    saved = family._members_role
    family._members_role = saved[:-1]
    with pytest.raises(MaterializationError, match="loaded group role"):
        topology_inputs(SimpleNamespace(populations=populations))
    family._members_role = (family.entity.flattened_roles[0],) * 3
    with pytest.raises(MaterializationError, match="capacity exceeded"):
        topology_inputs(SimpleNamespace(populations=populations))


def test_writer_encodes_roles_as_int64_and_keeps_logical_plan_and_receipt():
    prepared = plan_from(specimen())
    original = {
        name: {period: tuple(values) for period, values in periods.items()}
        for name, periods in prepared.arrays.items()
    }
    written = write(prepared)
    for entity in m.ENTITIES - {"person"}:
        name = f"person_{entity}_role"
        assert written.dataset.data[name] == {"eternity": [0, 0]}
        assert (
            written.receipt["observed_transport_types"][name]["eternity"]["kind"] == "i"
        )
        assert (
            written.receipt["observed_transport_types"][name]["eternity"]["itemsize"]
            == 8
        )
        assert prepared.specs[name].dtype == "str"
    assert written.logical_arrays() == original == prepared.arrays
    assert written.receipt["role_transport"]["format"] == m.ROLE_TRANSPORT_FORMAT
    assert written.receipt["role_transport_sha256"] == m.role_transport_digest(
        written.receipt["role_transport"]
    )
    assert written.receipt["certification"] == "not_attested"


def test_changed_native_role_order_or_capacity_refuses_before_managed_constructor():
    prepared = plan()
    calls, _, _, kwargs = fake_factory(prepared)
    transport = deepcopy(kwargs["role_transport"])
    transport["entities"]["family"][0]["max"] = 1
    kwargs["role_transport"] = transport
    with pytest.raises(m.NativeEngineError, match="order/capacity differs"):
        m.construct_managed_native(prepared, **kwargs)
    assert not any(name == "managed" for name, _ in calls)


def test_reversed_role_metadata_has_different_ordinals_and_no_silent_reinterpretation():
    metadata = groups()
    first = m.role_transport_from_entities(metadata)
    for entity in metadata:
        entity.flattened_roles.reverse()
    second = m.role_transport_from_entities(metadata)
    assert first != second
    assert m.role_transport_digest(first) != m.role_transport_digest(second)
    physical = m.role_transport_arrays(explicit_arrays(), first)
    decoded = m.role_transport_arrays(physical, second, decode=True)
    assert decoded != explicit_arrays()  # Fresh native metadata check must refuse it.


def test_nullable_capacity_is_metadata_and_missing_input_facts_still_refuse():
    from cliffs2017.native_materializer import input_digest

    transport = m.role_transport_from_entities(groups())
    first = m.role_transport_digest(transport)
    changed = deepcopy(transport)
    changed["entities"]["family"][1]["max"] = 2
    assert first != m.role_transport_digest(changed)
    assert first == m.role_transport_digest(dict(reversed(list(transport.items()))))
    with pytest.raises(MaterializationError, match="Missing/nonfinite input"):
        input_digest({"age": {"2017": (None,)}})


@given(
    st.lists(st.sampled_from(("head", "child")), min_size=1, max_size=24), st.booleans()
)
@settings(max_examples=30, deadline=None)
def test_generated_roles_round_trip_against_independent_ordered_key_oracle(
    keys, reverse
):
    metadata = groups()
    if reverse:
        for entity in metadata:
            entity.flattened_roles.reverse()
    transport = m.role_transport_from_entities(metadata)
    logical = explicit_arrays()
    for entity in m.ENTITIES - {"person"}:
        logical[f"person_{entity}_role"] = {"eternity": tuple(keys)}
    physical = m.role_transport_arrays(logical, transport)
    oracle = {"child": 0, "head": 1} if reverse else {"head": 0, "child": 1}
    assert physical["person_family_role"]["eternity"] == tuple(
        oracle[key] for key in keys
    )
    assert m.role_transport_arrays(physical, transport, decode=True) == logical
