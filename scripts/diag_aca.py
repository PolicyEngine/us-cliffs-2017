import sys, numpy as np
from huggingface_hub import hf_hub_download
from policyengine_us import CountryTaxBenefitSystem, Microsimulation
from policyengine_us.data.dataset_schema import USSingleYearDataset
sys.path.insert(0, '.')
from cliffs2017.deflate import deflate, subsample
p=hf_hub_download("policyengine/populace-us","populace_us_2024.h5",repo_type="dataset",revision="populace-us-2024-spm-20260909")
system=CountryTaxBenefitSystem()
base=subsample(USSingleYearDataset(p), 0.05, 1)
VARS=["aca_ptc","is_aca_ptc_eligible","aca_ptc_income_eligible" ,"takes_up_aca_if_eligible","slcsp","aca_magi_fraction","is_medicaid_eligible","housing_assistance","household_head_start_benefits","head_start","household_state_benefits","child_care_subsidies","is_on_cliff","marginal_tax_rate"]
for year in (2017, 2024):
    ds = deflate(base, system, year)[0] if year < 2024 else base
    sim = Microsimulation(dataset=ds, dataset_end_year=max(year,2024))
    print(f"===== {year}")
    for v in VARS:
        try:
            x = sim.calculate(v, year)
            vals = np.asarray(x.values, dtype=float)
            w = np.asarray(x.weights)
            print(f"  {v:32s} sum={float((vals*w).sum())/1e9:10.3f}B  nonzero_w={float(w[vals!=0].sum())/1e6:8.2f}M  mean_nz={float(vals[vals!=0].mean()) if (vals!=0).any() else 0:10.2f}")
        except Exception as e:
            print(f"  {v:32s} ERR {type(e).__name__}: {str(e)[:120]}")
