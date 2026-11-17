"""Synthetic interface/arithmetic checks; no engine or real inputs."""

import struct
from types import SimpleNamespace

import pytest

from cliffs2017.health_valuation import (
    CHIP_UNIT,
    CHIP_VALUE,
    HEALTH_INPUTS,
    HEALTH_OUTPUTS,
    MEDICAID_UNIT,
    MEDICAID_VALUE,
    MEDICARE_GROSS_UNIT,
    MEDICARE_NET_VALUE,
    NATIVE_PER_REFERENCE_DOLLAR,
    REFERENCE_READS,
    ReferenceHealthCapture,
    install_health_anchors,
    make_health_valuation_reform,
    make_reference_health_unit_reform,
)
from cliffs2017.native_witness import WitnessError


class Float32:
    pass


class Float64:
    pass


class Array:
    def __init__(self, values, *, dtype=Float32):
        self.values = list(values)
        self.shape = (len(values),)
        self.dtype = SimpleNamespace(
            kind="f", str="<f4" if dtype is Float32 else "<f8", type=dtype
        )

    def tolist(self):
        return list(self.values)

    def copy(self):
        return Array(self.values, dtype=self.dtype.type)

    def tobytes(self, order):
        return struct.pack(
            "<" + ("f" if self.dtype.type is Float32 else "d") * len(self.values),
            *self.values,
        )

    def astype(self, dtype, *, copy):
        assert copy
        return Array(
            self.values, dtype=Float64 if dtype in ("float64", Float64) else Float32
        )

    def __mul__(self, factor):
        return Array([value * factor for value in self.values], dtype=self.dtype.type)


class Variable:
    defined_for = None


class Reform:
    def __init__(self):
        self.variables = {}
        self.apply()

    def add_variable(self, variable):
        assert variable.__name__ not in self.variables
        self.variables[variable.__name__] = variable


API = SimpleNamespace(
    Variable=Variable,
    Person=SimpleNamespace(key="person"),
    YEAR="year",
    USD="USD",
    max_=max,
)


def reform():
    return make_health_valuation_reform(model_api=API, reform_type=Reform)()


class Period:
    unit = "year"

    def __str__(self):
        return "2017"


class Simulation:
    def __init__(self):
        classes = reform().variables
        self.tax_benefit_system = SimpleNamespace(
            variables={
                name: SimpleNamespace(
                    entity=variable.entity,
                    definition_period="year",
                    value_type=float,
                    defined_for=variable.defined_for,
                    is_neutralized=False,
                    dtype=Float32,
                    get_formula=lambda period: None,
                )
                for name, variable in classes.items()
                if name in HEALTH_INPUTS
            }
        )
        self.populations = {"person": SimpleNamespace(count=2)}
        self.inputs, self.writes = {}, []
        self.period = Period()
        self.corrupt = False

    def _get_set_input_periods(self, name):
        return (self.period,) if name in self.inputs else ()

    def _get_recorded_input_array(self, name, period):
        assert period is self.period  # Actual CorePeriod, never a fabricated string.
        return self.inputs[name]

    def set_input(self, name, period, value):
        assert period == "2017"
        self.writes.append(name)
        self.inputs[name] = Array([0, 0]) if self.corrupt else value


def arrays():
    return {name: Array([100, 200]) for name in HEALTH_INPUTS}


def test_reference_helpers_retain_actual_formula_objects_without_masks():
    def chip(person, period, parameters):
        return 17

    def medicare(person, period, parameters):
        return 23

    result = make_reference_health_unit_reform(
        chip_formula=chip,
        medicare_gross_formula=medicare,
        model_api=API,
        reform_type=Reform,
    )()
    assert set(result.variables) == {CHIP_UNIT, MEDICARE_GROSS_UNIT}
    for name, formula in [(CHIP_UNIT, chip), (MEDICARE_GROSS_UNIT, medicare)]:
        variable = result.variables[name]
        assert variable.__dict__["formula"] is formula
        assert variable.defined_for is None
        assert variable.entity is API.Person
    assert REFERENCE_READS[MEDICAID_UNIT] == "medicaid_cost_if_enrolled"


@pytest.mark.parametrize("bad", [None, 1, "formula"])
def test_reference_formula_cannot_come_from_a_name_or_missing_value(bad):
    with pytest.raises(TypeError):
        make_reference_health_unit_reform(
            chip_formula=bad,
            medicare_gross_formula=lambda *args: 0,
            model_api=API,
            reform_type=Reform,
        )


def test_native_reform_adds_only_account_variables_and_keeps_live_masks():
    variables = reform().variables
    assert set(variables) == HEALTH_INPUTS | HEALTH_OUTPUTS
    assert variables[MEDICAID_VALUE].defined_for == "medicaid_enrolled"
    assert variables[CHIP_VALUE].defined_for == "chip_enrolled"
    assert variables[MEDICARE_NET_VALUE].defined_for == "medicare_enrolled"
    assert variables[MEDICAID_VALUE].adds == [MEDICAID_UNIT]
    assert variables[CHIP_VALUE].adds == [CHIP_UNIT]
    assert all("formula" not in variables[name].__dict__ for name in HEALTH_INPUTS)


