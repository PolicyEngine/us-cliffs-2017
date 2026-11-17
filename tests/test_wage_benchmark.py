"""Benchmark-input checks on invented people, never earnings estimates."""

from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from test_commissioned import Weighted

from cliffs2017.wage_benchmark import (
    NATIVE_PER_REFERENCE_DOLLAR,
    STATE_CODES,
    WageBenchmark,
)


class FakeSimulation:
    def __init__(self, states, counties, masses=None):
        masses = masses or tuple(range(1, len(states) + 1))
        self.inputs = {
            "state_code": Weighted(states, masses),
            "county_fips": Weighted(counties, masses),
        }
        self.calls = []

    def calc(self, name, *, period, map_to):
        self.calls.append((name, period, map_to))
        return self.inputs[name]


def read(sim, **kwargs):
    return WageBenchmark().hourly_wages_real(
        sim, is_weighted=lambda value: isinstance(value, Weighted), **kwargs
    )


# Independent transcriptions of the covered-employer column in Hawaii Data
# Book2016 Table12.43, with the explicit CA26+ and MaineJanuary7 choices.
EXPECTED = {
    "AL": 7.25,
    "AK": 9.8,
    "AZ": 10,
    "AR": 8.5,
    "CA": 10.5,
    "CO": 9.3,
    "CT": 10.1,
    "DE": 8.25,
    "FL": 8.1,
    "GA": 7.25,
    "HI": 9.25,
    "ID": 7.25,
    "IL": 8.25,
    "IN": 7.25,
    "IA": 7.25,
    "KS": 7.25,
    "KY": 7.25,
    "LA": 7.25,
    "ME": 9,
    "MD": 8.75,
    "MA": 11,
    "MI": 8.9,
    "MN": 9.5,
    "MS": 7.25,
    "MO": 7.7,
    "MT": 8.15,
    "NE": 9,
    "NV": 8.25,
    "NH": 7.25,
    "NJ": 8.44,
    "NM": 7.5,
    "NY": 9.7,
    "NC": 7.25,
    "ND": 7.25,
    "OH": 8.15,
    "OK": 7.25,
    "OR": 9.75,
    "PA": 7.25,
    "RI": 9.6,
    "SC": 7.25,
    "SD": 8.65,
    "TN": 7.25,
    "TX": 7.25,
    "UT": 7.25,
    "VT": 10,
    "VA": 7.25,
    "WA": 11,
    "WV": 8.75,
    "WI": 7.25,
    "WY": 7.25,
    "DC": 11.5,
}


def test_all_51_state_benchmarks_convert_once_and_retain_weights():
    assert set(EXPECTED) == STATE_CODES
    states = sorted(EXPECTED)
    counties = [
        "36001" if state == "NY" else "41039" if state == "OR" else ""
        for state in states
    ]
    sim = FakeSimulation(states, counties)
    result = read(sim)
    assert result._data == pytest.approx(
        tuple(EXPECTED[state] / float(NATIVE_PER_REFERENCE_DOLLAR) for state in states)
    )
    assert result._mass == sim.inputs["state_code"]._mass
    assert sim.calls == [
        ("state_code", 2017, "person"),
        ("county_fips", 2017, "person"),
    ]


@pytest.mark.parametrize(
    "state,county,expected",
    [
        ("NY", "36005", 11),
        ("NY", "36047", 11),
        ("NY", "36061", 11),
        ("NY", "36081", 11),
        ("NY", "36085", 11),
        ("NY", "36059", 10),
        ("NY", "36103", 10),
        ("NY", "36119", 10),
        ("NY", "36001", 9.7),
        ("OR", "41001", 9.5),
        ("OR", "41069", 9.5),
        ("OR", "41051", 9.75),
    ],
)
def test_regional_boundary_benchmarks(state, county, expected):
    assert read(FakeSimulation([state], [county]))._data == pytest.approx(
        (expected / float(NATIVE_PER_REFERENCE_DOLLAR),)
    )


@pytest.mark.parametrize(
    "state,county",
    [
        ("NY", ""),
        ("OR", ""),
        ("NY", "41001"),
        ("OR", "36005"),
        ("NY", "36999"),
        ("OR", "41999"),
        ("XX", "00000"),
        (None, "36005"),
        ("NY", None),
    ],
)
def test_unknown_geography_never_uses_a_default_county_or_wage(state, county):
    with pytest.raises(ValueError):
        read(FakeSimulation([state], [county]))


def test_wrong_law_clock_and_unweighted_geography_refuse():
    sim = FakeSimulation(["CA"], [""])
    with pytest.raises(ValueError):
        read(sim, period=2025)
    assert sim.calls == []
    sim.calc = lambda *args, **kwargs: ["CA"]
    with pytest.raises(TypeError):
        read(sim)


@settings(max_examples=30, database=None, deadline=None, derandomize=True)
@given(
    st.lists(
        st.tuples(
            st.sampled_from(
                (
                    ("CA", "", Fraction("10.50")),
                    ("NY", "36005", Fraction(11)),
                    ("NY", "36059", Fraction(10)),
                    ("NY", "36001", Fraction("9.70")),
                    ("OR", "41001", Fraction("9.50")),
                    ("OR", "41051", Fraction("9.75")),
                )
            ),
            st.integers(min_value=1, max_value=100),
        ),
        min_size=1,
        max_size=20,
    )
)
def test_mixed_households_preserve_each_declared_rate_and_weight(people):
    states = [person[0][0] for person in people]
    counties = [person[0][1] for person in people]
    masses = tuple(person[1] for person in people)
    result = read(FakeSimulation(states, counties, masses))
    expected = tuple(
        float(person[0][2] / NATIVE_PER_REFERENCE_DOLLAR) for person in people
    )
    assert result._data == pytest.approx(expected)
    assert result._mass == masses
