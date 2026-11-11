"""Cliff counts for other changes in earnings, with intervals, from all four parts.

scripts/earnings_changes.py tests every adult with several changes in
earnings, one household part at a time. This script reads the four parts of
each year (results/earnings_changes/parts/ and their per-person rows in
results/parts/per_person/) and reports, for each year and change:

- the adults the change reaches, and those whose household's net income moves
  against it (falls under a raise, rises under a cut), before health coverage
  counts and counting it with the premium tax credit counted once: the count
  with a 95% interval, its workers and their share of all workers, its
  households and their members, and the fewest source households that supply
  half of it;
- the part of net income that moves most against the change (for a raise, the
  largest loss; for a cut, the largest gain), as shares of the count;
- the adults whose tax unit crosses 400% of the poverty line
  (``aca_magi_fraction`` 4.0, where the premium tax credit ended before 2021):
  how many, how many lose (raise) or gain (cut) their tax unit's whole credit,
  how many of them face the cliff counting health coverage, and for how many
  the credit is the part that moves most against the change;
- for each raise and cut of the same size, the adults on either side: those
  whose household would lose from the raise or gain from the cut.

Intervals come from 5,000 resamples of Microcosm's source households, as in
scripts/driver_intervals.py: the 2.5th and 97.5th percentiles, sampling error
only. Households and members are the parts' totals, without intervals.

It stops unless the rows reproduce every part's counts, the $1,000 raise
reproduces the final runs' counts, and every part ran the same code. The
output records HEAD, so it also stops if this script, scripts/earnings_changes.py
or cliffs2017/ has uncommitted changes.

usage: python scripts/earnings_changes_summary.py
  # writes results/earnings_changes.json and results/earnings_changes.md
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cliffs2017.decompose import primary_driver  # noqa: E402
from cliffs2017.run import FILENAME, REPO, REVISION  # noqa: E402
from scripts.driver_intervals import interval, resample, source_index, support  # noqa: E402

PARTS = ROOT / "results" / "earnings_changes" / "parts"
OUT = ROOT / "results" / "earnings_changes.json"
MARKDOWN = ROOT / "results" / "earnings_changes.md"
YEARS = (2017, 2025)
N_PARTS = 4
DRAWS = 5_000
SEED = 0
TOLERANCE = 1e-9
LIMIT = 4.0
MEASURES = {"without_health": "d_net_without_health", "with_health": "d_net_single_ptc"}
HEADLINE = ("people_on_cliff", "workers_on_cliff", "households_with_person_on_cliff", "people_in_those_households")
NOT_PARTS = ("d_net", "d_parts", "d_net_single_ptc", "d_net_without_health", "d_household_market_income")
PTC = "assigned_aca_ptc"


def check(label: str, ours: float, committed: float) -> None:
    if abs(ours - committed) > TOLERANCE * max(abs(committed), 1.0):
        raise ValueError(f"{label}: rows give {ours:,.6f}, committed {committed:,.6f}")


def moving_parts(rows: pd.DataFrame, measure: str, health_parts: list[str]) -> list[str]:
    """The parts that make up a measure's change, market income aside."""
    cols = [c for c in rows.columns if c.startswith("d_") and c not in NOT_PARTS]
    if measure == "without_health":
        return [c for c in cols if c not in health_parts]
    # Counting the credit once leaves out the premium net of the credit, as cliffs2017.run does.
    return [c for c in cols if c != "d_marketplace_net_premium"]


def driver(rows: pd.DataFrame, columns: list[str], sign: int) -> pd.Series:
    """The part that moves net income most against the change: for a raise the
    largest loss, for a cut the largest gain (the largest loss once signs flip)."""
    frame = rows[columns] * sign
    return primary_driver(frame).to_numpy()


def either_side(person, key_col, up: str, down: str, up_flags, down_flags) -> np.ndarray:
    """One row for each adult flagged under the raise ``up`` or the cut ``down``.

    ``person`` and ``key_col`` give each row's adult and change; the flags mark
    the rows whose net income moves against their change. An adult flagged
    under either change gets the raise's row if the raise reaches them and the
    cut's row otherwise, so each counts once, at their own weight.
    """
    person = np.asarray(person)
    key_col = np.asarray(key_col)
    ids = np.union1d(person[np.asarray(up_flags, dtype=bool)], person[np.asarray(down_flags, dtype=bool)])
    raised = np.isin(person, person[key_col == up])
    either = np.isin(person, ids) & ((key_col == up) | ((key_col == down) & ~raised))
    if len(np.unique(person[either])) != either.sum() or either.sum() != len(ids):
        raise ValueError(f"{up}/{down}: the either-side rows miss or repeat an adult")
    return either


