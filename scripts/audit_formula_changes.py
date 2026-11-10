"""List variables whose formula in force in a target year differs from a later one.

For each variable with a formula dated after the target year, print the
formula that applies in the target year and flag it when its body only
returns a constant (the model's placeholder for "not modeled yet").
"""
import sys, inspect, textwrap, re
import pandas as pd
from policyengine_us import CountryTaxBenefitSystem
target = int(sys.argv[1]) if len(sys.argv) > 1 else 2017
system = CountryTaxBenefitSystem()
rows = []
for name, var in system.variables.items():
    keys = sorted(str(k) for k in var.formulas.keys())
    later = [k for k in keys if k > f"{target}-12-31"]
    if not later or len(keys) < 2:
        continue
    in_force = [k for k in keys if k <= f"{target}-12-31"]
    if not in_force:
        continue
    f = var.formulas[in_force[-1]]
    try:
        src = textwrap.dedent(inspect.getsource(f))
    except Exception:
        src = ""
    body = [l.strip() for l in src.splitlines()[1:] if l.strip() and not l.strip().startswith("#")]
    constant = len(body) == 1 and re.fullmatch(r"return (0|0\.0|False|None|np\.zeros.*|\w+\.empty_array\(\))", body[0]) is not None
    rows.append(dict(variable=name, formula_in_force=in_force[-1], next_formula=later[0],
                     placeholder=constant, unit=getattr(var, "unit", None), label=var.label))
df = pd.DataFrame(rows).sort_values(["placeholder", "variable"], ascending=[False, True])
df.to_csv(sys.stdout, index=False)
print(f"# {len(df)} variables change formula after {target}; {int(df.placeholder.sum())} use a constant placeholder in {target}", file=sys.stderr)
