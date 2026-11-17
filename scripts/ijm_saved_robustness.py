"""Health-value and finite-raise robustness from saved actual counterfactuals.

No new tax/benefit scenarios are evaluated. CSV survey weights are never read.
New flags use the frozen experiment's entity mapping and MicroSeries methods.
The bootstrap resamples source-household aggregate outputs, after MicroSeries
has applied calibrated weights, keeping duplicate copies in the same cluster.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path


def cap_thread_limits(environ):
    """Cap this process at two threads without raising configured lower limits."""
    limits = {}
    for setting in (
        "OPENBLAS_NUM_THREADS",
        "OMP_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "BLIS_NUM_THREADS",
    ):
        current = environ.get(setting)
        if current is None:
            effective = 2
        else:
            try:
                configured = int(current)
            except ValueError as exc:
                raise ValueError(f"cannot safely cap nonnumeric {setting}") from exc
            if configured < 1:
                raise ValueError(f"cannot safely cap nonpositive {setting}")
            effective = min(configured, 2)
        environ[setting] = str(effective)
        limits[setting] = effective
    return limits


# Only this child process changes; existing lower limits remain lower.
THREAD_LIMITS = cap_thread_limits(os.environ)

import numpy as np
import pandas as pd
from microdf import MicroSeries

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.driver_intervals import interval, resample
from scripts.expanded_historical import (
    build_historical_simulation,
    historical_provenance,
)
from scripts.expanded_raise_union import (
    CHANGES,
    THRESHOLDS,
    add_variable,
    assert_counts_match,
    assert_scalar_match,
    flag_counts,
    full_mask,
    household_combination,
    household_counts,
    load_part_records,
    retention_flags,
    set_person_flag,
    sha256,
    validate_same_universe,
)

SOURCE_COMMIT = "9a814a3b3b53c0ecd6e1737b6ec862c31300ef6f"
SOURCE_SHA256 = "6496cc4393d4d3c6574f76eca231de5898c803b9067645591fd5c4d3e65aee84"
SOURCE_BYTES = 826917837
VALUATIONS = {"cash": (None, None), "full": (None, 1.0)}
for family in ("medicaid", "medicaid_chip"):
    for alpha in (0.0, 0.3, 0.5):
        VALUATIONS[f"{family}_a{alpha:g}"] = (family, alpha)
POPULATIONS = ("all_selected_adults", "current_workers")
RESAMPLE_FIELDS = ("adults", "households", "household_members")
MAIN_VALUATIONS = {
    "cash",
    "full",
    "medicaid_chip_a0",
    "medicaid_chip_a0.3",
    "medicaid_chip_a0.5",
}


def verified_input():
    """Require the actual cached H5 bytes from the public immutable revision."""
    from huggingface_hub import hf_hub_download

    path = Path(
        hf_hub_download(
            "policyengine/populace-us",
            "populace_us_2024.h5",
            repo_type="dataset",
            revision=SOURCE_COMMIT,
        )
    )
    digest = sha256(path)
    if path.stat().st_size != SOURCE_BYTES or digest != SOURCE_SHA256:
        raise ValueError(
            "public historical H5 bytes differ from the audited experiment"
        )
    return path, {
        "resolved_commit": SOURCE_COMMIT,
        "sha256": digest,
        "bytes": path.stat().st_size,
        "file": "populace_us_2024.h5",
    }


def load_mapping(path, year, part):
    """Load exactly the verified bytes, avoiding mutable release-tag resolution."""
    from policyengine_us import CountryTaxBenefitSystem
    from policyengine_us.data.dataset_schema import USSingleYearDataset

    from cliffs2017.deflate import deflate, partition

    data = partition(USSingleYearDataset(file_path=str(path)), 4, part, 0)
    if year < int(data.time_period):
        data, _ = deflate(data, CountryTaxBenefitSystem(), year)
    return data, build_historical_simulation(data, year, health=False)


def component_checks(frame, health_columns):
    """Check saved accounting identities; preserve native floating-point residuals."""
    components = [
        c
        for c in frame
        if c.startswith("d_")
        and c not in {"d_net", "d_parts", "d_net_single_ptc", "d_net_without_health"}
    ]
    cash = [c for c in components if c not in health_columns]
    ptc_error = np.max(
        np.abs(frame.d_net - frame.d_marketplace_net_premium - frame.d_net_single_ptc)
    )
    cash_error = np.max(np.abs(frame[cash].sum(axis=1) - frame.d_net_without_health))
    parts_error = np.max(np.abs(frame[components].sum(axis=1) - frame.d_parts))
    if max(ptc_error, cash_error, parts_error) > 1e-6:
        raise ValueError("saved components fail their accounting identities")
    return {
        "ptc_once_identity_max_abs": float(ptc_error),
        "cash_component_identity_max_abs": float(cash_error),
        "parts_sum_identity_max_abs": float(parts_error),
        "native_net_minus_parts_max_abs": float(
            np.max(np.abs(frame.d_net - frame.d_parts))
        ),
    }


def resource_change(frame, valuation):
    """Revalue actual benefit changes; keep PTC and premium accounting fixed."""
    family, alpha = VALUATIONS[valuation]
    if valuation == "cash":
        return frame.d_net_without_health.to_numpy()
    full = frame.d_net_single_ptc.to_numpy()
    if valuation == "full":
        return full
    priced = frame.d_medicaid_cost.to_numpy()
    if family == "medicaid_chip":
        priced = priced + frame.d_chip.to_numpy()
    return full + (alpha - 1) * priced


def scenario_flag(frame, delta, cutoff, population, people):
    """Apply eligibility in this frame's order, then restore person identity."""
    eligible = frame.worker if population == "current_workers" else None
    return full_mask(
        frame, retention_flags(frame.change, delta, cutoff, eligible), people
    )


