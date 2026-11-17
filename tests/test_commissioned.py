"""Synthetic contract fixtures only; these are not model or population results."""

import math
import operator
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from typing import ClassVar

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from cliffs2017.commissioned import (
    CANDIDATE,
    EARNINGS,
    HOUSEHOLD_FLAG,
    PERSON_FLAG,
    RANK,
    REQUIRED_BINDINGS,
    ContractError,
    RunSpec,
    Runtime,
    prepare_cli_request,
    run,
)


class Weighted:
    """Small weighted-series double; stripping weights raises immediately."""

    def __init__(self, values, mass, index=None):
        self._data = tuple(values)
        self._mass = tuple(mass)
        self.index = tuple(range(len(values))) if index is None else tuple(index)
        assert len(self._data) == len(self._mass) == len(self.index)

    @property
    def weights(self):
        raise AssertionError("The orchestrator must not fetch weights")

    @property
    def values(self):
        raise AssertionError("The orchestrator must not strip series metadata")

    def to_numpy(self):
        raise AssertionError("The orchestrator must not strip series metadata")

    @property
    def dtype(self):
        return "bool" if all(type(x) is bool for x in self._data) else "float"

    def __len__(self):
        return len(self._data)

    def __bool__(self):
        raise AssertionError("Series truth is ambiguous")

    def copy(self):
        return Weighted(self._data, self._mass, self.index)

    def _op(self, other, function):
        if isinstance(other, Weighted):
            assert self.index == other.index and self._mass == other._mass
            values = zip(self._data, other._data)
        else:
            values = ((value, other) for value in self._data)
        return Weighted([function(a, b) for a, b in values], self._mass, self.index)

    def __getitem__(self, mask):
        assert isinstance(mask, Weighted) and mask.index == self.index
        selected = [i for i, keep in enumerate(mask._data) if keep]
        return Weighted(
            [self._data[i] for i in selected],
            [self._mass[i] for i in selected],
            [self.index[i] for i in selected],
        )

    def __add__(self, other):
        return self._op(other, operator.add)

    __radd__ = __add__

    def __sub__(self, other):
        return self._op(other, operator.sub)

    def __rsub__(self, other):
        return self._op(other, lambda a, b: b - a)

    def __mul__(self, other):
        return self._op(other, operator.mul)

    __rmul__ = __mul__

    def __truediv__(self, other):
        return self._op(other, operator.truediv)

    def __eq__(self, other):
        return self._op(other, operator.eq)

    def __lt__(self, other):
        return self._op(other, operator.lt)

    def __le__(self, other):
        return self._op(other, operator.le)

    def __gt__(self, other):
        return self._op(other, operator.gt)

    def __ge__(self, other):
        return self._op(other, operator.ge)

    def __and__(self, other):
        return self._op(other, operator.and_)

    def __or__(self, other):
        return self._op(other, operator.or_)

    def __invert__(self):
        return self._op(False, lambda a, b: not a)

    def abs(self):
        return self._op(0, lambda a, b: abs(a))

    def any(self):
        return any(self._data)

    def max(self):
        return max(self._data)

    def sum(self):
        return sum(value * mass for value, mass in zip(self._data, self._mass))

    def isna(self):
        return self._op(
            0,
            lambda value, _: (
                value is None or (isinstance(value, float) and math.isnan(value))
            ),
        )


