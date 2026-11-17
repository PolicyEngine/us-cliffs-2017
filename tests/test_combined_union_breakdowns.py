"""The combined union's breakdowns, on synthetic households.

The property tests build a real policyengine-core Microsimulation (person and household
entities, calibrated household weights, no tax formulas), run the production counting code on
random saved changes with their parts of net income, and compare every count with a brute-force
oracle written independently here. Weights are whole numbers, so the oracle and MicroSeries
agree exactly. A four-part test then runs the bootstrap and the combine step's assembly on the
counted parts, as the Modal run and the combine step do.
"""

import copy
import io
import json
import math

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from scripts import combined_union_breakdowns as bd
from scripts import combined_union_inputs as ci
from scripts.expanded_combined_union import RAISES, SETS
from scripts.expanded_raise_union import CHANGES

YEAR = 2017
HEALTH_COMPONENTS = ["d_medicaid_cost", "d_assigned_aca_ptc", "d_marketplace_net_premium"]
COMPONENTS = ["d_household_market_income", "d_household_tax_before_refundable_credits", "d_snap",
              *HEALTH_COMPONENTS]
DRIVER_COLUMNS = [c for c in COMPONENTS if c not in ("d_household_market_income", "d_marketplace_net_premium")]
NAMES = sorted({c.removeprefix("d_") for c in DRIVER_COLUMNS} | {"none"})
HEALTH_NAMES = {"medicaid_cost", "assigned_aca_ptc"}
# Dollar changes in the other parts of net income; the market part is the pay change itself.
VALUES = [-2500.0, -900.0, -400.0, -100.0, 0.0, 150.0, 600.0]
STATES = {"AA": "expanded", "BB": "not_expanded", "CC": "not_expanded_partial"}
EXPANSION = {"AA": {"limit_2017": 1.38, "limit_2018": 1.38, "category": "expanded"},
             "BB": {"limit_2017": None, "limit_2018": None, "category": "not_expanded"},
             "CC": {"limit_2017": 1.0, "limit_2018": 1.0, "category": "not_expanded_partial"}}
AGES = [18.0, 30.0, 61.0, 62.0, 63.0, 64.0]
THRESHOLD = {"strict": 0.0, "below_half": 0.5}


def synthetic_sim(sizes, weights):
    from policyengine_core.entities import build_entity
    from policyengine_core.periods import YEAR as Y
    from policyengine_core.simulations.microsimulation import Microsimulation
    from policyengine_core.taxbenefitsystems import TaxBenefitSystem
    from policyengine_core.variables import Variable

    person = build_entity(key="person", plural="people", label="Person", is_person=True)
    household = build_entity(key="household", plural="households", label="Household",
                             roles=[{"key": "member", "plural": "members", "label": "Member"}])
    system = TaxBenefitSystem([person, household])
    system.add_variable(type("household_weight", (Variable,), {
        "value_type": float, "entity": household, "definition_period": Y, "label": "weight"}))
    people, households, k = {}, {}, 0
    for h, (size, w) in enumerate(zip(sizes, weights)):
        members = []
        for _ in range(size):
            people[f"p{k}"] = {}
            members.append(f"p{k}")
            k += 1
        households[f"h{h}"] = {"members": members, "household_weight": {YEAR: float(w)}}
    return Microsimulation(tax_benefit_system=system, situation={"people": people, "households": households})


def parts_frame(draw, people, pay):
    """Component columns for rows with these pay changes; the two measures follow from them."""
    frame = pd.DataFrame({"d_household_market_income": np.asarray(pay, dtype=float)})
    for c in COMPONENTS[1:]:
        frame[c] = [draw(st.sampled_from(VALUES)) for _ in people]
    once = [c for c in COMPONENTS if c != "d_marketplace_net_premium"]
    frame["d_net_single_ptc"] = frame[once].sum(axis=1)
    frame["d_net_without_health"] = frame[[c for c in COMPONENTS if c not in HEALTH_COMPONENTS]].sum(axis=1)
    return frame