def weighted_cluster_outputs(series, cluster_ids, source_ids):
    """Return already weighted aggregate model outcomes, never survey weights.

    MicroSeries.groupby applies its embedded household-calibrated weights.
    The returned ordinary Series contains aggregate outputs, suitable for a
    source-cluster bootstrap. Zero-output clusters remain in the sampling base.
    """
    if not isinstance(series, MicroSeries):
        raise TypeError("population aggregation requires a MicroSeries")
    if len(series) != len(cluster_ids):
        raise ValueError("source-household mapping does not align")
    nonzero = series[series != 0]
    if nonzero.empty:
        grouped = pd.Series(0.0, index=source_ids)
    else:
        groups = pd.Series(cluster_ids, index=series.index).loc[nonzero.index]
        grouped = (
            nonzero.groupby(groups, sort=True).sum().reindex(source_ids, fill_value=0.0)
        )
    if isinstance(grouped, MicroSeries):
        raise TypeError("cluster reduction unexpectedly retained observation weights")
    if not math.isclose(grouped.sum(), series.sum(), rel_tol=1e-12, abs_tol=1e-6):
        raise ValueError("cluster aggregate outputs do not reproduce MicroSeries total")
    return grouped


class Collector:
    def __init__(self, simulation, dataset, year):
        self.sim, self.year = simulation, year
        self.people = len(dataset.person)
        household_sources = dataset.household.set_index(
            "household_id"
        ).household_source_id
        self.source_ids = np.unique(household_sources.to_numpy())
        self.hh_clusters = dataset.household.household_source_id.to_numpy()
        self.person_clusters = dataset.person.person_household_id.map(
            household_sources
        ).to_numpy()
        if pd.isna(self.person_clusters).any():
            raise ValueError("person lacks its source-household ID")
        self.points, self.columns, self.names = {}, {}, {}
        self.index = 0

    def record(self, key, flags, bootstrap_fields=()):
        name = f"ijm_saved_flag_{self.index}"
        self.index += 1
        household = set_person_flag(self.sim, name, flags, self.year)
        counts = flag_counts(self.sim, name, household, self.year)
        self.points[key] = counts
        self.names[key] = (name, household)
        for field in bootstrap_fields:
            variable, entity = (
                (name, "person")
                if field == "adults"
                else (household, "household" if field == "households" else "person")
            )
            series = self.sim.calc(variable, period=self.year, map_to=entity)
            clusters = (
                self.hh_clusters if entity == "household" else self.person_clusters
            )
            self.columns[key + "|" + field] = weighted_cluster_outputs(
                series, clusters, self.source_ids
            )
        return counts

    def additional(self, key, half, strict):
        name = f"ijm_saved_extra_{self.index}"
        self.index += 1
        add_variable(
            self.sim,
            name,
            "household",
            household_combination(
                self.names[half][1], self.names[strict][1], "left_only"
            ),
        )
        self.points[key] = household_counts(self.sim, name, self.year)
        for field in ("households", "household_members"):
            assert_scalar_match(
                self.points[half][field],
                self.points[strict][field] + self.points[key][field],
                key + ".nested_" + field,
            )


