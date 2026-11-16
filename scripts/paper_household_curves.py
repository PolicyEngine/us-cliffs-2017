"""Real hypothetical-household curves under the paper's frozen experiment.

Run with: uv run --no-sync python scripts/paper_household_curves.py
Every plotted point is a PolicyEngine calculation. There is no survey data,
population aggregation, interpolation, or current-certified-bundle claim here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
from importlib import metadata
from pathlib import Path


def cap_threads(environ):
    limits = {}
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        old = environ.get(key)
        if old is None:
            environ[key] = "2"
        elif old.isdigit() and int(old) > 0:
            environ[key] = str(min(int(old), 2))
        limits[key] = environ.get(key)
    return limits


THREAD_LIMITS = cap_threads(os.environ)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from cliffs2017.decompose import components, household_values  # noqa: E402
from cliffs2017.medicaid import load_totals  # noqa: E402
from cliffs2017.simulation import reforms  # noqa: E402
from scripts.expanded_historical import FROZEN_PACKAGES  # noqa: E402

CASES = {
    "single_2025": dict(year=2025, adult_age=50, children=[], low=0, high=80_000,
                         state="NC", county="WAKE_COUNTY_NC", role="main",
                         label="Single adult, age 50, Wake County, North Carolina (2025)"),
    "aca_2017": dict(year=2017, adult_age=50, children=[], low=0, high=80_000,
                     state="NC", county="WAKE_COUNTY_NC", role="historical-hybrid-appendix",
                     label="Single adult, age 50, Wake County, North Carolina (2017 hybrid sensitivity)"),
    "parent_2025": dict(year=2025, adult_age=35, children=[8, 12], low=0, high=90_000,
                        state="NC", county="WAKE_COUNTY_NC", role="main",
                        label="Single parent, age 35, children ages 8 and 12, Wake County, North Carolina (2025)"),
}
DIAGNOSTICS = ["aca_ptc", "aca_magi", "aca_magi_fraction", "aca_required_contribution_percentage", "slcsp", "used_aca_ptc"]
PERSON_DIAGNOSTICS = ["employment_income", "medicaid_enrolled", "chip_enrolled", "is_medicaid_eligible", "is_chip_eligible", "medicaid_cost_if_enrolled", "medicaid_slcsp_state_denominator", "medicaid_slcsp_state_average_cost_index"]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@lru_cache(maxsize=2)
def checked_totals(year):
    path = ROOT / "results" / "medicaid" / f"totals_{year}_p4_s0.json"
    totals, meta = load_totals(path)
    expected = dict(year=year, aca_before_2018=year < 2018, parts=4, seed=0,
                    versions={k: FROZEN_PACKAGES[k] for k in ("policyengine-us", "policyengine-core")})
    wrong = {k: (meta.get(k), v) for k, v in expected.items() if meta.get(k) != v}
    if wrong:
        raise ValueError(f"Wrong fixed full-sample Medicaid totals: {wrong}")
    return totals, meta


def situation(case, earnings, *, axis=None):
    """Fully specified filing/coverage assumptions; no overridden income formulas."""
    year = case["year"]
    names = ["adult"] + [f"child{i + 1}" for i in range(len(case["children"]))]
    ages = [case["adult_age"]] + case["children"]
    people = {}
    for i, (name, age) in enumerate(zip(names, ages, strict=True)):
        people[name] = {
            "age": {year: age}, "employment_income": {year: earnings if i == 0 else 0},
            "is_tax_unit_head": {year: i == 0}, "is_tax_unit_dependent": {year: i != 0},
            "is_tax_unit_spouse": {year: False}, "has_esi": {year: False},
            "is_disabled": {year: False}, "is_pregnant": {year: False},
            "immigration_status": {year: "CITIZEN"},
            "is_full_time_student": {year: i != 0}, "is_in_k12_school": {year: i != 0},
            "takes_up_medicaid_if_eligible": {year: True},
            "takes_up_chip_if_eligible": {year: True},
            "pre_subsidy_rent": {year: 14_400 if i == 0 else 0},
        }
    out = {
        "people": people,
        "tax_units": {"tax_unit": {"members": names, "tax_unit_is_filer": {year: True},
            "filing_status": {year: "HEAD_OF_HOUSEHOLD" if case["children"] else "SINGLE"},
            "takes_up_eitc": {year: True}, "takes_up_aca_if_eligible": {year: True}}},
        "families": {"family": {"members": names}},
        "marital_units": {name: {"members": [name]} for name in names},
        "spm_units": {"spm_unit": {"members": names, "spm_unit_assets": {year: 0},
            "childcare_expenses": {year: 0}, "takes_up_snap_if_eligible": {year: True},
            "takes_up_tanf_if_eligible": {year: False},
            "takes_up_housing_assistance_if_eligible": {year: False}}},
        "households": {"household": {"members": names,
            "state_code": {year: case["state"]}, "county_str": {year: case["county"]}}},
    }
    if axis is not None:
        low, high, count = axis
        out["axes"] = [[dict(name="employment_income", index=0, period=year,
                              min=low, max=high, count=count)]]
    return out


@lru_cache(maxsize=2)
def system(year):
    from policyengine_us import CountryTaxBenefitSystem
    totals, _ = checked_totals(year)
    return CountryTaxBenefitSystem(reform=reforms(True, year < 2018, totals, year, year >= 2024))


def compute(case, earnings=0, *, axis=None, fresh_system=False):
    from policyengine_us import Simulation
    year = case["year"]
    inputs = situation(case, earnings, axis=axis)
    if fresh_system:
        totals, _ = checked_totals(year)
        sim = Simulation(situation=inputs, reform=reforms(True, year < 2018, totals, year, year >= 2024))
    else:
        sim = Simulation(tax_benefit_system=system(year), situation=inputs)
    parts = components(sim, year)
    values = household_values(sim, [n for n, _ in parts] + ["household_net_income"], year)
    signed = {n: values[n] * sign for n, sign in parts}
    native = values["household_net_income"]
    premium_signed = signed["marketplace_net_premium"]
    params = sim.tax_benefit_system.parameters(year).gov.household
    health_names = set(params.household_health_benefits) | set(params.household_health_costs)
    cash = sum(v for n, v in signed.items() if n not in health_names)
    full = native - premium_signed
    n = len(native)
    people = 1 + len(case["children"])
    out = {
        "earnings": np.asarray(sim.calculate("employment_income", year)).reshape(n, people)[:, 0],
        "resources_full_health": full,
        "resources_cash": cash,
        "resources_native": native,
        "native_rounding_residual": native - sum(signed.values()),
        "signed_components": signed,
        "tax_unit": {v: np.asarray(sim.calculate(v, year)) for v in DIAGNOSTICS},
        "people": {v: np.asarray(sim.calculate(v, year)).reshape(n, people) for v in PERSON_DIAGNOSTICS},
    }
    return out


def arrays(value, prefix=""):
    for key, val in value.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(val, dict):
            yield from arrays(val, path)
        else:
            yield path, np.asarray(val)


def compare(actual, expected, *, atol=0.01):
    left, right = dict(arrays(actual)), dict(arrays(expected))
    if left.keys() != right.keys():
        raise AssertionError("Different output schemas")
    largest = 0.0
    for key in left:
        if left[key].shape != right[key].shape:
            raise AssertionError(f"Different shapes at {key}")
        error = float(np.max(np.abs(left[key].astype(float) - right[key].astype(float)), initial=0))
        if error > atol:
            raise AssertionError(f"Mismatch at {key}: {error} > {atol}")
        largest = max(largest, error)
    return largest


def at_index(values, index):
    return {k: ({n: a[index:index + 1] for n, a in v.items()} if isinstance(v, dict)
                else v[index:index + 1]) for k, v in values.items()}


def signature(values):
    """Coverage and meal-tier statuses used only to refine observed transitions."""
    return tuple(np.concatenate([
        values["people"]["medicaid_enrolled"][0].astype(bool),
        values["people"]["chip_enrolled"][0].astype(bool),
        np.asarray([values["tax_unit"]["aca_ptc"][0] > 0]),
        np.asarray([values["signed_components"]["free_school_meals"][0] > 0,
                    values["signed_components"]["reduced_price_school_meals"][0] > 0]),
    ]).tolist())


def refine_integer_transition(low, high, get_point):
    """Fresh model evaluations identify an adjacent-dollar status transition.

    This is a finite integer-dollar resolution, not an exact statutory cutoff.
    The caller supplies a bracket containing a single observed status change.
    """
    low, high = int(low), int(high)
    left = signature(get_point(low))
    if left == signature(get_point(high)):
        return None
    while high - low > 1:
        mid = (low + high) // 2
        if signature(get_point(mid)) == left:
            low = mid
        else:
            high = mid
    return [low, high]


def accounting_checks(values, case):
    parts = values["signed_components"]
    residual = values["native_rounding_residual"]
    if float(np.max(np.abs(residual))) > 0.05:
        raise AssertionError("Native rounding residual exceeds five cents")
    expected = sum(v for k, v in parts.items() if k != "marketplace_net_premium") + residual
    np.testing.assert_allclose(values["resources_full_health"], expected, atol=1e-8, rtol=0)
    cash = values["resources_cash"]
    # In these NC cases the only health benefits are Medicaid, CHIP and PTC;
    # CHIP premiums are retained. This also checks unexpected health payments.
    expected_health = parts["medicaid_cost"] + parts["chip"] + parts["assigned_aca_ptc"] + parts["chip_premium"]
    np.testing.assert_allclose(values["resources_full_health"] - cash, expected_health + residual, atol=1e-8, rtol=0)
    np.testing.assert_allclose(parts["assigned_aca_ptc"], values["tax_unit"]["aca_ptc"], atol=0.01, rtol=0)
    totals, _ = checked_totals(case["year"])
    for variable, field in [("medicaid_slcsp_state_denominator", "denominator"),
                            ("medicaid_slcsp_state_average_cost_index", "average_cost_index")]:
        # PolicyEngine variables store these totals in float32; use its same cast.
        expected_total = float(np.float32(totals.loc[case["state"], field]))
        np.testing.assert_allclose(values["people"][variable], expected_total, rtol=0, atol=0)
    return dict(maximum_native_rounding_residual=float(np.max(np.abs(residual))),
                once_only_ptc_identity=True, fixed_national_medicaid_values=True,
                cash_plus_health_identity=True)


def transition_record(low, high):
    delta = {k: float(high["signed_components"][k][0] - v[0])
             for k, v in low["signed_components"].items()}
    delta.pop("marketplace_net_premium")
    residual_change = float(high["native_rounding_residual"][0] - low["native_rounding_residual"][0])
    full_change = float(high["resources_full_health"][0] - low["resources_full_health"][0])
    if abs(sum(delta.values()) + residual_change - full_change) > 1e-8:
        raise AssertionError("Transition component identity failed")
    return dict(before={k: float(low[k][0]) for k in ("earnings", "resources_full_health", "resources_cash")},
                after={k: float(high[k][0]) for k in ("earnings", "resources_full_health", "resources_cash")},
                earnings_change=float(high["earnings"][0] - low["earnings"][0]),
                full_resource_change=full_change,
                cash_resource_change=float(high["resources_cash"][0] - low["resources_cash"][0]),
                signed_component_changes=delta, residual_change=residual_change,
                retention=full_change / float(high["earnings"][0] - low["earnings"][0]))


def finish_case(name, case):
    count = (case["high"] - case["low"]) // 100 + 1
    axis = (case["low"], case["high"], count)
    vals = compute(case, axis=axis)
    checks = accounting_checks(vals, case)
    np.testing.assert_array_equal(vals["earnings"], np.arange(case["low"], case["high"] + 1, 100))
    checks["repeat_axis_maximum_error"] = compare(vals, compute(case, axis=axis), atol=0)
    scalar_points = {}

    def fresh_point(earnings):
        if earnings not in scalar_points:
            value = compute(case, earnings)
            accounting_checks(value, case)
            scalar_points[earnings] = value
        return scalar_points[earnings]

    checks["fresh_scalar_axis_maximum_error"] = 0.0
    for index in (0, count // 2, count - 1):
        error = compare(at_index(vals, index), fresh_point(float(vals["earnings"][index])))
        checks["fresh_scalar_axis_maximum_error"] = max(checks["fresh_scalar_axis_maximum_error"], error)
    changes = np.diff(vals["resources_full_health"])
    negative = np.flatnonzero(changes < 0)
    # Annotate the largest one (single adult) / three (parent) sampled drops;
    # all negative sampled steps remain in the data, without a dollar floor.
    selected = sorted(negative, key=lambda i: changes[i])[:1 if not case["children"] else 3]
    events = []
    for i in sorted(selected):
        low, high = [float(x) for x in vals["earnings"][i:i + 2]]
        fresh_low, fresh_high = fresh_point(low), fresh_point(high)
        for j, v in ((i, fresh_low), (i + 1, fresh_high)):
            error = compare(at_index(vals, j), v)
            checks["fresh_scalar_axis_maximum_error"] = max(checks["fresh_scalar_axis_maximum_error"], error)
        bracket = refine_integer_transition(low, high, fresh_point)
        event = dict(sampled_bracket=[low, high], sampled_change=transition_record(fresh_low, fresh_high),
                     integer_dollar_status_transition=bracket)
        if bracket is not None:
            event["integer_transition_change"] = transition_record(fresh_point(bracket[0]), fresh_point(bracket[1]))
        event["raise_comparisons"] = {}
        for increment in (1000, 5000):
            after = fresh_point(low + increment)
            event["raise_comparisons"][str(increment)] = transition_record(fresh_low, after)
            match = np.flatnonzero(vals["earnings"] == low + increment)
            if len(match):
                error = compare(at_index(vals, int(match[0])), after)
                checks["fresh_scalar_axis_maximum_error"] = max(checks["fresh_scalar_axis_maximum_error"], error)
        later = np.flatnonzero((vals["earnings"] >= high) & (vals["resources_full_health"] >= fresh_low["resources_full_health"][0]))
        first_recovery = int(later[0]) if len(later) else None
        event["sampled_recovery_earnings_bracket"] = (
            [float(vals["earnings"][first_recovery - 1]), float(vals["earnings"][first_recovery])]
            if first_recovery is not None else None)
        if first_recovery is not None:
            for j in (first_recovery - 1, first_recovery):
                error = compare(at_index(vals, j), fresh_point(float(vals["earnings"][j])))
                checks["fresh_scalar_axis_maximum_error"] = max(checks["fresh_scalar_axis_maximum_error"], error)
        events.append(event)
    base = float(vals["earnings"][0])
    checks["zero_change_repeat_maximum_error"] = compare(fresh_point(base), compute(case, base), atol=0)
    checks["independent_system_maximum_error"] = compare(fresh_point(base), compute(case, base, fresh_system=True))
    return dict(label=case["label"], specification=case, inputs_at_zero_earnings=situation(case, 0),
                sweep_axis=situation(case, 0, axis=axis)["axes"], curve=vals,
                sampled_negative_steps=[dict(earnings=[float(vals["earnings"][i]), float(vals["earnings"][i + 1])],
                                             resource_change=float(changes[i])) for i in negative],
                annotations=events,
                independently_run_points={str(k): v for k, v in sorted(scalar_points.items())}, checks=checks)


def package_tree_fingerprint(package):
    """Hash the installed source/parameter/data files without copying their content."""
    import importlib.util
    path = Path(importlib.util.find_spec(package).origin).parent
    digest = hashlib.sha256()
    count = size = 0
    for item in sorted(path.rglob("*")):
        if item.is_file() and item.suffix in (".py", ".yaml", ".yml", ".csv", ".json"):
            data = item.read_bytes()
            digest.update(item.relative_to(path).as_posix().encode() + b"\0")
            digest.update(hashlib.sha256(data).digest())
            count += 1
            size += len(data)
    return dict(sha256=digest.hexdigest(), files=count, bytes=size,
                definition="Sorted relative paths + NUL + SHA256(file bytes); .py/.yaml/.yml/.csv/.json files")


def provenance():
    return dict(
        route="Explicitly unmanaged frozen historical household Simulation; approved study exception",
        managed_bundle=False,
        versions={k: metadata.version(k) for k in FROZEN_PACKAGES},
        source_hashes={str(p.relative_to(ROOT)): sha256(p) for p in [
            Path(__file__), ROOT / "tests/test_paper_household_curves.py",
            ROOT / "cliffs2017/aca2017.py", ROOT / "cliffs2017/decompose.py",
            ROOT / "cliffs2017/simulation.py", ROOT / "cliffs2017/medicaid.py",
            ROOT / "cliffs2017/benefits.py", ROOT / "cliffs2017/data/cms_age_curves_2014_2017.csv",
        ]},
        installed_package_trees={k: package_tree_fingerprint(k) for k in ("policyengine_us", "policyengine_core")},
        fixed_medicaid_totals={str(y): {k: v for k, v in checked_totals(y)[1].items() if k != "sums_files"}
                               for y in (2017, 2025)},
        wrapper_compatibility_review=dict(
            checked_utc_date="2026-11-12", official_source="https://pypi.org/pypi/policyengine/6.17.2/json",
            latest_wrapper="6.17.2", wheel_sha256="d86ba67f7093453fbb3249275c1802ed9dbadb06582fddff447f181958468088",
            declared_us_extra={"policyengine-us": "2.2.1", "policyengine-core": "3.33.3"},
            current_us_release_separately_verified="2.117.5",
            limitation="Household module imports us_latest and release certification at import; no frozen-model selector. The earlier actual import rejects US2.116.0 before allow_unmanaged. No bypass or installed wrapper is used."),
        effective_thread_limits=THREAD_LIMITS, workers=1,
        data_scope="Fully hypothetical inputs; no survey microdata loaded or population estimates computed",
    )


def write_summary(result, path):
    lines = ["# Hypothetical household earnings curves", "",
             "Every stored earnings point is a real calculation under the frozen historical model. "
             "These selected illustrations estimate no population prevalence. Resources count "
             "health benefits at modeled government cost, remove marketplace net premiums so PTC "
             "is counted once, retain CHIP premiums, and do not deduct rent or living expenses.", ""]
    for name, case in result["cases"].items():
        lines += [f"## {case['label']}", "", f"Grid: ${case['specification']['low']:,} to ${case['specification']['high']:,}, every $100.", "",
                  "| Baseline earnings | First dollar with changed status | $1,000 resource change | $5,000 resource change | First sampled recovery bracket |",
                  "|---:|---:|---:|---:|---|"]
        for e in case["annotations"]:
            br = e["integer_dollar_status_transition"]
            recovery = e["sampled_recovery_earnings_bracket"]
            boundary = f"${br[1]:,}" if br is not None else "No changed coverage/meal status"
            lines.append(f"| ${e['sampled_bracket'][0]:,.0f} | {boundary}" +
                         f" | ${e['raise_comparisons']['1000']['full_resource_change']:,.2f}" +
                         f" | ${e['raise_comparisons']['5000']['full_resource_change']:,.2f}" +
                         f" | {recovery} |")
        lines += ["", "Fresh scalar, repeat, independent-system, fixed-Medicaid and component accounting controls passed.", ""]
    Path(path).write_text("\n".join(lines) + "\n")


def serializable(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {k: serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serializable(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def run_pilot(out):
    result = {}
    for age in (50, 55, 60):
        case = deepcopy(CASES["aca_2017"])
        case["adult_age"] = age
        vals = compute(case, axis=(40_000, 65_000, 251))
        result[f"aca_age_{age}"] = vals
        d = np.diff(vals["resources_full_health"])
        i = int(np.argmin(d))
        print(f"age={age}: biggest $100-step change={d[i]:.2f}, earnings={vals['earnings'][i]:.0f}->{vals['earnings'][i+1]:.0f}", flush=True)
    case = CASES["parent_2025"]
    vals = compute(case, axis=(25_000, 80_000, 551))
    result["parent_2025"] = vals
    for i in np.argsort(np.diff(vals["resources_full_health"]))[:5]:
        print(f"parent: $100-step change={np.diff(vals['resources_full_health'])[i]:.2f}, earnings={vals['earnings'][i]:.0f}->{vals['earnings'][i+1]:.0f}", flush=True)
    Path(out).write_text(json.dumps(serializable(result), indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "results/paper_household_curves.json")
    parser.add_argument("--pilot", action="store_true")
    args = parser.parse_args()
    actual = {k: metadata.version(k) for k in FROZEN_PACKAGES}
    if actual != FROZEN_PACKAGES:
        raise RuntimeError(f"Frozen historical versions required: {actual}")
    if args.pilot:
        run_pilot(args.out)
    else:
        started = time.monotonic()
        result = dict(kind="paper_hypothetical_household_curves", generated_utc=datetime.now(timezone.utc).isoformat(),
                      provenance=provenance(),
                      methodology=dict(
                          resources_full_health="household_net_income + raw marketplace_net_premium; PTC once, health government cost",
                          resources_cash="Sum of signed non-health components, excluding health benefits and health costs",
                          expenses="Annual rent14400, childcare0, assets0 held fixed. Rent can affect SNAP/tax rules but is not subtracted from the plotted resources. Other unspecified monetary inputs are model defaults0.",
                          take_up="Medicaid/CHIP/ACA/SNAP/EITC and tax filing true; TANF/housing false. All citizens. Age8/12 children avoid WIC; no pregnancy/disability/ESI. Children attend K12/full-time school.",
                          law="2017 federal rules with existing paper pre2018 ACA reform and later state/Medicaid/CHIP model inputs;2025 frozen-model scenario. Not an exact reconstruction of every historical rule or a current-law forecast.",
                          health_values="Fixed full-national state Medicaid totals from the paper;2017 spending values begin2020,2025 use2023. CHIP values use2023 spending/2022 enrollment. No hypothetical-axis denominator.",
                          resolution="$100 earnings grid; every plotted point computed. Annotated status transitions refined with fresh simulations to adjacent integer-dollar earnings, not sub-dollar or statutory thresholds. Recovery brackets are first sampled recovery and preceding sample, with no interpolation.",
                          selection="2025 cases are main.2017 is historical hybrid appendix only. Cases selected from actual2017 pilot ages50/55/60,2025 single ages35/50 and parent sweeps; annotate largest one/three sampled negative steps. All negative steps retained without a dollar floor.",
                          controls="Fresh scalar comparisons include grid endpoints/midpoints, annotation brackets/1k/5k endpoints/recovery brackets; repeat full axes and zero-change scalar; independently constructed reform-system control; component identities and fixed national Medicaid values at every curve point."),
                      cases={})
        for name, case in CASES.items():
            result["cases"][name] = finish_case(name, case)
            print(f"{name}: curve and all controls passed", flush=True)
        result["runtime_seconds"] = time.monotonic() - started
        result["status"] = "complete"
        args.out.parent.mkdir(parents=True, exist_ok=True)
        pending = args.out.with_suffix(".pending.json")
        pending.write_text(json.dumps(serializable(result), indent=2, allow_nan=False) + "\n")
        pending.replace(args.out)
        write_summary(result, args.out.with_suffix(".md"))
        print(f"Wrote {args.out}; SHA256 {sha256(args.out)}; {result['runtime_seconds']:.2f}s", flush=True)


if __name__ == "__main__":
    main()