@st.composite
def populations(draw, offset=0):
    n = draw(st.integers(1, 6))
    sizes = draw(st.lists(st.integers(1, 4), min_size=n, max_size=n))
    weights = draw(st.lists(st.integers(1, 500), min_size=n, max_size=n))
    sources = np.array(draw(st.lists(st.integers(0, n - 1), min_size=n, max_size=n))) + offset
    states = np.array(draw(st.lists(st.sampled_from(sorted(STATES)), min_size=n, max_size=n)))
    hh = np.repeat(np.arange(n), sizes)
    people = len(hh)
    age = np.array([draw(st.sampled_from(AGES)) for _ in range(people)])
    raise_people, ranks = [], []
    for h in range(n):
        members = np.flatnonzero(hh == h)
        take = draw(st.integers(0, min(2, len(members))))
        raise_people += members[:take].tolist()
        ranks += list(range(1, take + 1))
    workers = np.array([draw(st.booleans()) for _ in raise_people], dtype=bool)
    frames = {}
    for key, amount in CHANGES.items():
        base = pd.DataFrame({
            "person_index": np.array(raise_people, dtype=np.int64),
            "person_id": np.array(raise_people, dtype=np.int64) + 1000,
            "household_id": hh[raise_people].astype(np.int64) + 1,
            "rank": np.array(ranks, dtype=np.int64),
            "change": np.full(len(raise_people), amount),
            "worker": workers,
        })
        frames[key] = pd.concat([base, parts_frame(draw, raise_people, np.full(len(raise_people), amount))], axis=1)
    worker_people = {p for p, w in zip(raise_people, workers) if w}
    job_people = [p for p in range(people) if p not in worker_people and draw(st.booleans())]
    rank_of, seen = [], {}
    for p in job_people:
        seen[hh[p]] = seen.get(hh[p], 0) + 1
        rank_of.append(seen[hh[p]])
    gross = np.array([draw(st.sampled_from([15080.0, 20800.0])) for _ in job_people])
    job = pd.concat([pd.DataFrame({
        "person_index": np.array(job_people, dtype=np.int64),
        "person_id": np.array(job_people, dtype=np.int64) + 1000,
        "household_id": hh[job_people].astype(np.int64) + 1,
        "state_code": states[hh[job_people]] if job_people else np.array([], dtype=str),
        "rank": np.array(rank_of, dtype=np.int64),
        "gross_pay": gross,
    }), parts_frame(draw, job_people, gross)], axis=1)
    candidate = np.zeros(people, bool)
    candidate[job_people] = True
    rank = np.zeros(people, np.int64)
    rank[job_people] = rank_of
    return dict(sizes=np.array(sizes), weights=np.array(weights, dtype=float), sources=sources, states=states,
                hh=hh, age=age, frames=frames, job=job, candidate=candidate, rank=rank)


# ---------------------------------------------------------------------------
# An independent oracle: plain loops with the synthetic weights.


def o_households(flags, hh, n):
    out = np.zeros(n, bool)
    for p in np.flatnonzero(flags):
        out[hh[p]] = True
    return out


def o_counts(pop, house, adults=None):
    w, sizes, hh = pop["weights"], pop["sizes"], pop["hh"]
    out = {"households": float(sum(w[h] for h in np.flatnonzero(house))),
           "household_members": float(sum(w[h] * sizes[h] for h in np.flatnonzero(house)))}
    if adults is not None:
        out["adults"] = float(sum(w[hh[p]] for p in np.flatnonzero(adults) if house[hh[p]]))
    return out


def o_adults(pop, flags):
    return float(sum(pop["weights"][pop["hh"][p]] for p in np.flatnonzero(flags)))


def o_driver(row) -> str:
    values = [getattr(row, c) for c in DRIVER_COLUMNS]
    worst = min(values)
    return DRIVER_COLUMNS[values.index(worst)].removeprefix("d_") if worst < 0 else "none"


