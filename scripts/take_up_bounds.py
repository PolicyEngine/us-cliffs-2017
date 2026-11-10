"""How many cliffs rest on benefits the model gives to everyone eligible.

Microcosm carries take-up for SNAP, SSI, TANF, housing assistance, Head Start,
Medicaid, Medicare, the ACA premium tax credit and the EITC. It also stores a
WIC take-up draw, which cliffs2017.wic_take_up sets as PolicyEngine-US
2.116.0's ``takes_up_wic_if_eligible``, as policyengine.py does. PolicyEngine-US
gives several other benefits to everyone eligible:

- School meals: ``free_school_meals`` and ``reduced_price_school_meals`` have
  no take-up input at all.
- State benefits: ``household_state_benefits`` holds the state child care
  subsidies, the state supplements to SSI and other state programs. The child
  care subsidies have no take-up input, except California's CalWORKs child
  care, which reads TANF take-up. Some supplements don't read SSI take-up
  (Massachusetts's starts from ``uncapped_ssi``); others pay only SSI
  recipients (Wisconsin's and Washington's need ``ssi`` > 0), so they follow
  Microcosm's SSI take-up. The group counts every state benefit, so it
  overstates the cliffs that rest on full take-up.
- CHIP: ``chip_enrolled`` adds ``takes_up_chip_if_eligible``, default True. A
  family that doesn't enroll in CHIP pays no CHIP premium, so the CHIP group
  removes the premium's change too.
- Medicare Savings Programs: ``msp_cost`` has no take-up input.
- State health programs: the California, Colorado and New Mexico premium
  programs read take-up inputs that default to True; the others have none.

For each final run, this script counts the cliffs that would disappear if a
group of these benefits didn't change with the raise: rows whose change in net
income, less the group's change, is no longer negative. A person who doesn't
take up a benefit can't lose it, and a cliff that rests on one also needs the
household to have taken it up, so realistic take-up would remove only part of
each count. Where a benefit rises with the raise, as CHIP and Medicare Savings
Programs do in some households counting health coverage, where they replace
Medicaid the household loses, a household that didn't take it up would miss
the rise, so realistic take-up could also add cliffs. The per-person files hold
only cliff rows, so they can't count those; the shares here bound only the
cliffs that would disappear.

The per-person files are git-ignored record-level output of scripts/run.py
(results/parts/per_person/); each run's rows must reproduce its committed
count, or the script stops.

usage: python scripts/take_up_bounds.py   # writes results/take_up_bounds.json
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PARTS = ROOT / "results" / "parts" / "per_person"
OUT = ROOT / "results" / "take_up_bounds.json"
RUNS = ("2017_plain", "2017_health", "2025_plain", "2025_health")
STATE_HEALTH = (
    "d_assigned_ca_premium_subsidy",
    "d_co_omnisalud",
    "d_assigned_co_premium_assistance",
    "d_ct_covered_connecticut",
    "d_ma_connector_care",
    "d_md_premium_assistance",
    "d_nj_njhps",
    "d_assigned_nm_premium_assistance",
    "d_or_healthier_oregon_cost",
    "d_vt_premium_assistance",
    "d_wa_cascade_care_savings",
)
CASH_GROUPS = {
    "school_meals": ("d_free_school_meals", "d_reduced_price_school_meals"),
    "state_benefits": ("d_household_state_benefits",),
}
HEALTH_GROUPS = {
    "chip": ("d_chip", "d_chip_premium"),
    "medicare_savings_programs": ("d_msp_cost",),
    "state_health_programs": STATE_HEALTH,
}
TOLERANCE = 1e-6  # relative gap allowed between these rows and the committed count


def groups(health: bool) -> dict[str, tuple[str, ...]]:
    """The benefit groups to test in a run, plus all of them together."""
    chosen = dict(CASH_GROUPS)
    if health:
        chosen.update(HEALTH_GROUPS)
    chosen["all_of_these"] = tuple(c for cols in chosen.values() for c in cols)
    return chosen


def bounds(rows: pd.DataFrame, change: str, chosen: dict[str, tuple[str, ...]]) -> dict:
    """Weighted cliffs, and how many disappear without each group's change.

    ``change`` names the column whose negative values mark a cliff: ``d_net``,
    or ``d_net_single_ptc`` for the counts that take the premium tax credit
    once.
    """
    on = rows[change].to_numpy() < 0
    weight = rows["weight"].to_numpy()
    total = float(weight[on].sum())
    result = {"people_on_cliff": total, "sample_people_on_cliff": int(on.sum()), "groups": {}}
    for name, cols in chosen.items():
        group_change = rows[list(cols)].sum(axis=1).to_numpy()
        without = rows[change].to_numpy() - group_change
        gone = on & (without >= 0)
        result["groups"][name] = {
            "columns": list(cols),
            "cliffs_that_disappear": float(weight[gone].sum()),
            "share": float(weight[gone].sum() / total) if total else 0.0,
            "sample_rows": int(gone.sum()),
            # Cliff rows where the group rises with the raise: without take-up,
            # these households would miss the rise.
            "rises_in_cliff_rows": float(weight[on & (group_change > 0)].sum()),
        }
    return result


def load(run: str) -> pd.DataFrame:
    files = sorted(PARTS.glob(f"run_{run}_p4_*_s0_cliff_parts.csv.gz"))
    if len(files) != 4:
        raise FileNotFoundError(f"{run}: expected 4 part files in {PARTS}, found {len(files)}")
    return pd.concat([pd.read_csv(f) for f in files], ignore_index=True)


def check(run: str, result: dict, committed: float) -> None:
    gap = abs(result["people_on_cliff"] - committed)
    if gap > TOLERANCE * max(committed, 1.0):
        raise ValueError(f"{run}: rows give {result['people_on_cliff']:,.1f} cliffs, committed run {committed:,.1f}")


def main() -> int:
    # The output records HEAD as its commit, so the script that runs must be the one HEAD holds.
    script = Path(__file__).resolve().relative_to(ROOT)
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", str(script)], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    if dirty:
        raise SystemExit(f"commit {script} first: the output records HEAD, which doesn't hold this version")
    out = {
        "note": (
            "Cliffs that disappear if a benefit group's change is removed: upper "
            "bounds on how many cliffs realistic take-up of these benefits would "
            "remove. Counting health coverage, it could also add some, which these "
            "rows can't count. WIC follows Microcosm's stored take-up draw."
        ),
        "commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
        ).stdout.strip(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "runs": {},
    }
    renames = set()
    for run in RUNS:
        health = run.endswith("health")
        rows = load(run)
        final = json.loads((ROOT / "results" / f"final_{run}.json").read_text())
        # Each final run records the stored inputs it renamed (the WIC take-up draw); the
        # bounds carry that record, and stop if the runs they read differ in it.
        renames.add(json.dumps(final.get("stored_input_renames"), sort_keys=True))
        entry = {"as_modeled": bounds(rows, "d_net", groups(health))}
        check(run, entry["as_modeled"], final["people_on_cliff"])
        if health:
            entry["credit_counted_once"] = bounds(rows, "d_net_single_ptc", groups(health))
            committed = final["premium_tax_credit_counted_once"]["people_on_cliff"]
            check(run + " counted once", entry["credit_counted_once"], committed)
        out["runs"][run] = entry
    if len(renames) != 1:
        raise ValueError(f"the final runs differ in the stored inputs they renamed: {sorted(renames)}")
    out["stored_input_renames"] = json.loads(renames.pop())
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    for run, entry in out["runs"].items():
        key = "credit_counted_once" if "credit_counted_once" in entry else "as_modeled"
        b = entry[key]
        shares = ", ".join(f"{k} {v['share']:.1%}" for k, v in b["groups"].items())
        print(f"{run} ({key}): {b['people_on_cliff']:,.0f} cliffs; {shares}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
