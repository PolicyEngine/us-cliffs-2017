"""Run the commissioned scenarios through injected, authenticated native tools.

This module defines no tax or benefit rules and imports no country model. Its
caller supplies the managed factory, actual native branching helpers and the
source-bound government-transfer account. Synthetic fixtures remain labelled
test doubles; the standalone CLI refuses to invent these capabilities.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

EARNINGS = (
    "employment_income",
    "self_employment_income",
    "sstb_self_employment_income",
)
CUTOFFS = (("0.60", 3, 5), ("0.50", 1, 2), ("0.20", 1, 5), ("0", 0, 1))
CANDIDATE = "cliffs_candidate_mask"
RANK = "cliffs_candidate_rank"
PERSON_FLAG = "cliffs_person_flag"
HOUSEHOLD_FLAG = "cliffs_household_flag"
REQUIRED_BINDINGS = (
    "preparation_sha256",
    "account_sha256",
    "price_anchor_sha256",
    "full_sample_households_sha256",
    "native_controls_sha256",
    "baseline_sha256",
    "takeup_draws_sha256",
)


class ContractError(ValueError):
    """A required native capability, scope or invariant is absent."""


@dataclass(frozen=True)
class RunSpec:
    run_id: str
    raises: tuple[int, ...] = (1000, 2000, 5000)
    law_year: int = 2017
    reference_year: int = 2025
    currency_year: int = 2025

    def validate(self):
        if (self.law_year, self.reference_year, self.currency_year) != (
            2017,
            2025,
            2025,
        ):
            raise ContractError(
                "This commission requires law2017/reference2025/real2025 dollars"
            )
        if self.raises != (1000, 2000, 5000):
            raise ContractError("Bind the main1000 and separate2000/5000 sensitivities")
        if not re.fullmatch(r"[a-z0-9_]{1,48}", self.run_id):
            raise ContractError("Supply a bounded unique run ID")


@dataclass(frozen=True)
class Runtime:
    """The integration owner supplies real capabilities or explicit test doubles.

    account(sim, period=2017, map_to=...) returns weighted real2025 dollars.
    to_native/to_reference retain a weighted series when given one.
    split_raise is the actual earnings_increments(person, period, increase).
    create_branch is create_perturbed_branch(sim, period, name, increments).
    audit verifies branch input/draw/membership/health-anchor preservation.
    Context callbacks must revalidate current engine/account/price state or an
    enforced immutable-state witness. A static constructor receipt alone cannot
    prove that a later reform preserved that state.
    """

    factory: Callable
    install: Callable
    is_weighted: Callable
    create_branch: Callable
    split_raise: Callable
    to_native: Callable
    to_reference: Callable
    account: Callable
    context_for: Callable
    hourly_wages_real: Callable
    audit: Callable
    expected_context: object
    bindings: Mapping
    mode: str = "native"
    earnings_tolerance: float = 0
    resource_tolerance: float = 0

    def validate(self):
        callbacks = (
            self.factory,
            self.install,
            self.is_weighted,
            self.create_branch,
            self.split_raise,
            self.to_native,
            self.to_reference,
            self.account,
            self.context_for,
            self.hourly_wages_real,
            self.audit,
        )
        if not all(callable(item) for item in callbacks) or not isinstance(
            self.expected_context, Mapping
        ):
            raise ContractError("Managed native/account capabilities are missing")
        if self.mode not in {"native", "synthetic_test"}:
            raise ContractError("Unknown runtime purpose")
        for name in REQUIRED_BINDINGS:
            if not re.fullmatch(r"[0-9a-f]{64}", str(self.bindings.get(name, ""))):
                raise ContractError("Missing source-bound receipt: " + name)
        for tolerance in (self.earnings_tolerance, self.resource_tolerance):
            if not math.isfinite(tolerance) or tolerance < 0:
                raise ContractError("Invalid source-bound native validation tolerance")
        if (self.earnings_tolerance or self.resource_tolerance) and not re.fullmatch(
            r"[0-9a-f]{64}", str(self.bindings.get("tolerance_receipt_sha256", ""))
        ):
            raise ContractError("Nonzero validation tolerance needs its own receipt")


def install_analysis_variables(system, model_api):
    """Register entity mapping/ranking only; the caller injects actual model API."""

    class cliffs_candidate_mask(model_api.Variable):
        label = "Frozen candidate mask for the commissioned experiment"
        value_type = bool
        entity = model_api.Person
        definition_period = model_api.YEAR

    class cliffs_candidate_rank(model_api.Variable):
        label = "Stable rank among frozen household candidates"
        value_type = int
        entity = model_api.Person
        definition_period = model_api.YEAR

        def formula(person, period, parameters):
            return (
                person.get_rank(
                    person.household,
                    person("person_id", period),
                    condition=person(CANDIDATE, period),
                )
                + 1
            )

    class cliffs_person_flag(model_api.Variable):
        label = "Person meets the commissioned scenario condition"
        value_type = bool
        entity = model_api.Person
        definition_period = model_api.YEAR

    class cliffs_household_flag(model_api.Variable):
        label = "A household member meets the commissioned condition"
        value_type = bool
        entity = model_api.Household
        definition_period = model_api.YEAR

        def formula(household, period, parameters):
            return household.any(household.members(PERSON_FLAG, period))

    variables = (
        cliffs_candidate_mask,
        cliffs_candidate_rank,
        cliffs_person_flag,
        cliffs_household_flag,
    )
    if any(variable.__name__ in system.variables for variable in variables):
        raise ContractError("Analysis variable collision; preserve the existing system")
    for variable in variables:
        system.add_variable(variable)


def _series(runtime, value, *, boolean=False):
    if not runtime.is_weighted(value):
        raise ContractError("A weighted MicroSeries surface is required")
    if value.isna().any():
        raise ContractError("Missing native inputs or outputs")
    if boolean:
        if str(value.dtype).lower() not in {"bool", "boolean"}:
            raise ContractError("A declared nonmissing boolean input is required")
    elif ((value == math.inf) | (value == -math.inf)).any():
        raise ContractError("Nonfinite native input or output")
    return value


def _context(runtime, sim):
    if runtime.context_for(sim) != runtime.expected_context:
        raise ContractError("Runtime/preparation/account/anchor context changed")
    if runtime.mode == "native":
        native = getattr(sim, "cliffs_native", {})
        if native.get("law_year") != 2017 or native.get("reference_year") != 2025:
            raise ContractError("No authenticated native2017 factory receipt")


def _resources(runtime, sim):
    _context(runtime, sim)
    return _series(runtime, runtime.account(sim, period=2017, map_to="person"))


def _earnings(runtime, sim):
    values = [_series(runtime, sim.calc(name, period=2017)) for name in EARNINGS]
    return values, _series(runtime, sum(values))


def _rank(runtime, sim, mask):
    sim.set_input(CANDIDATE, 2017, mask)
    sim.delete_arrays(RANK, 2017)
    rank = _series(runtime, sim.calc(RANK, period=2017)).copy()
    if mask.any() and ((rank[mask] < 1).any() or (rank[mask] > len(mask[mask])).any()):
        raise ContractError("Invalid candidate rank or unbounded branch schedule")
    return rank, int(rank[mask].max()) if mask.any() else 0


def _project(runtime, sim, flag):
    sim.set_input(PERSON_FLAG, 2017, flag)
    # Core retains dependent arrays after set_input; never reuse a stale union.
    sim.delete_arrays(HOUSEHOLD_FLAG, 2017)
    household = _series(runtime, sim.calc(HOUSEHOLD_FLAG, period=2017), boolean=True)
    members = _series(
        runtime, sim.calc(HOUSEHOLD_FLAG, period=2017, map_to="person"), boolean=True
    )
    return household, members


def _maximum(value):
    return float(value.abs().max()) if len(value) else 0.0


def _counts(runtime, sim, flag):
    household, members = _project(runtime, sim, flag)
    return {
        "adults": float(flag.sum()),
        "households": float(household.sum()),
        "members": float(members.sum()),
    }


def _job_changes(runtime, sim, selected, hourly_real):
    gross_real = selected * hourly_real * 40 * 52
    changes = {"employment_income": _series(runtime, runtime.to_native(gross_real))}
    targets = {
        "hours_worked_last_week": 40,
        "weekly_hours_worked_before_lsr": 40,
        "weeks_worked": 52,
        "weeks_unemployed": 0,
        "unemployment_compensation": 0,
        "hourly_wage": runtime.to_native(hourly_real),
    }
    for name, target in targets.items():
        changes[name] = selected * (
            target - _series(runtime, sim.calc(name, period=2017))
        )
    flags = {}
    for name, target in (
        ("is_paid_hourly", True),
        ("is_self_employed", False),
        ("has_never_worked", False),
    ):
        value = _series(runtime, sim.calc(name, period=2017), boolean=True)
        flags[name] = value | selected if target else value & ~selected
    return changes, flags, gross_real


def run(spec: RunSpec, runtime: Runtime):
    """Calculate each scenario afresh; return aggregates, never fabricated results."""
    spec.validate()
    runtime.validate()
    binding_at_start = dict(runtime.bindings)
    context_at_start = json.dumps(
        dict(runtime.expected_context), sort_keys=True, allow_nan=False
    )

    def check_frozen_context(current):
        if (
            dict(runtime.bindings) != binding_at_start
            or json.dumps(
                dict(runtime.expected_context), sort_keys=True, allow_nan=False
            )
            != context_at_start
        ):
            raise ContractError("The frozen execution bindings changed")
        _context(runtime, current)

    sim = runtime.factory()
    check_frozen_context(sim)
    runtime.install(sim)
    components, earnings = _earnings(runtime, sim)
    age = _series(runtime, sim.calc("age", period=2017))
    student = _series(
        runtime, sim.calc("is_full_time_student", period=2017), boolean=True
    )
    disabled = _series(runtime, sim.calc("is_disabled", period=2017), boolean=True)
    workers = (age >= 18) & (earnings > 0)
    jobs = (age >= 18) & (age < 65) & ~student & ~disabled
    for component in components:
        jobs = jobs & (component == 0)
    worker_rank, worker_max = _rank(runtime, sim, workers)
    job_rank, job_max = _rank(runtime, sim, jobs)
    hourly = _series(runtime, runtime.hourly_wages_real(sim))
    if (hourly[jobs] <= 0).any():
        raise ContractError("A source-bound positive job wage is missing")
    base = _resources(runtime, sim)
    blank = workers & False
    flags = {"job": {key: blank.copy() for key, _, _ in CUTOFFS}}
    audit = []

    def branch_result(name, changes, targets, selected, gross_real):
        if name in sim.branches:
            raise ContractError("Refuse an existing branch name")
        touched_hh, touched = _project(runtime, sim, selected)
        if len(selected[selected]) != len(touched_hh[touched_hh]):
            raise ContractError("A rank selected more than one adult per household")
        branch = None
        try:
            branch = runtime.create_branch(sim, 2017, name, changes)
            for variable, value in targets.items():
                branch.set_input(variable, 2017, value)
            check_frozen_context(branch)
            runtime.audit(sim, branch, selected)
            changed = _resources(runtime, branch)
            difference = _series(runtime, changed - base)
            if _maximum(difference[~touched]) > runtime.resource_tolerance:
                raise ContractError("An untouched household's resources changed")
            _, after_earnings = _earnings(runtime, branch)
            actual_gross = _series(
                runtime, runtime.to_reference(after_earnings - earnings)
            )
            error = _maximum((actual_gross - gross_real)[selected])
            if error > runtime.earnings_tolerance:
                raise ContractError(
                    "Native earnings do not match the declared real shock"
                )
            runtime.audit(sim, branch, selected)
            audit.append(
                {
                    "branch": name,
                    "sample_adults": len(selected[selected]),
                    "earnings_identity_max_error": error,
                }
            )
            return difference
        finally:
            if name in sim.branches:
                del sim.branches[name]

    zero_name = spec.run_id + "_zero"
    zero = branch_result(
        zero_name, {"employment_income": blank * 0}, {}, blank, blank * 0
    )
    if _maximum(zero) > runtime.resource_tolerance:
        raise ContractError("A zero earnings change moved resources")
    for label, eligible, ranks, maximum, amount in (
        *(
            (f"raise_{amount}", workers, worker_rank, worker_max, amount)
            for amount in spec.raises
        ),
        ("job", jobs, job_rank, job_max, None),
    ):
        measured = blank.copy()
        result = {key: blank.copy() for key, _, _ in CUTOFFS}
        for rank in range(1, maximum + 1):
            selected = eligible & (ranks == rank)
            if not selected.any():
                continue
            if (measured & selected).any():
                raise ContractError("Candidate tested more than once")
            measured = measured | selected
            if amount is None:
                changes, targets, gross = _job_changes(runtime, sim, selected, hourly)
            else:
                gross = selected * amount
                changes = runtime.split_raise(
                    sim.person, 2017, runtime.to_native(gross)
                )
                targets = {}
            difference = branch_result(
                f"{spec.run_id}_{label}_{rank}", changes, targets, selected, gross
            )
            for key, numerator, denominator in CUTOFFS:
                # Integer cross-products keep exact cutoff semantics; no epsilon.
                result[key] = result[key] | (
                    selected & (difference * denominator < gross * numerator)
                )
        if (eligible & ~measured).any() or (measured & ~eligible).any():
            raise ContractError("Not every frozen candidate was tested exactly once")
        for low, high in (("0", "0.20"), ("0.20", "0.50"), ("0.50", "0.60")):
            if (result[low] & ~result[high]).any():
                raise ContractError("Cutoffs are not nested within one experiment")
        flags[label] = result

    tables = {}
    for amount in spec.raises:
        raises = flags[f"raise_{amount}"]
        strict_raise_hh, _ = _project(runtime, sim, raises["0"])
        strict_job_hh, _ = _project(runtime, sim, flags["job"]["0"])
        strict_households = strict_raise_hh | strict_job_hh
        # Projection to people supplies each strict household's complete members.
        _, strict_members = _project(runtime, sim, raises["0"] | flags["job"]["0"])
        rows = {}
        for key, _, _ in CUTOFFS:
            union = raises[key] | flags["job"][key]
            union_households, union_members = _project(runtime, sim, union)
            additional_households = union_households & ~strict_households
            additional_members = union_members & ~strict_members
            rows[key] = {
                "raise": _counts(runtime, sim, raises[key]),
                "job": _counts(runtime, sim, flags["job"][key]),
                "union": _counts(runtime, sim, union),
                "additional_households_outside_strict_households": float(
                    additional_households.sum()
                ),
                "additional_members_outside_strict_households": float(
                    additional_members.sum()
                ),
            }
        tables[str(amount)] = rows
    check_frozen_context(sim)
    runtime.audit(sim, None, blank)
    return {
        "status": "SYNTHETIC_TEST_DOUBLE_NOT_AN_ESTIMATE"
        if runtime.mode == "synthetic_test"
        else "COMPUTED_UNREVIEWED_NO_UNCERTAINTY",
        "law_year": 2017,
        "reference_year": 2025,
        "currency_year": 2025,
        "bindings": binding_at_start,
        "tables": tables,
        "scenario_audit": audit,
        "uncertainty": "NOT_COMPUTED; paired source-cluster contributions/intervals need the separately admitted aggregation stage",
    }


def prepare_cli_request(argv=None, *, runtime=None):
    """Decide whether command data has native capabilities; do no work or writes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    if not args.out.is_absolute():
        parser.error("Use an explicit absolute aggregate-output path")
    if runtime is None or runtime.mode != "native":
        parser.error(
            "No source-authenticated managed factory/account runtime is installed; no results produced"
        )
    spec = RunSpec(args.run_id)
    spec.validate()
    runtime.validate()
    return spec, args.out


def main(argv=None, *, runtime=None):
    spec, output = prepare_cli_request(argv, runtime=runtime)
    result = run(spec, runtime)
    with output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