def o_rows(pop, variant):
    job = pop["job"]
    if variant == bd.RANKS_1_2:
        return job[job["rank"] <= 2]
    if variant == bd.NO_62_64:
        return job[~np.isin(pop["age"][job["person_index"].to_numpy()], [62.0, 63.0, 64.0])]
    return job


def o_tests(pop, measure, variant, t):
    """test -> person flags below ``t``, and test -> person -> largest loss."""
    column = bd.MEASURES[measure]
    people = len(pop["hh"])
    flags, drivers = {}, {}
    for key, frame in pop["frames"].items():
        flags[key], drivers[key] = np.zeros(people, bool), {}
        for row in frame.itertuples():
            drivers[key][row.person_index] = o_driver(row)
            if row.worker and getattr(row, column) / row.change < t:
                flags[key][row.person_index] = True
    flags["job"], drivers["job"] = np.zeros(people, bool), {}
    for row in o_rows(pop, variant).itertuples():
        drivers["job"][row.person_index] = o_driver(row)
        if getattr(row, column) / row.gross_pay < t:
            flags["job"][row.person_index] = True
    return flags, drivers


def o_metrics(pop):
    hh, n = pop["hh"], len(pop["weights"])
    cand, rank, age = pop["candidate"], pop["rank"], pop["age"]
    category = np.array([STATES[s] for s in pop["states"]])
    older = cand & (age >= 62) & (age <= 64)
    metrics = {}

    def record(label, mask):
        metrics[label] = o_counts(pop, o_households(mask, hh, n), mask)

    record("pool|candidates", cand)
    for label, mask in {"rank_1_2": cand & (rank <= 2), "rank_3_plus": cand & (rank >= 3),
                        "age_62_64": older, "age_18_61": cand & ~older,
                        **{f"expansion_{c}": cand & (category[hh] == c) for c in bd.EXPANSION}}.items():
        record(f"pool|{label}", mask)
    person, house = {}, {}
    for v, bases in bd.VARIANT_BASES.items():
        for m in bd.VARIANT_MEASURES[v]:
            flags = {level: o_tests(pop, m, v, t)[0] for level, t in THRESHOLD.items()}
            for base in bases:
                p = {level: np.logical_or.reduce([flags[level][c] for c in SETS[base]]) for level in THRESHOLD}
                h = {level: o_households(p[level], hh, n) for level in THRESHOLD}
                h["additional"] = h["below_half"] & ~h["strict"]
                person[v, m, base], house[v, m, base] = p, h
                metrics[f"{v}|{m}|{base}|strict"] = o_counts(pop, h["strict"], p["strict"])
                metrics[f"{v}|{m}|{base}|below_half"] = o_counts(pop, h["below_half"], p["below_half"])
                metrics[f"{v}|{m}|{base}|additional"] = o_counts(pop, h["additional"], p["below_half"])
    for v in (bd.RANKS_1_2, bd.NO_62_64):
        for base in bd.VARIANT_BASES[v]:
            for level in THRESHOLD:
                full, small = (bd.FULL, bd.HEALTH, base), (v, bd.HEALTH, base)
                metrics[f"drop|{v}|{base}|{level}"] = {
                    **o_counts(pop, house[full][level] & ~house[small][level]),
                    "adults": o_adults(pop, person[full][level] & ~person[small][level])}
    for base, group in bd.DRIVER_GROUPS:
        level = "strict" if group == "strict" else "below_half"
        tests, drivers = o_tests(pop, bd.HEALTH, bd.FULL, THRESHOLD[level])
        flagged = person[bd.FULL, bd.HEALTH, base][level].copy()
        if group == "additional":
            flagged &= house[bd.FULL, bd.HEALTH, base]["additional"][hh]
        assigned = {}
        for p in np.flatnonzero(flagged):
            test = next(c for c in (*RAISES, "job") if c in SETS[base] and tests[c][p])
            assigned[p] = drivers[test][p]
        metrics[f"driver_total|{base}|{group}"] = {"adults": o_adults(pop, flagged)}
        for name in NAMES:
            mask = np.array([assigned.get(p) == name for p in range(len(hh))])
            metrics[f"driver|{base}|{group}|{name}"] = {"adults": o_adults(pop, mask)}
        health = np.array([assigned.get(p) in HEALTH_NAMES for p in range(len(hh))])
        metrics[f"driver_family|{base}|{group}|health_coverage"] = {"adults": o_adults(pop, health)}
        metrics[f"driver_family|{base}|{group}|other"] = {"adults": o_adults(pop, flagged & ~health)}
    for base in ("combined", "job"):
        p, h = person[bd.FULL, bd.HEALTH, base]["strict"], house[bd.FULL, bd.HEALTH, base]["strict"]
        for c in bd.EXPANSION:
            metrics[f"expansion|{base}|strict|{c}"] = o_counts(pop, h & (category == c), p)
    return metrics