@pytest.mark.parametrize(
    "gross,part_a,part_b,share,average_d,own_d,expected",
    [
        (1000, 100, 200, 0.5, 60, 50, 620),
        (1000, 100, 250, 0.5, 60, 50, 570),
        (1000, 100, 200, 0.25, 60, 50, 635),
        (1000, 100, 200, 0.5, 60, 100, 570),
        (100, 100, 200, 0.5, 60, 50, 0),
    ],
)
def test_net_medicare_retains_native_offsets_once_and_floors_at_zero(
    gross, part_a, part_b, share, average_d, own_d, expected
):
    values = {
        MEDICARE_GROSS_UNIT: gross,
        "base_part_a_premium": part_a,
        "gross_medicare_part_b_premium_if_enrolled": part_b,
        "income_adjusted_part_d_premium_surcharge": own_d,
    }
    reads = []

    def person(name, period):
        reads.append((name, period))
        return values[name]

    p = SimpleNamespace(
        calibration=SimpleNamespace(
            gov=SimpleNamespace(
                hhs=SimpleNamespace(
                    medicare=SimpleNamespace(
                        part_d=SimpleNamespace(
                            enrollment_share=share, premiums_per_enrollee=average_d
                        )
                    )
                )
            )
        )
    )
    formula = reform().variables[MEDICARE_NET_VALUE].__dict__["formula"]
    assert formula(person, "2017", lambda period: p) == expected
    assert len(reads) == 4 and {name for name, _ in reads} == set(values)
    assert all(period == "2017" for _, period in reads)
    assert not any("msp" in name or "net_premium" in name for name, _ in reads)


def test_install_preserves_values_and_returns_live_witness_expectations():
    sim, inputs = Simulation(), arrays()
    fixed = install_health_anchors(sim, native_arrays=inputs)
    assert {item.name for item in fixed} == HEALTH_INPUTS
    assert all(
        item.period == "2017" and item.purpose == "health_unit_value" for item in fixed
    )
    assert all(sim.inputs[name] is inputs[name] for name in HEALTH_INPUTS)
    assert all(value.tolist() == [100, 200] for value in sim.inputs.values())


@pytest.mark.parametrize("period", [2025, "2017", True])
def test_install_refuses_a_wrong_clock_before_writes(period):
    sim = Simulation()
    with pytest.raises(WitnessError):
        install_health_anchors(sim, native_arrays=arrays(), period=period)
    assert sim.writes == []


@pytest.mark.parametrize(
    "change", ["missing", "extra", "negative", "nonfinite", "length", "dtype"]
)
def test_all_input_preconditions_precede_any_setter(change):
    sim, inputs = Simulation(), arrays()
    name = max(HEALTH_INPUTS)
    if change == "missing":
        del inputs[name]
    elif change == "extra":
        inputs["unknown"] = Array([1, 2])
    elif change == "negative":
        inputs[name] = Array([-1, 0])
    elif change == "nonfinite":
        inputs[name] = Array([float("nan"), 0])
    elif change == "length":
        inputs[name] = Array([1])
    else:
        inputs[name] = Array([1, 2], dtype=Float64)
    with pytest.raises(WitnessError):
        install_health_anchors(sim, native_arrays=inputs)
    assert sim.writes == []


def test_install_refuses_to_overwrite_preexisting_anchors():
    sim = Simulation()
    sim.inputs[MEDICAID_UNIT] = Array([1, 2])
    with pytest.raises(WitnessError):
        install_health_anchors(sim, native_arrays=arrays())
    assert sim.writes == []


def test_installer_cannot_bless_a_setter_cast_or_changed_array():
    sim = Simulation()
    sim.corrupt = True
    with pytest.raises(WitnessError, match="changed"):
        install_health_anchors(sim, native_arrays=arrays())


@pytest.mark.parametrize(
    "attribute,value",
    [
        ("defined_for", "medicaid_enrolled"),
        ("is_neutralized", True),
        ("value_type", int),
    ],
)
def test_installer_refuses_masked_or_changed_input_definitions(attribute, value):
    sim = Simulation()
    setattr(sim.tax_benefit_system.variables[MEDICAID_UNIT], attribute, value)
    with pytest.raises(WitnessError):
        install_health_anchors(sim, native_arrays=arrays())
    assert sim.writes == []


class MicroSeries:
    __module__ = "microdf.synthetic_test_double"

    def __init__(self, array):
        self.array = array
        self.weights = (2, 3)

    def to_numpy(self, *, copy):
        raise AssertionError("Do not strip the managed series")

    def __len__(self):
        return len(self.array.values)

    def __eq__(self, array):
        result = MicroSeries(
            Array([a == b for a, b in zip(self.array.values, array.values)])
        )
        result.weights = self.weights
        return result

    def all(self):
        assert self.weights == (2, 3)
        return all(self.array.values)


class ReferencePeriod:
    unit = "year"

    def __str__(self):
        return "2025"