def bootstrap_fields(config, population, scope, threshold=None):
    if scope == "raise":
        return (
            ("adults",)
            if population == "all_selected_adults" and config in MAIN_VALUATIONS
            else ()
        )
    if threshold not in {"retains_lt_50pct", "retains_lt_0pct"}:
        return ()
    if population == "current_workers":
        if config in {"cash", "full"}:
            return RESAMPLE_FIELDS
        if config.startswith("medicaid_chip_"):
            return ("household_members",)
    if (
        population == "all_selected_adults"
        and config in {"cash", "full"}
        and threshold == "retains_lt_0pct"
    ):
        return ("adults", "household_members")
    return ()


def one_part(path, source, year, part):
    data, sim = load_mapping(path, year, part)
    frames, records, inputs = load_part_records(source, year, 4, part, 0, data.person)
    accounting = {}
    for key, record in records.items():
        csv = source / record["per_person_file"]
        columns = pd.read_csv(csv, nrows=0).columns
        # Explicitly omit the stored weight column; all signed components exist.
        frames[key] = pd.read_csv(csv, usecols=[c for c in columns if c != "weight"])
        if sha256(csv) != inputs[list(records).index(key)]["rows_sha256"]:
            raise ValueError("saved component rows changed while being read")
        accounting[key] = component_checks(frames[key], record["health_parts"])
    validate_same_universe(frames)
    c = Collector(sim, data, year)
    first = frames["raise_1000"]
    selected = full_mask(first, np.ones(len(first), dtype=bool), len(data.person))
    worker = full_mask(first, first.worker.to_numpy(dtype=bool), len(data.person))
    c.record("population/all_selected_adults", selected)
    c.record("population/current_workers", worker)
    for key in CHANGES:
        assert_scalar_match(
            c.points["population/current_workers"]["adults"],
            records[key]["change"]["workers_reached"],
            key + ".workers_reached",
        )
    for config in VALUATIONS:
        for population in POPULATIONS:
            union_masks = {
                threshold: np.zeros(c.people, dtype=bool) for threshold in THRESHOLDS
            }
            for key, frame in frames.items():
                change = resource_change(frame, config)
                for threshold, cutoff in THRESHOLDS.items():
                    mask = scenario_flag(frame, change, cutoff, population, c.people)
                    union_masks[threshold] |= mask
                    if cutoff == 0:
                        metric = f"{config}/{population}/{key}/strict"
                        counts = c.record(
                            metric, mask, bootstrap_fields(config, population, "raise")
                        )
                        if config in {"cash", "full"}:
                            measure = (
                                "without_health" if config == "cash" else "with_health"
                            )
                            if population == "all_selected_adults":
                                assert_counts_match(
                                    counts, records[key]["change"][measure], metric
                                )
                            else:
                                assert_scalar_match(
                                    counts["adults"],
                                    records[key]["change"][measure]["workers_on_cliff"],
                                    metric + ".workers_on_cliff",
                                )
                        if population == "all_selected_adults" and config not in {
                            "cash",
                            "full",
                        }:
                            original = full_mask(
                                frame,
                                retention_flags(
                                    frame.change, frame.d_net_single_ptc, 0
                                ),
                                c.people,
                            )
                            c.record(
                                f"{config}/{population}/{key}/new_since_full",
                                mask & ~original,
                            )
            previous = None
            for threshold in THRESHOLDS:
                mask = union_masks[threshold]
                if previous is not None and (mask & ~previous).any():
                    raise ValueError("finite-raise retention unions are not nested")
                previous = mask
                metric = f"{config}/{population}/union/{threshold}"
                c.record(
                    metric,
                    mask,
                    bootstrap_fields(config, population, "union", threshold),
                )
            half = f"{config}/{population}/union/retains_lt_50pct"
            strict = f"{config}/{population}/union/retains_lt_0pct"
            c.additional(f"{config}/{population}/additional_below_half", half, strict)
    contributions = pd.DataFrame(c.columns, index=c.source_ids)
    result = {
        "part": part,
        "points": c.points,
        "inputs": inputs,
        "accounting_checks": accounting,
        "source_households": len(c.source_ids),
    }
    del frames, records, sim, data, c
    gc.collect()
    return result, contributions