# ---------------------------------------------------------------------------
# Running the production code on a synthetic part


def production_drivers(pop):
    people = len(pop["hh"])
    job = pop["job"]
    job_drivers = bd.person_drivers(job, bd.drivers_from_components(job, COMPONENTS), people)
    raise_drivers = {k: bd.person_drivers(f, bd.drivers_from_components(f, COMPONENTS), people)
                     for k, f in pop["frames"].items()}
    return raise_drivers, job_drivers


def run_counts(pop, per_source=True):
    sim = synthetic_sim(pop["sizes"], pop["weights"])
    counter = bd.BreakdownCounter(sim, YEAR, "t", pop["sources"], per_source=per_source)
    raise_drivers, job_drivers = production_drivers(pop)
    category = np.array([STATES[s] for s in pop["states"]], dtype=object)
    sets = bd.count_breakdowns(counter, pop["frames"], raise_drivers, pop["job"], job_drivers, pop["candidate"],
                               pop["rank"], pop["age"], category, bd.driver_names(COMPONENTS), HEALTH_NAMES)
    return counter, sets


def runner_records(pop):
    w, hh, job = pop["weights"], pop["hh"], pop["job"]
    return [{"counts": {"weighted_candidates_tested": float(sum(w[hh[p]] for p in
                                                                 job.loc[job["rank"] == r, "person_index"]))}}
            for r in sorted(set(job["rank"]))]


def summarize(pop, part, manifest):
    sim = synthetic_sim(pop["sizes"], pop["weights"])
    counter = bd.BreakdownCounter(sim, YEAR, "t", pop["sources"])
    raise_drivers, job_drivers = production_drivers(pop)
    return bd.summarize_counts(counter, pop["frames"], raise_drivers, pop["job"], job_drivers, pop["candidate"],
                               pop["rank"], pop["age"], pop["states"], EXPANSION, bd.driver_names(COMPONENTS),
                               HEALTH_NAMES, runner_records(pop), manifest, part)


# ---------------------------------------------------------------------------
# Counting


def test_driver_names_leave_out_market_income_and_the_premium():
    assert bd.driver_names(COMPONENTS) == NAMES


@given(populations())
def test_counts_match_brute_force_oracle_and_every_invariant_holds(pop):
    counter, sets = run_counts(pop)
    expected = o_metrics(pop)
    assert set(counter.metrics) == set(expected)
    for label, fields in expected.items():
        assert counter.metrics[label] == fields, label
    assert all(bd.check_count_invariants(counter.metrics, NAMES).values())
    for label, fields in counter.sources_totals.items():
        for f, column in fields.items():
            assert column.sum() == pytest.approx(counter.metrics[label][f], rel=1e-12)


