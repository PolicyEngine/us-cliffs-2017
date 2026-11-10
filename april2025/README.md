# Reproducing the April 2025 cliff counts

These scripts rerun PolicyEngine's April 2025 national cliff estimate with that month's model and data, and test why it exceeds the current model's. [../CORRECTION.md](../CORRECTION.md) explains the results.

| Script | What it does | Output |
|---|---|---|
| repro.py | Recomputes the 2025 counts: people on a cliff (`is_on_cliff`), their households, everyone in those households | repro_summary.json |
| attribute.py | Replicates the model's cliff test line for line and runs it three ways: as published, with a $0 raise, and with the three random draws held at their first values. Breaks each change in net income into programs | attribute_summary.json |
| workers.py | Recomputes the share of workers on a cliff against several bases | workers_summary.json |

The per-person files the scripts also write (`*.csv`, `*.csv.gz`) stay out of git; rerun the scripts to rebuild them.

## Environment

- PolicyEngine-US 1.251.1: commit c379969db9 of [PolicyEngine/policyengine-us](https://github.com/PolicyEngine/policyengine-us), the main branch on 16 April 2025.
- policyengine-core 3.16.6, numpy 1.26.4, pandas 2.2.3, microdf-python 1.5.12, h5py 3.16.0, Python 3.12.
- Data: `enhanced_cps_2024.h5` from [policyengine/policyengine-us-data](https://huggingface.co/policyengine/policyengine-us-data) at revision da98b4faccf44492e91d80c0112a34ef6c3da0bd, uploaded 1 April 2025, the last upload before the April estimate.
- stub/policyengine_us_data stands in for the policyengine-us-data package of that time, whose releases PyPI no longer serves. PolicyEngine-US 1.251.1 imports three names from it: two that only set a default dataset, and the ZIP code table that its ZIP code and county formulas sample from (the file at policyengine-us-data commit 95ca7930).

```bash
cd april2025
git clone https://github.com/PolicyEngine/policyengine-us src && git -C src checkout c379969db9e7e6461bb68b65b2bfde5d6370e6e1
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python "policyengine-core==3.16.6" "microdf-python==1.5.12" tqdm "huggingface-hub==2.4.0"
uv pip install --python .venv/bin/python --no-deps ./src
uv pip install --python .venv/bin/python "numpy==1.26.4" "pandas==2.2.3" "h5py==3.16.0"
PYTHONPATH=stub .venv/bin/python repro.py
PYTHONPATH=stub .venv/bin/python attribute.py
PYTHONPATH=stub .venv/bin/python workers.py   # reads attribute.py's per-person files
```

Each script loads the full enhanced CPS; repro.py took 12 minutes and attribute.py 7 minutes on an Apple M5 Max.
