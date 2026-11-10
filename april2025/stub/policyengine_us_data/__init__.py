"""Stand-in for policyengine-us-data as of April 2025 (its releases are gone from PyPI).

PolicyEngine-US 1.251.1 imports three names from this package:
- DATASETS and CPS_2024, only to set a default dataset (every run here passes
  an explicit enhanced CPS file instead);
- ZIP_CODE_DATASET, the ZIP code population table its zip_code and county
  formulas sample from. zip_codes.csv.gz is the file at policyengine-us-data
  commit 95ca7930 (16 April 2025); it last changed on 18 September 2024.
"""
from pathlib import Path

import pandas as pd

DATASETS = []
CPS_2024 = None
ZIP_CODE_DATASET = pd.read_csv(Path(__file__).parent / "zip_codes.csv.gz", compression="gzip")