class ReferenceHolder:
    def __init__(self, array):
        self.array = array
        self.period = ReferencePeriod()

    def get_known_periods(self, branch_name):
        assert branch_name == "reference_owned"
        return [self.period] if self.array is not None else []

    def get_array(self, period, branch_name):
        assert period is self.period
        assert branch_name == "reference_owned"
        return self.array


def source_formula(*args):
    raise AssertionError("The fake API never runs the country's formula")


class ReferenceSimulation(Simulation):
    def __init__(self):
        super().__init__()
        self.tax_benefit_system.variables = {
            name: SimpleNamespace(
                defined_for=None,
                entity=API.Person,
                definition_period="year",
                is_neutralized=False,
                get_formula=lambda period: source_formula,
            )
            for name in REFERENCE_READS.values()
        }
        self.reads = []
        self.result = MicroSeries(Array([100, 200]))
        self.branch_name = "reference_owned"
        self.cache_mode = "matching"

    def calc(self, name, *, period, map_to):
        self.reads.append((name, period, map_to))
        return self.result

    def get_holder(self, name):
        assert name in REFERENCE_READS.values()
        array = self.result.array
        if self.cache_mode == "missing":
            array = None
        elif self.cache_mode == "misaligned":
            array = Array([array.values[1], array.values[0]])
        return ReferenceHolder(array)


def capture():
    return ReferenceHealthCapture(
        reference_formulas={name: source_formula for name in REFERENCE_READS.values()},
        person_count=2,
    )


def test_reference_capture_reads_once_and_converts_once_for_native_installation():
    collect, reference, native = capture(), ReferenceSimulation(), Simulation()
    collect(reference)
    assert set(reference.reads) == {
        (name, 2025, "person") for name in REFERENCE_READS.values()
    }
    assert len(reference.reads) == 3
    assert collect.receipt["person_count"] == 2
    assert "native_year" not in collect.receipt
    fixed = collect.prepare_health(native)
    assert len(fixed) == 3
    for value in native.inputs.values():
        assert value.tolist() == pytest.approx(
            [
                100 * float(NATIVE_PER_REFERENCE_DOLLAR),
                200 * float(NATIVE_PER_REFERENCE_DOLLAR),
            ]
        )
        assert value.dtype.type is Float32
    assert collect.receipt["native_per_reference_dollar"] == (245120, 321943)
    with pytest.raises(WitnessError, match="once"):
        collect(reference)
    with pytest.raises(WitnessError, match="one native"):
        collect.prepare_health(Simulation())


@pytest.mark.parametrize("change", ["mask", "supplied", "formula", "count"])
def test_reference_source_preconditions_refuse_before_any_read(change):
    collect, reference = capture(), ReferenceSimulation()
    name = next(iter(REFERENCE_READS.values()))
    if change == "mask":
        reference.tax_benefit_system.variables[name].defined_for = "is_chip_eligible"
    elif change == "supplied":
        reference.inputs[name] = Array([1, 2])
    elif change == "formula":
        reference.tax_benefit_system.variables[name].get_formula = lambda period: (
            lambda *args: 999
        )
    else:
        reference.populations["person"].count = 1
    with pytest.raises(WitnessError):
        collect(reference)
    assert reference.reads == []


@pytest.mark.parametrize("change", ["negative", "nonfinite", "length", "unweighted"])
def test_invalid_reference_values_never_produce_an_anchor_receipt(change):
    collect, reference = capture(), ReferenceSimulation()
    if change == "unweighted":
        reference.result = Array([100, 200])
    else:
        values = {"negative": [-1, 2], "nonfinite": [float("inf"), 2], "length": [1]}[
            change
        ]
        reference.result = MicroSeries(Array(values))
    with pytest.raises(WitnessError):
        collect(reference)
    with pytest.raises(WitnessError, match="not been captured"):
        _ = collect.receipt


def test_reference_array_mutation_refuses_before_native_setter():
    collect, reference, native = capture(), ReferenceSimulation(), Simulation()
    collect(reference)
    collect._arrays[CHIP_UNIT].values[0] = 999
    with pytest.raises(WitnessError, match="changed"):
        collect.prepare_health(native)
    assert native.writes == []


def test_missing_capture_cannot_install_or_infer_zero_units():
    collect, native = capture(), Simulation()
    with pytest.raises(WitnessError, match="Capture"):
        collect.prepare_health(native)
    assert native.writes == []


def test_source_produced_zeros_remain_explicit_diagnostics_without_imputation():
    collect, reference = capture(), ReferenceSimulation()
    reference.result = MicroSeries(Array([0, 200]))
    collect(reference)
    assert dict(collect.receipt["zero_unit_cells"]) == {
        name: 1 for name in HEALTH_INPUTS
    }
    native = Simulation()
    collect.prepare_health(native)
    assert all(value.tolist()[0] == 0 for value in native.inputs.values())


@pytest.mark.parametrize("mode", ["missing", "misaligned"])
def test_reference_raw_cache_must_exist_and_match_the_managed_projection(mode):
    collect, reference = capture(), ReferenceSimulation()
    reference.cache_mode = mode
    with pytest.raises(WitnessError, match="cache"):
        collect(reference)
    with pytest.raises(WitnessError, match="not been captured"):
        _ = collect.receipt