def finish_year(parts, clusters, draws, seed):
    contributions = pd.concat(clusters).sort_index()
    if not contributions.index.is_unique:
        raise ValueError("a source-household cluster was split across partition parts")
    points = {}
    for key, counts in parts[0]["points"].items():
        points[key] = {
            field: sum(p["points"][key][field] for p in parts) for field in counts
        }
    # These are already weighted aggregate model outputs, not record weights.
    simulations = resample(contributions.to_numpy(), draws, seed)
    estimates = {
        name: simulations[:, i] for i, name in enumerate(contributions.columns)
    }
    intervals = {}
    for name, values in estimates.items():
        key, field = name.rsplit("|", 1)
        assert_scalar_match(contributions[name].sum(), points[key][field], name)
        intervals.setdefault(key, {})[field] = interval(values)
    for config in VALUATIONS:
        for population in POPULATIONS:
            for field in ("households", "household_members"):
                half = f"{config}/{population}/union/retains_lt_50pct|{field}"
                strict = f"{config}/{population}/union/retains_lt_0pct|{field}"
                if half in estimates and strict in estimates:
                    key = f"{config}/{population}/additional_below_half"
                    intervals.setdefault(key, {})[field] = interval(
                        estimates[half] - estimates[strict]
                    )
    interaction_keys = (
        "full/all_selected_adults/raise_5000/strict",
        "full/all_selected_adults/raise_1000/strict",
        "cash/all_selected_adults/raise_5000/strict",
        "cash/all_selected_adults/raise_1000/strict",
    )
    signs = (1, -1, -1, 1)
    interaction_draws = sum(
        sign * estimates[key + "|adults"] for sign, key in zip(signs, interaction_keys)
    )
    interaction = {
        "adult_count_difference": sum(
            sign * points[key]["adults"] for sign, key in zip(signs, interaction_keys)
        ),
        "interval_95": interval(interaction_draws),
        "definition": "[N_full(5000)-N_full(1000)]-[N_cash(5000)-N_cash(1000)]; paired source-household resamples",
    }
    return {
        "points": points,
        "interval_95": intervals,
        "paired_increment_resource_interaction": interaction,
        "source_households": len(contributions),
        "bootstrap_columns": len(contributions.columns),
        "parts": parts,
    }