class Fixture:
    """Eight synthetic people; A/B/C household masses2/3/5, not survey data."""

    households = ("A", "A", "A", "A", "B", "B", "C", "C")
    mass = (2, 2, 2, 2, 3, 3, 5, 5)
    # Hand-declared real-dollar resource changes; no tax calculation supplies them.
    changes: ClassVar[dict[int, dict[int, int]]] = {
        1000: {0: 600, 1: 500, 2: -10, 6: 800},
        2000: {0: 1800, 1: 1600, 2: 1600, 6: 400},
        5000: {0: 4500, 1: 4000, 2: 4000, 6: -1},
    }

    def __init__(self):
        self.base = {
            "employment_income": [50, 50, 50, 0, 0, 0, 50, 0],
            "self_employment_income": [0] * 8,
            "sstb_self_employment_income": [0] * 8,
            "age": [30, 30, 30, 64.5, 30, 10, 30, 65],
            "is_full_time_student": [False] * 8,
            "is_disabled": [False] * 8,
            "hours_worked_last_week": [20, 20, 20, 0, 0, 0, 20, 0],
            "weekly_hours_worked_before_lsr": [20, 20, 20, 0, 0, 0, 20, 0],
            "weeks_worked": [52, 52, 52, 0, 0, 0, 52, 0],
            "weeks_unemployed": [0, 0, 0, 10, 0, 0, 0, 0],
            "unemployment_compensation": [0, 0, 0, 200, 0, 0, 0, 0],
            "hourly_wage": [1] * 8,
            "is_paid_hourly": [False] * 8,
            "is_self_employed": [False] * 8,
            "has_never_worked": [False] * 8,
        }
        self.created = []
        self.branch_changes = []
        self.bad_context = False
        self.coupling = False
        self.fail_account = False
        self.original = deepcopy(self.base)

    def series(self, values):
        return Weighted(values, self.mass)

    def factory(self):
        sim = Simulation(self, deepcopy(self.base))
        self.created.append(sim)
        return sim

    def create_branch(self, sim, period, name, increments):
        assert period == 2017
        branch = Simulation(self, deepcopy(sim.data), name=name)
        branch.aux = deepcopy(sim.aux)
        for variable, value in increments.items():
            assert isinstance(value, Weighted)
            before = branch.data[variable]
            branch.data[variable] = [a + b for a, b in zip(before, value._data)]
        sim.branches[name] = branch
        selected = [
            i
            for i in range(8)
            if any(branch.data[e][i] != sim.data[e][i] for e in EARNINGS)
        ]
        self.branch_changes.append((name, selected, branch))
        return branch

    def account(self, sim, *, period, map_to):
        assert period == 2017 and map_to == "person"
        if self.fail_account and "raise_" in sim.name:
            raise ContractError("synthetic account refusal")
        delta = dict.fromkeys(self.households, 0)
        selected = next(
            (ids for name, ids, branch in self.branch_changes if branch is sim), []
        )
        for person in selected:
            if "_job_" in sim.name:
                # A: exactlyhalf20800; B: exactlyzero, not strictlynegative.
                amount = 10400 if person == 3 else 0
            else:
                amount = next(
                    values[person]
                    for size, values in self.changes.items()
                    if f"_raise_{size}_" in sim.name
                )
            delta[self.households[person]] = amount
        if self.coupling and selected:
            delta["B"] += 1
        return self.series([10000 + delta[household] for household in self.households])

    def runtime(self):
        context = {"fixture_only": "no model or population"}

        def split(person, period, increase):
            assert period == 2017
            return {"employment_income": increase}

        def audit(base, branch, selected):
            if branch is None:
                assert base.data == self.original
            else:
                assert branch.fixture.households == self.households

        return Runtime(
            factory=self.factory,
            install=lambda sim: None,
            is_weighted=lambda value: isinstance(value, Weighted),
            create_branch=self.create_branch,
            split_raise=split,
            to_native=lambda value: value * Fraction(1, 2),
            to_reference=lambda value: value * 2,
            account=self.account,
            context_for=lambda sim: (
                {} if self.bad_context and "raise_" in sim.name else context
            ),
            hourly_wages_real=lambda sim: self.series([10] * 8),
            audit=audit,
            expected_context=context,
            bindings={name: "a" * 64 for name in REQUIRED_BINDINGS},
            mode="synthetic_test",
        )