def load_year(year: int, dataset: str) -> tuple[list[dict], pd.DataFrame]:
    parts, rows = [], []
    for i in range(N_PARTS):
        path = PARTS / f"changes_{year}_p{N_PARTS}_{i}_s0.json"
        if not path.exists():
            raise FileNotFoundError(f"{path} is missing: run scripts/earnings_changes.py --year {year} --part {i}")
        part = json.loads(path.read_text())
        if part["dataset"] != dataset:
            raise ValueError(f"{path} read {part['dataset']}, not {dataset}")
        frame = pd.read_csv(ROOT / part["per_person_file"])
        for key, entry in part["changes"].items():
            block = frame[frame["change_key"] == key]
            for measure, column in MEASURES.items():
                flags = block["change"].to_numpy() * block[column].to_numpy() < 0
                check(f"{path.name} {key} {measure}", float(block["weight"][flags].sum()),
                      entry[measure]["people_on_cliff"])
            check(f"{path.name} {key} reached", float(block["weight"].sum()), entry["adults_reached"])
        parts.append(part)
        rows.append(frame)
    for key in ("code", "versions", "stored_input_renames", "health_parts"):
        if any(p[key] != parts[0][key] for p in parts[1:]):
            raise ValueError(f"{year}: the parts differ in {key}")
    if sorted(p["part"] for p in parts) != list(range(N_PARTS)):
        raise ValueError(f"{year}: parts {sorted(p['part'] for p in parts)}")
    out = pd.concat(rows, ignore_index=True)
    if out[["change_key", "person_id"]].duplicated().any():
        raise ValueError(f"{year}: a person appears twice under one change")
    return parts, out


def check_finals(year: int, parts: list[dict]) -> None:
    plain = json.loads((ROOT / "results" / f"final_{year}_plain.json").read_text())
    health = json.loads((ROOT / "results" / f"final_{year}_health.json").read_text())
    for key in HEADLINE:
        check(f"{year} +1000 without health {key}",
              sum(p["changes"]["raise_1000"]["without_health"][key] for p in parts), plain[key])
        check(f"{year} +1000 with health {key}",
              sum(p["changes"]["raise_1000"]["with_health"][key] for p in parts),
              health["premium_tax_credit_counted_once"][key])


