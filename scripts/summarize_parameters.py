"""Print the counts METHODOLOGY.md quotes from the parameter audit.

Reads the CSV that scripts/audit_parameters.py writes and counts the
parameters from the model's files (status "later start" or "covered"):
state parameters are those under gov.states, local ones under gov.local,
federal ones the rest of gov; state tax parameters sit under
gov.states.<state>.tax and state child care subsidy parameters have
"ccap", "ccdf", "ccsp", "child_care" or "childcare" in their names. A
parameter "starts in" the year its earliest value takes effect. It also
lists the parameters a formula reads at an instant after the target year.

Usage: python scripts/summarize_parameters.py results/parameters_read_2017.csv 2017
"""

import sys

import pandas as pd

CHILD_CARE = r"ccap|ccdf|ccsp|child_care|childcare"


def counts(frame: pd.DataFrame, target: int) -> dict:
    files = frame[frame.status.isin(["later start", "covered"])]
    name = files.parameter
    later = files.status == "later start"
    start_year = files.earliest_start.astype(str).str[:4]
    state = name.str.startswith("gov.states.")
    local = name.str.startswith("gov.local.")
    federal = name.str.startswith("gov.") & ~state & ~local
    state_tax = name.str.match(r"gov\.states\.[a-z]{2}\.tax\.")
    child_care = state & name.str.contains(CHILD_CARE)

    def share(mask):
        return int((mask & later).sum()), int(mask.sum())

    return {
        "parameters from the model's files": len(files),
        f"with a value starting after 1 January {target}": int(later.sum()),
        "state (later, all)": share(state),
        "local (later, all)": share(local),
        "federal (later, all)": share(federal),
        f"federal, later, starting in {target + 1}": int((federal & later & (start_year == str(target + 1))).sum()),
        "state tax (later, all)": share(state_tax),
        "state tax, later, starting in 2021": int((state_tax & later & (start_year == "2021")).sum()),
        "state child care subsidy (later, all)": share(child_care),
        "neither state, local nor federal": int((~(state | local | federal)).sum()),
    }


def main():
    path, target = sys.argv[1], int(sys.argv[2])
    frame = pd.read_csv(path, comment="#", dtype={"later_reads": str})
    for key, value in counts(frame, target).items():
        print(f"{key}: {value}")
    read_later = frame[frame.later_reads.notna() & (frame.later_reads != "")]
    print(f"\nread at an instant after {target}: {len(read_later)}")
    for row in read_later.itertuples():
        print(f"  {row.parameter}: {row.later_reads}")


if __name__ == "__main__":
    main()