class Simulation:
    def __init__(self, fixture, data, name="baseline"):
        self.fixture, self.data, self.name = fixture, data, name
        self.person = self
        self.branches = {}
        self.aux = {}
        self.cached_households = None
        self.cleared = []

    def set_input(self, name, period, value):
        assert period == 2017 and isinstance(value, Weighted)
        if name in {CANDIDATE, PERSON_FLAG}:
            self.aux[name] = value.copy()
        else:
            self.data[name] = list(value._data)

    def delete_arrays(self, name, period):
        assert period == 2017
        self.cleared.append(name)
        if name == HOUSEHOLD_FLAG:
            self.cached_households = None

    def calc(self, name, *, period, map_to=None):
        assert period == 2017
        if name == RANK:
            positions = dict.fromkeys(self.fixture.households, 0)
            rank = []
            for household, selected in zip(
                self.fixture.households, self.aux[CANDIDATE]._data
            ):
                positions[household] += bool(selected)
                rank.append(positions[household] if selected else 0)
            return self.fixture.series(rank)
        if name == HOUSEHOLD_FLAG:
            if self.cached_households is None:
                self.cached_households = {h: False for h in self.fixture.households}
                for h, flag in zip(
                    self.fixture.households, self.aux[PERSON_FLAG]._data
                ):
                    self.cached_households[h] |= flag
            if map_to == "person":
                return self.fixture.series(
                    [self.cached_households[h] for h in self.fixture.households]
                )
            household_mass = dict(zip(self.fixture.households, self.fixture.mass))
            return Weighted(
                [self.cached_households[h] for h in ("A", "B", "C")],
                [household_mass[h] for h in ("A", "B", "C")],
                ("A", "B", "C"),
            )
        return self.fixture.series(self.data[name])


def test_exact_thresholds_all_workers_and_member_union():
    fixture = Fixture()
    result = run(RunSpec("case"), fixture.runtime())
    assert result["status"] == "SYNTHETIC_TEST_DOUBLE_NOT_AN_ESTIMATE"
    # The third worker in A supplies the strict loss; a top-two cap misses it.
    main_rows = result["tables"]["1000"]
    assert main_rows["0"]["raise"] == {"adults": 2, "households": 2, "members": 8}
    assert main_rows["0"]["job"]["members"] == 0
    assert main_rows["0.50"]["union"]["members"] == 14  # A4*2+B2*3, once each.
    assert main_rows["0.50"]["additional_members_outside_strict_households"] == 6
    assert main_rows["0.50"]["additional_households_outside_strict_households"] == 3
    assert main_rows["0.60"]["raise"]["adults"] == 4  # 500/1000, not600/1000.
    assert (
        main_rows["0.50"]["job"]["adults"] == 3
    )  # B0 qualifies; A0.5 equality does not.
    assert result["tables"]["2000"]["0.20"]["raise"]["adults"] == 0  # C0.2 equality.
    assert fixture.created[0].branches == {}
    assert fixture.base == fixture.original
    assert HOUSEHOLD_FLAG in fixture.created[0].cleared


def test_different_raise_sizes_need_not_be_nested():
    result = run(RunSpec("sizes"), Fixture().runtime())
    # Source-declared synthetic outcome: A loses on1000; only C loses on5000.
    assert result["tables"]["1000"]["0"]["raise"]["members"] == 8
    assert result["tables"]["2000"]["0"]["raise"]["members"] == 0
    assert result["tables"]["5000"]["0"]["raise"]["members"] == 10
    assert result["tables"]["2000"]["0.50"]["union"]["members"] == 16


def test_full_time_job_units_and_fractional_age_boundary():
    fixture = Fixture()
    result = run(RunSpec("units"), fixture.runtime())
    jobs = [
        (ids, branch) for name, ids, branch in fixture.branch_changes if "_job_" in name
    ]
    assert len(jobs) == 1 and jobs[0][0] == [3, 4]  # Includes64.5, excludes65.
    branch = jobs[0][1]
    for person in (3, 4):
        assert (
            branch.data["employment_income"][person] == 10400
        )  # Half-native20800real.
        assert branch.data["hourly_wage"][person] == 5
        assert branch.data["weeks_worked"][person] == 52
        assert branch.data["hours_worked_last_week"][person] == 40
        assert branch.data["unemployment_compensation"][person] == 0
        assert branch.data["is_paid_hourly"][person] is True
    assert branch.data["employment_income"][0] == 50
    assert (
        sum(
            row["sample_adults"]
            for row in result["scenario_audit"]
            if "raise_1000" in row["branch"]
        )
        == 4
    )


def test_job_requires_zero_each_component_and_observable_exclusions():
    fixture = Fixture()
    fixture.base["employment_income"][4] = 10
    fixture.base["self_employment_income"][4] = -10  # Netzero is not zeroeach.
    fixture.base["is_full_time_student"][3] = True
    fixture.original = deepcopy(fixture.base)
    result = run(RunSpec("none"), fixture.runtime())
    assert result["tables"]["1000"]["0.60"]["job"]["adults"] == 0


