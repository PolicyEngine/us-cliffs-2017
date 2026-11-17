"""Deliberate weighted doubles only; no engine, source data or policy result."""

from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace

import pytest

from cliffs2017.native_pilot import (
    FCC_PATHS,
    PilotError,
    _admitted_document,
    make_fcc_2017_reform,
    run_raise_pilot,
)
from test_commissioned import Fixture, Simulation, Weighted


@pytest.fixture(autouse=True)
def weighted_all(monkeypatch):
    # The established deliberate double lacks this genuine MicroSeries method.
    monkeypatch.setattr(Weighted, "all", lambda self: all(self._data), raising=False)


class PilotFixture(Fixture):
    precision_error = 0
    unselected_change = False
    FCC_nonzero = False

    def factory(self):
        sim = super().factory()
        sim.__class__ = PilotSimulation
        return sim

    def create_branch(self, sim, period, name, increments):
        branch = super().create_branch(sim, period, name, increments)
        branch.__class__ = PilotSimulation
        if self.precision_error:
            branch.data["employment_income"][0] += self.precision_error
        if self.unselected_change:
            branch.data["employment_income"][1] += 1
        return branch

    def account(self, sim, *, period, map_to):
        assert period == 2017 and map_to in {"person", "household"}
        delta = {"A": 0, "B": 0, "C": 0}
        if sim.name != "baseline":
            delta.update(A=600, C=800)
            if self.coupling:
                delta["B"] = 1
        if map_to == "person":
            return self.series([10000 + delta[h] for h in self.households])
        return Weighted(
            [10000 + delta[h] for h in ("A", "B", "C")],
            [2, 3, 5],
            ("A", "B", "C"),
        )

    def audit_object(self):
        calls = []
        return SimpleNamespace(
            snapshot_pilot=lambda sim, selected: calls.append("snapshot"),
            precision_report={"status": "EXACT", "fixture_only": True},
            calls=calls,
        )


class PilotSimulation(Simulation):
    def calc(self, name, *, period, map_to=None):
        if name in {"acp", "ebb"}:
            return Weighted(
                [1 if self.fixture.FCC_nonzero else 0, 0, 0],
                [2, 3, 5],
                ("A", "B", "C"),
            )
        return super().calc(name, period=period, map_to=map_to)


def test_one_per_household_keeps_weighted_totals_and_releases_branch():
    fixture = PilotFixture()
    audit, events = fixture.audit_object(), []
    sim, result = run_raise_pilot(fixture.runtime(), audit, events=events.append)
    assert result["status"] == "engineering_controls_passed"
    assert result["selected_sample_adults"] == 2
    assert result["selected_sample_households"] == 2
    assert result["selected_weighted_adults"] == 7
    assert result["selected_weighted_households"] == 7
    assert result["baseline_household_resources_real_2025"] == 100000
    assert result["raise_household_resources_real_2025"] == 105200
    assert fixture.branch_changes[0][1] == [0, 6]
    assert sim.branches == {}
    assert fixture.base == fixture.original
    assert audit.calls == ["snapshot"]
    assert events == ["native_baseline", "native_raise"]


def test_strict_precision_refusal_retains_diagnostic_without_adopting_tolerance():
    fixture = PilotFixture()
    fixture.precision_error = 0.125
    sim, result = run_raise_pilot(
        fixture.runtime(), fixture.audit_object(), events=lambda stage: None
    )
    assert result["status"] == "precision_refused"
    assert result["selected_earnings_increment_max_deviation_real_2025"] == 0.25
    assert result["precision_tolerance_adopted"] == 0
    assert sim.branches == {}


def test_exact_managed_sum_does_not_hide_raw_input_representability_refusal():
    fixture = PilotFixture()
    audit = fixture.audit_object()
    audit.precision_report = {"status": "precision_refused", "fixture_only": True}
    sim, result = run_raise_pilot(fixture.runtime(), audit, events=lambda stage: None)
    assert result["selected_earnings_increment_max_deviation_real_2025"] == 0
    assert result["status"] == "precision_refused"
    assert result["precision_tolerance_adopted"] == 0
    assert sim.branches == {}


@pytest.mark.parametrize("violation", ["unselected_change", "coupling", "FCC_nonzero"])
def test_consequential_invariant_failure_preserves_baseline_and_releases_branch(
    violation,
):
    fixture = PilotFixture()
    setattr(fixture, violation, True)
    with pytest.raises(PilotError):
        run_raise_pilot(
            fixture.runtime(), fixture.audit_object(), events=lambda stage: None
        )
    assert fixture.created[0].branches == {}
    assert fixture.base == fixture.original


def test_live_context_failure_on_branch_still_releases_owned_branch():
    fixture = PilotFixture()
    fixture.bad_context = True
    with pytest.raises(ValueError, match="context"):
        run_raise_pilot(
            fixture.runtime(), fixture.audit_object(), events=lambda stage: None
        )
    assert fixture.created[0].branches == {}


def test_fcc_reform_changes_only_four_2017_caps():
    class ExplicitReformDouble:
        def modify_parameters(self, update):
            self.update = update

    reform = make_fcc_2017_reform(reform_type=ExplicitReformDouble)()
    reform.apply()
    assert set(reform.update) == set(FCC_PATHS)
    assert len(reform.update) == 4
    assert all(value == {"2017": 0} for value in reform.update.values())


def test_pilot_does_not_call_job_wage_provider():
    fixture = PilotFixture()
    runtime = replace(
        fixture.runtime(),
        hourly_wages_real=lambda sim: pytest.fail("raise-only pilot called job wages"),
    )
    _, result = run_raise_pilot(
        runtime, fixture.audit_object(), events=lambda stage: None
    )
    assert result["status"] == "engineering_controls_passed"


def test_admitted_metadata_nulls_bind_raw_bytes_and_never_allow_missing_facts(tmp_path):
    from cliffs2017.native_materializer import MaterializationError, input_digest

    raw = b'{"calendar_scope": null, "source_dtype": null}\n'
    path = tmp_path / "admitted-contract-metadata.json"
    path.write_bytes(raw)
    record = {"path": str(path), "sha256": sha256(raw).hexdigest()}
    declaration, contract_sha = _admitted_document(record)
    assert declaration == {"calendar_scope": None, "source_dtype": None}
    assert contract_sha == record["sha256"]
    with pytest.raises(MaterializationError, match="Missing/nonfinite input facts"):
        input_digest({"annual_income": None})
    # Even semantically equivalent JSON must keep the admitted byte identity.
    path.write_bytes(raw + b"\n")
    with pytest.raises(PilotError, match="Admitted source/config bytes changed"):
        _admitted_document(record)
