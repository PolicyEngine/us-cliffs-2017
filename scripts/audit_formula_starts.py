"""List variables whose first formula starts after a target year.

Before its first formula's start date a variable has no formula, so
policyengine-core returns its default (0 or False) unless an input supplies
it. For each such variable, report its 2024 weighted total on a sample, which
shows how much the target-year run leaves out.
Usage: python scripts/audit_formula_starts.py 2017 0.05 > results/formula_starts_2017.csv
"""
import sys, numpy as np, pandas as pd
sys.path.insert(0, '.')
from huggingface_hub import hf_hub_download
from policyengine_us import CountryTaxBenefitSystem, Microsimulation
from policyengine_us.data.dataset_schema import USSingleYearDataset
from cliffs2017.deflate import subsample
target = int(sys.argv[1]); fraction = float(sys.argv[2])
system = CountryTaxBenefitSystem()
rows = []
for name, var in system.variables.items():
    if not var.formulas:
        continue
    first = min(str(k) for k in var.formulas.keys())
    if first > f"{target}-12-31":
        rows.append(dict(variable=name, first_formula=first, unit=getattr(var, "unit", None),
                         value_type=getattr(var.value_type, "__name__", str(var.value_type)),
                         entity=var.entity.key, label=var.label))
df = pd.DataFrame(rows)
p = hf_hub_download("policyengine/populace-us", "populace_us_2024.h5", repo_type="dataset", revision="populace-us-2024-spm-20260909")
sim = Microsimulation(dataset=subsample(USSingleYearDataset(p), fraction, 2), dataset_end_year=2024)
totals, counts = [], []
for name in df.variable:
    try:
        x = sim.calculate(name, 2024)
        vals = np.asarray(x.values, dtype=float); w = np.asarray(x.weights)
        totals.append(float((vals * w).sum())); counts.append(float(w[vals != 0].sum()))
    except Exception as e:
        totals.append(np.nan); counts.append(np.nan)
df["total_2024"] = totals; df["weighted_nonzero_2024"] = counts
df.sort_values("total_2024", ascending=False, key=lambda s: s.abs()).to_csv(sys.stdout, index=False)
print(f"# {len(df)} variables first formula after {target}", file=sys.stderr)
