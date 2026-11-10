"""List each Microcosm 2024 input column and the factor that takes it back to 2017.

For every column in the dataset that names a PolicyEngine-US variable with an
``uprating`` index, the factor is index(target year) / index(2024), computed
the way policyengine-core uprates inputs (``_uprating_index_value``). It also
reports the first date the index has a value in the raw parameter files: the
model backdates every parameter to 2015 by copying its earliest value, so an
index that starts after the target year gives a factor that stops at that
start date instead of reaching the target year.

Usage: python scripts/probe_uprating.py [target_year] > results/uprating_2017.csv
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from huggingface_hub import hf_hub_download
from policyengine_core.parameters import ParameterNode, get_parameter
from policyengine_core.simulations.simulation import _uprating_index_value

import policyengine_us
from policyengine_us import CountryTaxBenefitSystem
from policyengine_us.data.dataset_schema import USSingleYearDataset

REPO = "policyengine/populace-us"
FILENAME = "populace_us_2024.h5"
REVISION = "populace-us-2024-spm-20260909"  # the build PE-US 2.116.0 pins


def raw_first_date(raw_root, name):
    try:
        param = get_parameter(raw_root, name)
    except Exception:
        return None
    values = getattr(param, "values_list", None)
    if not values:
        return None
    return values[-1].instant_str


def main():
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 2017
    path = hf_hub_download(REPO, FILENAME, repo_type="dataset", revision=REVISION)
    dataset = USSingleYearDataset(path)
    base = int(dataset.time_period)
    system = CountryTaxBenefitSystem()
    raw_root = ParameterNode(
        directory_path=Path(policyengine_us.__file__).parent / "parameters"
    )
    rows = []
    for table, frame in zip(dataset.table_names, dataset.tables):
        for column in frame.columns:
            variable = system.variables.get(column)
            row = dict(entity=table, column=column)
            if variable is None:
                row.update(kind="not a variable")
                rows.append(row)
                continue
            values = frame[column].to_numpy()
            numeric = np.issubdtype(values.dtype, np.number) and values.dtype != bool
            row.update(
                kind="variable",
                value_type=getattr(variable.value_type, "__name__", str(variable.value_type)),
                unit=getattr(variable, "unit", None),
                has_formula=bool(variable.formulas),
                uprating=variable.uprating,
                nonzero_share=float(np.mean(values != 0)) if numeric else None,
            )
            if variable.uprating:
                index = get_parameter(system.parameters, variable.uprating)
                at_base = _uprating_index_value(index, f"{base}-01-01")
                at_target = _uprating_index_value(index, f"{target}-01-01")
                row.update(
                    index_base=at_base,
                    index_target=at_target,
                    factor=(at_target / at_base) if at_base else None,
                    index_raw_first=raw_first_date(raw_root, variable.uprating),
                )
            rows.append(row)
    out = pd.DataFrame(rows)
    out.to_csv(sys.stdout, index=False)
    print(f"# dataset {REPO}@{REVISION} time_period={base} target={target}", file=sys.stderr)
    print(out.groupby("kind").size().to_string(), file=sys.stderr)


if __name__ == "__main__":
    main()
