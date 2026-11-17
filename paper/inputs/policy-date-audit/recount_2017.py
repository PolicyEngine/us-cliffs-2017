"""Recount the archived 2017 parameter audit using only the standard library."""

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def recount(source):
    with source.open() as handle:
        rows = list(csv.DictReader(handle))
    raw = [row for row in rows if row["status"] in {"covered", "later start"}]

    def counts(predicate):
        selected = [row for row in raw if predicate(row["parameter"])]
        return {
            "later": sum(row["status"] == "later start" for row in selected),
            "all": len(selected),
        }

    def state(name):
        return name.startswith("gov.states.")

    def local(name):
        return name.startswith("gov.local.")

    def federal(name):
        return name.startswith("gov.") and not state(name) and not local(name)

    def state_tax(name):
        return bool(re.match(r"gov\.states\.[a-z]{2}\.tax\.", name))

    return {
        "source_csv_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "raw_parameters": len(raw),
        "later": sum(row["status"] == "later start" for row in raw),
        "state": counts(state),
        "local": counts(local),
        "federal": counts(federal),
        "state_tax": counts(state_tax),
        "state_tax_later_first2021": sum(
            state_tax(row["parameter"])
            and row["status"] == "later start"
            and row["earliest_start"].startswith("2021")
            for row in raw
        ),
        "state_childcare": counts(
            lambda name: state(name)
            and bool(re.search(r"ccap|ccdf|ccsp|child_care|childcare", name))
        ),
        "later_fixed_reads": sum(bool(row["later_reads"]) for row in rows),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=ROOT / "results/parameters_read_2017.csv"
    )
    parser.add_argument("--check", action="store_true", help="Check archived receipt")
    args = parser.parse_args()
    result = recount(args.source)
    if args.check:
        expected = json.loads(
            (Path(__file__).parent / "summary.json").read_text()
        )["recount_2017"]["counts"]
        assert result == expected, "Recount differs from archived receipt"
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