@given(populations())
def test_every_breakdown_adds_to_its_group_and_ranks_1_2_never_exceed_all_ranks(pop):
    counter, _ = run_counts(pop, per_source=False)
    m = counter.metrics
    for f in bd.FIELDS:
        assert sum(m[f"pool|expansion_{c}"][f] for c in bd.EXPANSION) == m["pool|candidates"][f]
    for pair in bd.POOL_SPLITS.values():
        assert sum(m[f"pool|{s}"]["adults"] for s in pair) == m["pool|candidates"]["adults"]
    for base, group in bd.DRIVER_GROUPS:
        total = m[f"driver_total|{base}|{group}"]["adults"]
        assert total == m[f"{bd.FULL}|{bd.HEALTH}|{base}|{group}"]["adults"]
        assert sum(m[f"driver|{base}|{group}|{n}"]["adults"] for n in NAMES) == total
        assert sum(m[f"driver_family|{base}|{group}|{x}"]["adults"] for x in bd.FAMILIES) == total
    for base in ("combined", "job"):
        for f in bd.FIELDS:
            assert (sum(m[f"expansion|{base}|strict|{c}"][f] for c in bd.EXPANSION)
                    == m[f"{bd.FULL}|{bd.HEALTH}|{base}|strict"][f])
    for v in (bd.RANKS_1_2, bd.NO_62_64):
        for base in bd.VARIANT_BASES[v]:
            for level in bd.LEVELS:
                full, small = m[f"{bd.FULL}|{bd.HEALTH}|{base}|{level}"], m[f"{v}|{bd.HEALTH}|{base}|{level}"]
                for f in bd.FIELDS:
                    assert small[f] <= full[f]
                    assert full[f] - small[f] == m[f"drop|{v}|{base}|{level}"][f]
            # A narrower test can move a household from strict to additional, never outside below-half.
            for f in bd.FIELDS:
                assert m[f"{v}|{bd.HEALTH}|{base}|additional"][f] <= m[f"{bd.FULL}|{bd.HEALTH}|{base}|below_half"][f]


@settings(max_examples=10)
@given(populations())
def test_job_rows_must_test_exactly_the_candidates_with_their_ranks(pop):
    sim = synthetic_sim(pop["sizes"], pop["weights"])
    raise_drivers, job_drivers = production_drivers(pop)
    category = np.array([STATES[s] for s in pop["states"]], dtype=object)
    names = bd.driver_names(COMPONENTS)
    extra = pop["candidate"].copy()
    untested = np.flatnonzero(~extra)
    if len(untested):
        extra[untested[0]] = True
        counter = bd.BreakdownCounter(sim, YEAR, "a", per_source=False)
        with pytest.raises(ValueError, match="exactly the candidates"):
            bd.count_breakdowns(counter, pop["frames"], raise_drivers, pop["job"], job_drivers, extra, pop["rank"],
                                pop["age"], category, names, HEALTH_NAMES)
    if len(pop["job"]):
        rank = pop["rank"].copy()
        rank[pop["job"]["person_index"].iloc[0]] += 5
        counter = bd.BreakdownCounter(sim, YEAR, "b", per_source=False)
        with pytest.raises(ValueError, match="ranks differ"):
            bd.count_breakdowns(counter, pop["frames"], raise_drivers, pop["job"], job_drivers, pop["candidate"],
                                rank, pop["age"], category, names, HEALTH_NAMES)


def test_a_raise_worker_takes_the_largest_loss_of_the_smallest_raise_that_flags_them():
    flagged = np.array([True, True, False, True])
    flags = [np.array([False, True, False, False]), np.array([True, True, False, False]),
             np.array([True, False, False, False]), np.array([False, False, False, True])]
    drivers = [np.array(["a1", "b1", "c1", "d1"], dtype=object), np.array(["a2", "b2", "c2", "d2"], dtype=object),
               np.array(["a3", "b3", "c3", "d3"], dtype=object), np.array(["", "", "", "job"], dtype=object)]
    assert bd.assign_drivers(flagged, flags, drivers).tolist() == ["a2", "b1", "", "job"]
    with pytest.raises(ValueError, match="no test that flags them"):
        bd.assign_drivers(np.array([True, True, True, True]), flags, drivers)