def write_tables(result):
    lines = [
        "# Saved-counterfactual robustness",
        "",
        "All counts are millions. Intervals cover sampling error only. The worker universe comprises current workers among up to two adults ranked by market income per household. The grid contains $1,000, $2,000 and $5,000 raises.",
        "",
        "## Current-worker household-member union",
        "",
        "| Scenario | Resources | Strict-loss members (95% interval) | Below-half members (95% interval) | Additional members, excluding all strict-loss households (95% interval) |",
        "|---|---|---:|---:|---:|",
    ]

    def cell(year, key, field):
        point = year["points"][key][field] / 1e6
        ci = year["interval_95"].get(key, {}).get(field)
        return (
            f"{point:.3f} ({ci[0] / 1e6:.3f}–{ci[1] / 1e6:.3f})"
            if ci
            else f"{point:.3f}"
        )

    for year, data in result["years"].items():
        for config in ("cash", "full"):
            prefix = f"{config}/current_workers/"
            lines.append(
                f"| {year} | {config} | {cell(data, prefix + 'union/retains_lt_0pct', 'household_members')} | {cell(data, prefix + 'union/retains_lt_50pct', 'household_members')} | {cell(data, prefix + 'additional_below_half', 'household_members')} |"
            )
    lines += [
        "",
        "## Medicaid and CHIP value multiplier",
        "",
        "ACA PTC remains counted once; all other health components and premiums retain their original coefficients. Alpha is an accounting assumption, not an estimated welfare valuation.",
        "",
        "| Scenario | Alpha | Adults losing resources after $1k (95% interval) | Adults losing resources after $5k (95% interval) |",
        "|---|---:|---:|---:|",
    ]
    for year, data in result["years"].items():
        for alpha in (0, 0.3, 0.5, 1):
            config = "full" if alpha == 1 else f"medicaid_chip_a{alpha:g}"
            lines.append(
                f"| {year} | {alpha:g} | {cell(data, config + '/all_selected_adults/raise_1000/strict', 'adults')} | {cell(data, config + '/all_selected_adults/raise_5000/strict', 'adults')} |"
            )
    lines += [
        "",
        "## Paired increment-by-resource contrast",
        "",
        "| Scenario | Adult contrast (millions) | 95% interval |",
        "|---|---:|---:|",
    ]
    for year, data in result["years"].items():
        x = data["paired_increment_resource_interaction"]
        lines.append(
            f"| {year} | {x['adult_count_difference'] / 1e6:.3f} | {x['interval_95'][0] / 1e6:.3f}–{x['interval_95'][1] / 1e6:.3f} |"
        )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--draws", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--out", type=Path, default=ROOT / "results/ijm_saved_robustness.json"
    )
    parser.add_argument(
        "--table", type=Path, default=ROOT / "results/ijm_saved_robustness.md"
    )
    args = parser.parse_args()
    if args.draws < 200:
        raise ValueError("at least 200 source-household resamples required")
    start = time.monotonic()
    code_hash = sha256(Path(__file__))
    path, input_provenance = verified_input()
    years = {}
    for year in (2017, 2025):
        parts, clusters = [], []
        for part in range(4):
            stats, contribution = one_part(path, args.source_root.resolve(), year, part)
            parts.append(stats)
            clusters.append(contribution)
            print(
                f"{year} part {part}: component identities and original totals reproduced",
                flush=True,
            )
        print(
            f"{year}: resampling {sum(len(c) for c in clusters)} source households",
            flush=True,
        )
        years[str(year)] = finish_year(parts, clusters, args.draws, args.seed)
        years[str(year)]["scenario"] = {
            "policy": (
                "2017 federal rules, model's 2018 Medicaid/CHIP limits and specified later state rules"
                if year == 2017
                else "2025 policy rules of the frozen model, with CSFP excluded to align the benefit list"
            ),
            "population": (
                "2024-based Microcosm data scaled to 2017 size, incomes and prices"
                if year == 2017
                else "The same 2024-based Microcosm data uprated by the frozen model to 2025"
            ),
        }
        del parts, clusters
        gc.collect()
    if sha256(Path(__file__)) != code_hash:
        raise ValueError("postprocessing source changed during execution")
    adapter = historical_provenance()
    for historical_field in ("experiment", "policy", "population"):
        adapter.pop(historical_field)
    adapter["experiment"] = "frozen-saved-counterfactuals-2017-and-2025"
    result = {
        "status": "completed_saved_counterfactual_measurement_robustness",
        "years": years,
        "draws": args.draws,
        "seed": args.seed,
        "effective_thread_limits": THREAD_LIMITS,
        "interval_method": "95% percentile intervals from paired resampling of every original source household; duplicate copies share one draw; sampling error only",
        "grid": list(CHANGES.values()),
        "thresholds": THRESHOLDS,
        "valuations": {
            key: {"family": spec[0], "alpha": spec[1]}
            for key, spec in VALUATIONS.items()
        },
        "valuation_definition": "R_alpha = saved corrected health-inclusive change + (alpha-1) times the actual signed Medicaid change, plus CHIP change when specified. ACA PTC remains counted once; CHIP premiums, other health programs and native rounding residual remain unchanged. Cash uses the saved non-health-component sum.",
        "limitations": [
            "Only top-two adults by market income were perturbed in the source runs.",
            "Current-worker union excludes nonworkers; finite grid makes no continuum claim.",
            "Revaluation changes accounting, not eligibility, take-up or behavior.",
            "The 2017 case applies hybrid historical rules to scaled 2024-based data.",
            "Bootstrap omits model, calibration, take-up, valuation and policy-reconstruction uncertainty, CPS strata and repeated survey households across years.",
        ],
        "historical_adapter": adapter,
        "source_input": input_provenance,
        "code": {
            "commit_at_run": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "script_sha256": code_hash,
            "historical_loader_sha256": sha256(ROOT / "scripts/expanded_historical.py"),
            "aggregation_helpers_sha256": sha256(
                ROOT / "scripts/expanded_raise_union.py"
            ),
        },
        "seconds": round(time.monotonic() - start, 2),
        "csv_weight_columns_read": False,
    }
    for target, content in (
        (args.out, json.dumps(result, indent=2, sort_keys=True) + "\n"),
        (args.table, write_tables(result)),
    ):
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(content)
        tmp.replace(target)
    print(f"wrote {args.out} and {args.table}; {result['seconds']} seconds", flush=True)


if __name__ == "__main__":
    main()
