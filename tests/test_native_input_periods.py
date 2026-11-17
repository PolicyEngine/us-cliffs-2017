"""Source/memory regressions only; no real Core/model/data qualification."""

import json

import pytest

from cliffs2017 import native_pilot
from cliffs2017.native_observers import (
    NativeObservers,
    ObservationError,
    _signature,
    input_period_refusal_metadata,
)


class MemoryPeriod:
    def __init__(self, label):
        self.label = label

    def __str__(self):
        return self.label


class MemorySimulation:
    def __init__(self, labels, value):
        self.periods = tuple(MemoryPeriod(label) for label in labels)
        self.value = value
        self.reads = []

    def _get_set_input_periods(self, name):
        self.period_name = name
        return self.periods

    def _get_recorded_input_array(self, name, period):
        self.reads.append((name, period))
        return self.value


def memory_observer(labels, value=None, *, name="flag"):
    observer = object.__new__(NativeObservers)
    observer.specs = {name: object()}
    observer.core_methods = {
        key: getattr(MemorySimulation, key)
        for key in ("_get_set_input_periods", "_get_recorded_input_array")
    }
    return observer, MemorySimulation(labels, value)


@pytest.mark.parametrize(
    "stored,requested",
    [
        ("ETERNITY", "eternity"),
        ("ETERNITY", "ETERNITY"),
        ("eternity", "eternity"),
        ("2017", "2017"),
        ("2017-02", "2017-02"),
        ("2017-02-03", "2017-02-03"),
    ],
)
def test_one_matching_period_returns_the_actual_recorded_object(stored, requested):
    raw = object()
    observer, simulation = memory_observer([stored], raw)
    assert observer._raw(simulation, "flag", requested) is raw
    assert simulation.reads == [("flag", simulation.periods[0])]


@pytest.mark.parametrize(
    "stored,requested",
    [
        ("2018", "2017"),
        ("2017-03", "2017-02"),
        ("2017-02-04", "2017-02-03"),
        ("2017", "2017-01"),
        ("2017-01", "2017"),
        ("EtErNiTy", "eternity"),
    ],
)
def test_unrelated_periods_are_never_accepted(stored, requested):
    observer, simulation = memory_observer([stored], object())
    with pytest.raises(ObservationError):
        observer._raw(simulation, "flag", requested)
    assert simulation.reads == []


@pytest.mark.parametrize(
    "labels,requested",
    [
        (["2017", "2017"], "2017"),
        (["2017-01", "2017-01"], "2017-01"),
        (["ETERNITY", "eternity"], "eternity"),
    ],
)
def test_duplicates_still_refuse_without_reading_a_value(labels, requested):
    observer, simulation = memory_observer(labels, object())
    with pytest.raises(ObservationError) as caught:
        observer._raw(simulation, "flag", requested)
    assert input_period_refusal_metadata(caught.value)["matching_period_count"] == 2
    assert simulation.reads == []


def test_nonstring_request_is_not_coerced_to_a_matching_year():
    observer, simulation = memory_observer(["2017"], object())
    with pytest.raises(ObservationError) as caught:
        observer._raw(simulation, "flag", 2017)
    assert input_period_refusal_metadata(caught.value) is None
    assert simulation.reads == []


def test_absent_recorded_array_does_not_fall_back_to_a_calculation():
    observer, simulation = memory_observer(["2017"], None)
    assert observer._raw(simulation, "flag", "2017") is None
    with pytest.raises(ObservationError):
        _signature(None)


def test_unknown_contract_name_does_not_enter_the_metadata_capsule():
    observer, simulation = memory_observer([])
    with pytest.raises(ObservationError) as caught:
        observer._raw(simulation, "unbound_symbol", "2017")
    assert input_period_refusal_metadata(caught.value) is None


def test_absent_supplied_period_does_not_use_a_default_value():
    observer, simulation = memory_observer([], object())
    with pytest.raises(ObservationError) as caught:
        observer._raw(simulation, "flag", "2017")
    metadata = input_period_refusal_metadata(caught.value)
    assert metadata["available_periods"] == []
    assert metadata["matching_period_count"] == 0
    assert simulation.reads == []


def test_period_metadata_is_bounded_and_reports_omitted_count_honestly():
    labels = [str(year) for year in range(2000, 2041)]
    observer, simulation = memory_observer(labels)
    with pytest.raises(ObservationError) as caught:
        observer._raw(simulation, "flag", "1999")
    metadata = input_period_refusal_metadata(caught.value)
    assert metadata["available_period_count"] == 41
    assert metadata["available_periods"] == labels[:32]
    assert metadata["available_periods_truncated"] is True
    metadata["available_periods"].append("9999")
    assert len(input_period_refusal_metadata(caught.value)["available_periods"]) == 32


def test_unrecognized_period_text_is_not_copied_to_the_capsule():
    observer, simulation = memory_observer(["PRIVATE_SENTINEL_DETAIL"])
    with pytest.raises(ObservationError) as caught:
        observer._raw(simulation, "flag", "2017")
    assert input_period_refusal_metadata(caught.value) is None


def test_method_identity_requirement_is_unchanged():
    observer, simulation = memory_observer(["ETERNITY"], object())
    observer.core_methods["_get_set_input_periods"] = lambda *args: []
    with pytest.raises(ObservationError, match="method changed") as caught:
        observer._raw(simulation, "flag", "eternity")
    assert input_period_refusal_metadata(caught.value) is None


@pytest.mark.parametrize(
    "name",
    [
        "social_security_retirement",
        "social_security_disability",
        "social_security_survivors",
        "social_security_dependents",
    ],
)
def test_four_ssa_alias_route_uses_reported_name_and_actual_period_object(name):
    raw = object()
    observer, simulation = memory_observer(["2017"], raw, name=name)
    assert observer._raw(simulation, name, "2017") is raw
    assert simulation.period_name == name + "_reported"
    assert simulation.reads == [(name + "_reported", simulation.periods[0])]


def test_main_refusal_contains_only_safe_input_metadata(tmp_path, monkeypatch):
    observer, simulation = memory_observer(["ETERNITY"], name="flag")
    # A real missing month remains a refusal; use it to exercise the capsule.
    with pytest.raises(ObservationError) as caught:
        observer._raw(simulation, "flag", "2017-01")
    error = caught.value
    error.args = ("PRIVATE_SENTINEL_DETAIL",)

    def refuse(*args, **kwargs):
        raise error

    monkeypatch.setattr(native_pilot, "assemble_and_run", refuse)
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"schema_version": native_pilot.SCHEMA, "raise_real_2025": 1000})
    )
    output = tmp_path / "output"
    assert native_pilot.main(["--config", str(config), "--output", str(output)]) == 1
    text = (output / "pilot-result.json").read_text()
    result = json.loads(text)
    assert "PRIVATE_SENTINEL_DETAIL" not in text
    assert result["status"] == "refused"
    assert result["input_period_metadata"] == {
        "variable": "flag",
        "read_variable": "flag",
        "requested_period": "2017-01",
        "available_periods": ["ETERNITY"],
        "available_period_count": 1,
        "available_periods_truncated": False,
        "matching_period_count": 0,
    }


def test_other_failures_have_no_input_metadata():
    assert input_period_refusal_metadata(ObservationError("unrelated")) is None
    unrelated = ValueError("private")
    unrelated._input_period_metadata = {"private": "PRIVATE_SENTINEL_DETAIL"}
    assert input_period_refusal_metadata(unrelated) is None