def test_drivers_count_the_credit_once_and_stop_when_parts_miss_the_measure():
    rows = pd.DataFrame({"d_household_market_income": [1000.0, 1000.0], "d_household_tax_before_refundable_credits":
                         [-100.0, -100.0], "d_snap": [-300.0, 0.0], "d_medicaid_cost": [0.0, 0.0],
                         "d_assigned_aca_ptc": [-50.0, -2000.0], "d_marketplace_net_premium": [-5000.0, 2000.0]})
    rows["d_net_single_ptc"] = rows[[c for c in COMPONENTS if c != "d_marketplace_net_premium"]].sum(axis=1)
    # The premium net of the credit is left out, so the credit itself can be the largest loss.
    assert bd.drivers_from_components(rows, COMPONENTS).tolist() == ["snap", "assigned_aca_ptc"]
    bad = rows.assign(d_net_single_ptc=rows["d_net_single_ptc"] + 5)
    with pytest.raises(ValueError, match="miss d_net_single_ptc"):
        bd.drivers_from_components(bad, COMPONENTS)


def test_expansion_categories_and_strict_json_limits():
    assert bd.expansion_category(1.38) == "expanded"
    assert bd.expansion_category(2.15) == "expanded"
    assert bd.expansion_category(1.0) == "not_expanded_partial"
    assert bd.expansion_category(-math.inf) == "not_expanded"
    with pytest.raises(ValueError):
        bd.expansion_category(float("nan"))
    assert bd.json_limit(-math.inf) is None and bd.json_limit(1.38) == 1.38


@given(populations())
def test_count_checks_catch_a_largest_loss_that_does_not_add_up(pop):
    counter, _ = run_counts(pop, per_source=False)
    metrics = copy.deepcopy(counter.metrics)
    metrics["driver|combined|strict|snap"]["adults"] += 1.0
    assert not bd.check_count_invariants(metrics, NAMES)["largest_losses_add_to_each_group"]
    metrics = copy.deepcopy(counter.metrics)
    metrics[f"{bd.RANKS_1_2}|{bd.HEALTH}|job|strict"]["households"] = (
        metrics[f"{bd.FULL}|{bd.HEALTH}|job|strict"]["households"] + 1.0)
    assert not bd.check_count_invariants(metrics, NAMES)["narrower_job_test_never_raises_strict_or_below_half"]


# ---------------------------------------------------------------------------
# Benchmark


def test_benchmark_comparators_follow_the_published_rows():
    first = bd.benchmark_comparators(bd.BENCHMARK_TABLES[0])
    assert first == {"did_not_work_18_64": 45_914e3, "excluding_ill_or_disabled": 33_008e3,
                     "excluding_ill_or_disabled_and_school_or_other": 22_039e3}
    out = bd.external_benchmark({"estimate": 30e6, "interval_95": [28e6, 32e6]})
    ratio = out["sources"][0]["pool_over_comparator"]["excluding_ill_or_disabled"]
    assert ratio["estimate"] == pytest.approx(30e6 / 33_008e3)
    broken = copy.deepcopy(bd.BENCHMARK_TABLES[0])
    broken["did_not_work_last_year_thousands"]["total"] += 100
    with pytest.raises(ValueError, match="do not add"):
        bd.benchmark_comparators(broken)


# ---------------------------------------------------------------------------
# Four parts: records, bootstrap and the combine step's assembly


MANIFEST = {"digest": "d" * 64, "code": {"commit": "c", "sha256": {}}}


def _npz(totals):
    buffer = io.BytesIO()
    np.savez_compressed(buffer, sources=totals["sources"], matrix=totals["matrix"], columns=np.array(totals["columns"]))
    return buffer.getvalue()