def main() -> int:
    script = Path(__file__).resolve().relative_to(ROOT)
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", str(script), "scripts/earnings_changes.py", "cliffs2017"],
        cwd=ROOT, capture_output=True, text=True,
    ).stdout.strip()
    if dirty:
        raise SystemExit(f"commit these first: the output records HEAD\n{dirty}")
    from huggingface_hub import hf_hub_download

    dataset = f"{REPO}/{FILENAME}@{REVISION}"
    path = hf_hub_download(REPO, FILENAME, repo_type="dataset", revision=REVISION)
    households = pd.read_hdf(path, "household", columns=["household_id", "household_source_id"])

    out = {
        "note": (
            "Adults whose household's net income moves against a change in their earnings "
            "(falls under a raise, rises under a cut), for several changes, with 95% percentile "
            "intervals from resampling Microcosm's source households (sampling error only)."
        ),
        "commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "dataset": dataset,
        "draws": DRAWS,
        "seed": SEED,
        "years": {},
    }
    for year in YEARS:
        parts, rows = load_year(year, dataset)
        check_finals(year, parts)
        health_parts = parts[0]["health_parts"]
        workers = sum(p["workers"] for p in parts)
        index, n = source_index(rows["household_id"].to_numpy(), households)
        rows = rows.assign(source=index)
        columns, labels, samples = [], [], []

        def add(label, mask):
            mask = np.asarray(mask, dtype=bool)
            columns.append(np.bincount(rows["source"].to_numpy()[mask], weights=rows["weight"].to_numpy()[mask], minlength=n))
            labels.append(label)
            samples.append(int(mask.sum()))

        keys = list(parts[0]["changes"])
        flags = {}
        for key in keys:
            block = rows["change_key"].to_numpy() == key
            change = rows["change"].to_numpy()
            add((key, "reached", None), block)
            for measure, column in MEASURES.items():
                on = block & (change * rows[column].to_numpy() < 0)
                flags[(key, measure)] = on
                add((key, measure, None), on)
            base, alt = rows["base_aca_magi_fraction"].to_numpy(), rows["alt_aca_magi_fraction"].to_numpy()
            crossed = block & ((base < LIMIT) != (alt < LIMIT))
            sign = np.sign(change)
            base_ptc, alt_ptc = rows[f"base_{PTC}"].to_numpy(), rows[f"alt_{PTC}"].to_numpy()
            whole = np.where(sign > 0, (base_ptc > 0) & (alt_ptc <= 0), (base_ptc <= 0) & (alt_ptc > 0))
            add((key, "crossed_400", None), crossed)
            add((key, "crossed_400_whole_credit", None), crossed & whole)
            add((key, "crossed_400_on_cliff_with_health", None), crossed & flags[(key, "with_health")])
            on = flags[(key, "with_health")]
            drivers = np.full(len(rows), "", dtype=object)
            cols = moving_parts(rows, "with_health", health_parts)
            drivers[on] = driver(rows[on], cols, int(np.sign(change[on][0])) if on.any() else 1)
            add((key, "credit_moves_most_with_health", None), on & (drivers == PTC))
            add((key, "crossed_400_credit_moves_most", None), crossed & on & (drivers == PTC))
        # Either side: the adults whose household loses from a raise or gains from the cut of the same size.
        pairs = [(k, "cut" + k[len("raise"):]) for k in keys if k.startswith("raise") and "cut" + k[len("raise"):] in keys]
        key_col = rows["change_key"].to_numpy()
        person = rows["person_id"].to_numpy()
        for up, down in pairs:
            for measure in MEASURES:
                add((up, f"either_side_{measure}", down),
                    either_side(person, key_col, up, down, flags[(up, measure)], flags[(down, measure)]))
        stats = np.column_stack(columns)
        draws = resample(stats, DRAWS, SEED)
        found = {}
        for j, label in enumerate(labels):
            found[label] = dict(
                adults=float(stats[:, j].sum()),
                interval_95=interval(draws[:, j]),
                **{k: v for k, v in support(stats[:, j], samples[j]).items()},
            )
        year_out = {"workers": workers, "changes": {}}
        for key in keys:
            entry = parts[0]["changes"][key]
            c = dict(label=entry["label"], amount=entry["amount"], share=entry["share"])
            c["adults_reached"] = found[(key, "reached", None)]
            c["workers_reached"] = sum(p["changes"][key]["workers_reached"] for p in parts)
            for measure, column in MEASURES.items():
                totals = {h: sum(p["changes"][key][measure][h] for p in parts) for h in HEADLINE}
                f = found[(key, measure, None)]
                on = flags[(key, measure)]
                sign = 1 if entry["amount"] > 0 or entry["share"] > 0 else -1
                cols = moving_parts(rows, measure, health_parts)
                by = pd.Series(driver(rows[on], cols, sign), index=rows.index[on])
                shares = rows["weight"][on].groupby(by).sum() / max(totals["people_on_cliff"], 1e-12)
                c[measure] = dict(
                    **totals,
                    interval_95=f["interval_95"],
                    share_of_workers=totals["workers_on_cliff"] / workers,
                    share_of_adults_reached=totals["people_on_cliff"] / c["adults_reached"]["adults"],
                    sample_people_on_cliff=f["sample_people_on_cliff"],
                    source_households=f["source_households"],
                    source_households_for_half=f["source_households_for_half"],
                    by_part_moving_most={k: float(v) for k, v in shares.sort_values(ascending=False).items()},
                )
                check(f"{year} {key} {measure} rows vs parts", f["adults"], totals["people_on_cliff"])
            c["poverty_line_400"] = {
                name: found[(key, name, None)]
                for name in ("crossed_400", "crossed_400_whole_credit", "crossed_400_on_cliff_with_health",
                             "credit_moves_most_with_health", "crossed_400_credit_moves_most")
            }
            year_out["changes"][key] = c
        year_out["either_side"] = {
            f"{up}|{down}": {measure: found[(up, f"either_side_{measure}", down)] for measure in MEASURES}
            for up, down in pairs
        }
        out["years"][str(year)] = year_out
        print(f"{year}: done, {len(rows):,} rows, {n:,} source households", flush=True)

    OUT.write_text(json.dumps(out, indent=1) + "\n")
    MARKDOWN.write_text(render(out))
    print(MARKDOWN.read_text())
    return 0


def millions(x: float) -> str:
    return f"{x / 1e6:.2f}M"


def thousands(x: float) -> str:
    return f"{x / 1e3:,.0f}k"


