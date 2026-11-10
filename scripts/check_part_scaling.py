"""Check that one part's run matches the subsample run over the same households.

Part 0 of a P-part split (cliffs2017.deflate.partition) holds the households
that ``subsample(dataset, 1 / P, seed)`` keeps, at their full weight rather
than P times it. If no household's result depends on the other households in
the run or on its own weight, the subsample run's weighted counts are P times
the part's and its sample counts equal the part's. Exits 1 on a mismatch.

usage: python scripts/check_part_scaling.py <parts> <part 0 result> <subsample result>
"""

import json
import sys

WEIGHTED = [
    "people_on_cliff",
    "workers_on_cliff",
    "households_with_person_on_cliff",
    "people_in_those_households",
    "people_total",
    "workers",
]
SAMPLE = ["sample_people_on_cliff", "sample_households"]
TOLERANCE = 1e-5


def main():
    parts, part_path, subsample_path = int(sys.argv[1]), sys.argv[2], sys.argv[3]
    part, sub = (json.load(open(p)) for p in (part_path, subsample_path))
    if part["part"] != 0 or part["parts"] != parts or sub["fraction"] != 1 / parts:
        sys.exit(f"need part 0 of {parts} and the {1 / parts:g} subsample")
    for key in ("year", "health_benefits_in_net_income", "aca_before_2018", "seed", "versions", "dataset"):
        if part[key] != sub[key]:
            sys.exit(f"the runs differ on {key}: {part[key]} vs {sub[key]}")
    # Settings that older runs don't record must match where both record them.
    for key in ("bootstrap_clusters",):
        if key in part and key in sub and part[key] != sub[key]:
            sys.exit(f"the runs differ on {key}: {part[key]} vs {sub[key]}")
    if "code" in part and "code" in sub:
        if part["code"]["cliffs2017_sha256"] != sub["code"]["cliffs2017_sha256"]:
            sys.exit("the runs used different code (cliffs2017_sha256)")
    # Runs made before --leave-out-csfp existed don't record it; they ran without it.
    if part.get("leave_out_csfp", False) != sub.get("leave_out_csfp", False):
        sys.exit("the runs differ on leave_out_csfp")
    failed = False
    for key in WEIGHTED + SAMPLE:
        scaled = part[key] * (parts if key in WEIGHTED else 1)
        gap = abs(scaled - sub[key]) / max(abs(sub[key]), 1)
        failed |= gap > TOLERANCE
        print(f"{key:34s} part x{parts if key in WEIGHTED else 1} {scaled:18,.1f}  subsample {sub[key]:18,.1f}  gap {gap:.1e}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