@settings(max_examples=6)
@given(st.tuples(*(populations(offset=100 * p) for p in range(ci.PARTS))))
def test_four_parts_bootstrap_and_assemble_with_parts_adding_to_groups(pops):
    records, npz = [], []
    for part, pop in enumerate(pops):
        record, totals = summarize(pop, part, MANIFEST)
        assert all(v["pass"] is True for v in record["invariants"].values())
        record = json.loads(json.dumps(record, allow_nan=False))  # as the part file round-trips
        records.append(record)
        npz.append(_npz(totals))
    boot = bd.bootstrap_breakdowns(records, npz, draws=40, seed=0)
    boot = json.loads(json.dumps(boot, allow_nan=False))
    result = bd.build_result(records, boot, MANIFEST)
    json.dumps(result, allow_nan=False)
    assert all(result["invariants_national"].values())
    pool = result["candidate_pool"]
    assert pool["sample_candidates"] == sum(len(p["job"]) for p in pops)
    adults = pool["candidates"]["adults"]["estimate"]
    assert adults == sum(o_adults(p, p["candidate"]) for p in pops)
    assert pool["rank_1_2"]["adults"]["estimate"] + pool["rank_3_plus"]["adults"]["estimate"] == pytest.approx(adults)
    for base in bd.BASES:
        for g in bd.GROUPS:
            for f in bd.FIELDS:
                assert (result["ranks_1_2"][base]["ranks_1_2"][g][f]["estimate"]
                        <= result["ranks_1_2"][base]["all_ranks"][g][f]["estimate"] + 1e-9
                        or g == "additional")
    for key, group in result["largest_loss"]["groups"].items():
        total = group["flagged_adults"]["adults"]["estimate"]
        assert sum(v["adults"]["estimate"] for v in group["by_largest_loss"].values()) == pytest.approx(total)
        shares = [v["share"]["estimate"] for v in group["by_largest_loss"].values()]
        if total:
            assert sum(shares) == pytest.approx(1.0)
        for v in group["by_largest_loss"].values():
            lo, hi = v["share"]["interval_95"]
            assert lo is None or 0.0 <= lo <= hi <= 1.0
    for base in ("combined", "job"):
        section = result["medicaid_expansion"][f"{base}_strict"]
        for f in bd.FIELDS:
            assert (sum(section[c][f]["estimate"] for c in bd.EXPANSION)
                    == pytest.approx(section["total"][f]["estimate"]))
    assert result["medicaid_expansion"]["states"]["not_expanded"] == ["BB"] or not any(
        "BB" in p["states"] for p in pops)
    for base in ("combined", "job", "combined_1000"):
        support = result["without_health"][base]["support"]
        assert support["source_households"] <= boot["source_households"]
    # A part missing from the bootstrap stops it.
    with pytest.raises(ValueError, match="every part"):
        bd.bootstrap_breakdowns(records[:3], npz[:3], draws=5, seed=0)


def test_model_expansion_reads_the_2017_adult_limits_from_the_tax_benefit_system(system):
    """The pinned model's adult group as the 2017 run reads it: the January 2018 limits, backdated."""
    from types import SimpleNamespace

    states = [c for c in system.parameters.gov.hhs.medicaid.eligibility.categories.adult.income_limit.children]
    out = bd.model_expansion(SimpleNamespace(tax_benefit_system=system), states)
    json.dumps(out, allow_nan=False)
    assert all(e["limit_2017"] == e["limit_2018"] for e in out.values())
    covered = [s for s in out if s in STATES_51]
    assert len(covered) == 51
    expanded = sorted(s for s in covered if out[s]["category"] == "expanded")
    assert "DC" in expanded and "TX" not in expanded and out["WI"]["category"] == "not_expanded_partial"
    assert out["TX"]["limit_2017"] is None


STATES_51 = {"AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS",
             "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC",
             "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"}