def render(out: dict) -> str:
    lines = [
        "# Cliffs under other changes in earnings",
        "",
        "Written by scripts/earnings_changes_summary.py from the parts that scripts/earnings_changes.py",
        f"writes; commit {out['commit'][:7]}. Each row repeats the cliff test with another change in the",
        "earnings of each household's two highest-income adults. Under a raise we count the adults whose",
        "household's net income falls; under a cut, the adults whose household's net income rises. A raise",
        "in dollars reaches every measured adult; a cut in dollars, only adults whose earnings reach it; a",
        "change in proportion to earnings, only adults with earnings. \"Counting health coverage\" counts",
        "the premium tax credit once. Intervals: 95%, from resampling source households, sampling error only.",
        "The +$1,000 rows reproduce the final runs.",
        "",
    ]
    for year, y in out["years"].items():
        rules = "2017 federal rules" if year == "2017" else "2025 rules"
        lines += [f"## {rules}", "",
                  "| Change | Adults reached | Before health coverage | 95% interval | Share of workers | Counting health coverage | 95% interval | Share of workers |",
                  "|---|---:|---:|---|---:|---:|---|---:|"]
        for c in y["changes"].values():
            a, b = c["without_health"], c["with_health"]
            lines.append(
                f"| {c['label']} | {millions(c['adults_reached']['adults'])} | {millions(a['people_on_cliff'])} | "
                f"{millions(a['interval_95'][0])} to {millions(a['interval_95'][1])} | {a['share_of_workers']:.2%} | "
                f"{millions(b['people_on_cliff'])} | {millions(b['interval_95'][0])} to {millions(b['interval_95'][1])} | "
                f"{b['share_of_workers']:.2%} |"
            )
        lines += ["", "Households and their members:", "",
                  "| Change | Before: households | Before: members | Counting health: households | Counting health: members |",
                  "|---|---:|---:|---:|---:|"]
        for c in y["changes"].values():
            a, b = c["without_health"], c["with_health"]
            lines.append(
                f"| {c['label']} | {millions(a['households_with_person_on_cliff'])} | {millions(a['people_in_those_households'])} | "
                f"{millions(b['households_with_person_on_cliff'])} | {millions(b['people_in_those_households'])} |"
            )
        lines += ["", "Either side, for each raise and the cut of the same size (adults whose household loses from",
                  "the raise or gains from the cut):", "",
                  "| Sizes | Before health coverage | 95% interval | Counting health coverage | 95% interval |",
                  "|---|---:|---|---:|---|"]
        for pair, e in y["either_side"].items():
            up, down = pair.split("|")
            a, b = e["without_health"], e["with_health"]
            lines.append(
                f"| {y['changes'][up]['label']} / {y['changes'][down]['label']} | {millions(a['adults'])} | "
                f"{millions(a['interval_95'][0])} to {millions(a['interval_95'][1])} | {millions(b['adults'])} | "
                f"{millions(b['interval_95'][0])} to {millions(b['interval_95'][1])} |"
            )
        lines += ["", "400% of the poverty line (adults whose tax unit crosses it with the change):", "",
                  "| Change | Cross 400% | Lose (raise) or gain (cut) the whole credit | Of those crossing, cliff counting health | 95% interval | Credit moves most, all adults on a cliff | 95% interval |",
                  "|---|---:|---:|---:|---|---:|---|"]
        for c in y["changes"].values():
            p = c["poverty_line_400"]
            x, w, on, most = (p["crossed_400"], p["crossed_400_whole_credit"],
                              p["crossed_400_on_cliff_with_health"], p["credit_moves_most_with_health"])
            lines.append(
                f"| {c['label']} | {thousands(x['adults'])} ({x['sample_people_on_cliff']}) | {thousands(w['adults'])} ({w['sample_people_on_cliff']}) | "
                f"{thousands(on['adults'])} ({on['sample_people_on_cliff']}) | {thousands(on['interval_95'][0])} to {thousands(on['interval_95'][1])} | "
                f"{thousands(most['adults'])} ({most['sample_people_on_cliff']}) | {thousands(most['interval_95'][0])} to {thousands(most['interval_95'][1])} |"
            )
        lines += ["", "Sample adults in parentheses.", "", "The part that moves net income most against the change, counting health coverage (share of the count):", "",
                  "| Change | First | Second | Third |", "|---|---|---|---|"]
        for c in y["changes"].values():
            top = list(c["with_health"]["by_part_moving_most"].items())[:3]
            cells = [f"{name} {share:.0%}" for name, share in top] + [""] * (3 - len(top))
            lines.append(f"| {c['label']} | " + " | ".join(cells) + " |")
        lines.append("")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