@pytest.mark.parametrize("change", ["context", "account", "coupling"])
def test_branch_refusal_preserves_failure_and_releases_only_own_branch(change):
    fixture = Fixture()
    if change == "context":
        fixture.bad_context = True
    if change == "account":
        fixture.fail_account = True
    if change == "coupling":
        fixture.coupling = True
    runtime = fixture.runtime()
    with pytest.raises(ContractError):
        run(RunSpec("refusal"), runtime)
    assert fixture.created[0].branches == {}
    assert fixture.base == fixture.original


def test_missing_inputs_and_unweighted_account_refuse():
    fixture = Fixture()
    fixture.base["is_disabled"][4] = None
    with pytest.raises(ContractError, match="Missing"):
        run(RunSpec("missing"), fixture.runtime())
    runtime = Fixture().runtime()
    with pytest.raises(ContractError, match="weighted"):
        run(RunSpec("unweighted"), replace(runtime, account=lambda *a, **k: [1] * 8))


def test_scope_and_provenance_refuse_before_factory():
    fixture = Fixture()
    with pytest.raises(ContractError, match="law2017"):
        run(RunSpec("wrong_year", law_year=2025), fixture.runtime())
    with pytest.raises(ContractError, match="receipt"):
        run(RunSpec("no_anchor"), replace(fixture.runtime(), bindings={}))
    assert fixture.created == []


def test_cli_decision_refuses_fake_or_missing_native_capabilities(tmp_path):
    # Feed argv as data to the decision function, never execute the CLI writer.
    output = tmp_path / "not_an_estimate.json"
    with pytest.raises(SystemExit) as absent:
        prepare_cli_request(["--run-id", "cli", "--out", str(output)])
    assert absent.value.code == 2 and not output.exists()
    with pytest.raises(SystemExit) as fake:
        prepare_cli_request(
            ["--run-id", "cli", "--out", str(output)], runtime=Fixture().runtime()
        )
    assert fake.value.code == 2 and not output.exists()


@settings(max_examples=30, deadline=None, derandomize=True, database=None)
@given(
    masses=st.tuples(*(st.integers(min_value=1, max_value=100) for _ in range(3))),
    amount=st.sampled_from((1000, 2000, 5000)),
    cutoff=st.sampled_from(
        (Fraction(3, 5), Fraction(1, 2), Fraction(1, 5), Fraction(0))
    ),
)
def test_weighted_union_and_disjoint_additional_counts_match_set_reference(
    masses, amount, cutoff
):
    """Synthetic outcomes; independently count sets for arbitrary survey masses."""
    fixture = Fixture()
    household_mass = dict(zip(("A", "B", "C"), masses))
    fixture.mass = tuple(household_mass[household] for household in fixture.households)
    result = run(RunSpec("property"), fixture.runtime())
    key = {
        Fraction(3, 5): "0.60",
        Fraction(1, 2): "0.50",
        Fraction(1, 5): "0.20",
        Fraction(0): "0",
    }[cutoff]
    row = result["tables"][str(amount)][key]

    # This reference enumerates people and households directly. It does not
    # call the orchestrator's projection, ranking or counting helpers.
    raises = {
        person
        for person, change in Fixture.changes[amount].items()
        if Fraction(change, amount) < cutoff
    }
    jobs = {
        person
        for person, ratio in ((3, Fraction(1, 2)), (4, Fraction(0)))
        if ratio < cutoff
    }
    strict_people = {
        person for person, change in Fixture.changes[amount].items() if change < 0
    }
    strict_households = {fixture.households[person] for person in strict_people}
    for label, people in (("raise", raises), ("job", jobs), ("union", raises | jobs)):
        households = {fixture.households[person] for person in people}
        expected = {
            "adults": sum(fixture.mass[person] for person in people),
            "households": sum(household_mass[h] for h in households),
            "members": sum(
                fixture.mass[person]
                for person, household in enumerate(fixture.households)
                if household in households
            ),
        }
        assert row[label] == expected
    additional = {
        fixture.households[person] for person in raises | jobs
    } - strict_households
    assert row["additional_households_outside_strict_households"] == sum(
        household_mass[h] for h in additional
    )
    assert row["additional_members_outside_strict_households"] == sum(
        fixture.mass[person]
        for person, household in enumerate(fixture.households)
        if household in additional
    )
