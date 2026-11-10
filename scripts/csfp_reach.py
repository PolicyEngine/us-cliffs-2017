"""How many people PolicyEngine-US gives a Commodity Supplemental Food Program package, and its cost.

usage: python scripts/csfp_reach.py --year 2025 --fraction 0.25 --out results/csfp/reach_2025.json

The model's gov.usda.csfp.amount cites the program's funding and participation
for each year; this compares them with the model's own recipients and spending
on a reweighted household subsample (cliffs2017.deflate.subsample). The
result records the repository commit and a hash of cliffs2017/, as the runs do.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
from policyengine_us import CountryTaxBenefitSystem

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cliffs2017.run import FILENAME, REPO, REVISION, code_version, load_dataset
from cliffs2017.simulation import build_simulation


def cited(system, year):
    """Funding and participation from the comment on the amount's value for ``year``."""
    import policyengine_us

    path = Path(policyengine_us.__file__).parent / "parameters/gov/usda/csfp/amount.yaml"
    for line in path.read_text().splitlines():
        match = re.match(rf"\s*{year}-01-01: \d+ # cost / participation => ([\d,]+) / ([\d,]+)", line)
        if match:
            return {k: float(v.replace(",", "")) for k, v in zip(("funding", "participation"), match.groups())}
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--fraction", type=float, default=0.25)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    system = CountryTaxBenefitSystem()
    dataset, _ = load_dataset(args.year, args.fraction, args.seed, system)
    sim = build_simulation(dataset, args.year)
    year = args.year

    def arr(variable):
        return np.asarray(sim.calculate(variable, year).values)

    weight = arr("person_weight").astype(float)
    value = arr("commodity_supplemental_food_program").astype(float)
    result = dict(
        year=year,
        fraction=args.fraction,
        seed=args.seed,
        dataset=f"{REPO}/{FILENAME}@{REVISION}",
        package_value=float(system.parameters(f"{year}-01-01").gov.usda.csfp.amount),
        model_recipients=float(weight[value > 0].sum()),
        model_spending=float((weight * value).sum()),
        sample_recipients=int((value > 0).sum()),
        cited=cited(system, year),
        code=code_version(),
    )
    Path(args.out).write_text(json.dumps(result, indent=1))
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
