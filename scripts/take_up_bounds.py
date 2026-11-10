"""How many cliffs rest on benefits the model gives to everyone eligible.

Microcosm carries take-up for SNAP, SSI, TANF, housing assistance, Head Start,
Medicaid, Medicare, the ACA premium tax credit and the EITC. PolicyEngine-US
2.116.0 gives several other benefits to everyone eligible:

- WIC: ``wic`` is defined for ``takes_up_wic_if_eligible`` and
  ``is_wic_eligible`` needs ``is_wic_at_nutritional_risk``; both default to
  True and the data hold neither. (The data's ``would_claim_wic`` column is an
  older name that 2.116.0 never reads.)
- School meals: ``free_school_meals`` and ``reduced_price_school_meals`` have
  no take-up input at all.
- CHIP: ``chip_enrolled`` adds ``takes_up_chip_if_eligible``, default True.
- Medicare Savings Programs: ``msp_cost`` has no take-up input.
- State health programs: the California, Colorado and New Mexico premium
  programs read take-up inputs that default to True; the others have none.

For each final run, this script counts the cliffs that would disappear if a
group of these benefits didn't change with the raise: rows whose change in net
income, less the group's change, is no longer negative. That bounds how far
full take-up raises each count. A person who doesn't take up WIC can't lose it,
but a cliff that rests on WIC alone also needs the household to have taken it
up, so realistic take-up would remove only part of each count. Removing a
benefit's change could also create a cliff where that benefit rose with the
raise; the per-person files hold only cliff rows, so the counts here leave
those out, which keeps them upper bounds on the fall.

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
    "wic": ("d_wic",),
    "school_meals": ("d_free_school_meals", "d_reduced_price_school_meals"),
}
HEALTH_GROUPS = {
    "chip": ("d_chip",),
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
        without = rows[change].to_numpy() - rows[list(cols)].sum(axis=1).to_numpy()
        gone = on & (without >= 0)
        result["groups"][name] = {
            "columns": list(cols),
            "cliffs_that_disappear": float(weight[gone].sum()),
            "share": float(weight[gone].sum() / total) if total else 0.0,
            "sample_rows": int(gone.sum()),
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
    out = {
        "note": (
            "Cliffs that disappear if a benefit group's change is removed. "
            "Upper bounds on how far full take-up of these benefits raises each count."
        ),
        "commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
        ).stdout.strip(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "runs": {},
    }
    for run in RUNS:
        health = run.endswith("health")
        rows = load(run)
        final = json.loads((ROOT / "results" / f"final_{run}.json").read_text())
        entry = {"as_modeled": bounds(rows, "d_net", groups(health))}
        check(run, entry["as_modeled"], final["people_on_cliff"])
        if health:
            entry["credit_counted_once"] = bounds(rows, "d_net_single_ptc", groups(health))
            committed = final["premium_tax_credit_counted_once"]["people_on_cliff"]
            check(run + " counted once", entry["credit_counted_once"], committed)
        out["runs"][run] = entry
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    for run, entry in out["runs"].items():
        key = "credit_counted_once" if "credit_counted_once" in entry else "as_modeled"
        b = entry[key]
        shares = ", ".join(f"{k} {v['share']:.1%}" for k, v in b["groups"].items())
        print(f"{run} ({key}): {b['people_on_cliff']:,.0f} cliffs; {shares}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
