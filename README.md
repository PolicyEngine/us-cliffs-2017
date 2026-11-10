# Tax-benefit cliffs under 2017 rules

How many American adults would see their household's net income fall if they earned $1,000 more? This repository estimates that count under 2017 tax and benefit rules and, for comparison, under 2025 rules, with and without health coverage counted as income. It uses [PolicyEngine-US](https://github.com/PolicyEngine/policyengine-us) and Microcosm, PolicyEngine's US microdata.

- [results/summary.md](results/summary.md): the counts, with 95% intervals.
- [METHODOLOGY.md](METHODOLOGY.md): how we define a cliff, build the 2017 population and measure uncertainty, and what the model leaves out.
- [CORRECTION.md](CORRECTION.md): why our April 2025 estimate overstated the count, and the evidence.
- [april2025/](april2025/): the scripts that reproduce the April 2025 estimate and trace the error.

## Layout

| Path | Contents |
|---|---|
| cliffs2017/run.py | One run: a year, with or without health coverage, on the full sample, a household subsample or one of several disjoint household groups |
| cliffs2017/deflate.py | Scales the 2024 data to 2017 dollar levels and population; splits and subsamples households |
| cliffs2017/aca2017.py | The ACA premium tax credit before 2018, which PolicyEngine-US leaves at $0 |
| cliffs2017/decompose.py | Breaks each tested adult's change in net income into programs and taxes |
| cliffs2017/medicaid.py | Medicaid's full-sample state totals, which the health runs hold fixed so each household's Medicaid value doesn't depend on the other households in a run |
| cliffs2017/benefits.py | Leaves the Commodity Supplemental Food Program out of household benefits, so 2025 runs count the benefits 2017 runs do |
| cliffs2017/combine.py | Adds the household groups into one result per configuration |
| scripts/medicaid_totals.sh | The Medicaid totals, from per-state sums over each household group |
| scripts/run_final.sh, scripts/combine_final.sh | The final runs and their combination; `CSFP=keep scripts/run_final.sh` runs 2025 on the model's own benefit list, for the sensitivity in results/csfp/ |
| scripts/csfp_reach.py | How many people the model gives a Commodity Supplemental Food Program package, against the funding and participation its parameters cite |
| scripts/check_part_scaling.py, scripts/run_batch.sh | Checks one group's run against the subsample run over the same households, which run_batch.sh makes (`CSFP=keep` for the runs in results/csfp/) |
| scripts/runner.zsh | Runs each job directly, or through a queue you name |
| results/medicaid/ | The Medicaid sums and totals the health runs read |
| results/csfp/ | The 2025 runs that count the Commodity Supplemental Food Program, and its reach |
| scripts/render_results.py | Writes results/summary.md from the combined results |
| scripts/audit_*.py | The parameter and formula audits behind the coverage notes in METHODOLOGY.md |
| tests/ | Property and example tests (pytest) |

## Running it

```bash
uv venv --python 3.13 && uv pip install -e ".[test]"
scripts/medicaid_totals.sh 4 0
pytest
scripts/run_final.sh 4 0 0,1 && scripts/run_final.sh 4 0 2,3
CSFP=keep scripts/run_final.sh 4 0 0,1,2,3 2025-plain,2025-health
python scripts/csfp_reach.py --year 2025 --fraction 0.25 --out results/csfp/reach_2025.json
scripts/run_batch.sh 0.25 0 && CSFP=keep scripts/run_batch.sh 0.25 0
scripts/combine_final.sh 4 0
```

Each part needs about 11 GB of memory. To queue the runs under a memory limit, set `CLIFFS_RUNNER` (or write its value to a `.runner` file) to a command that takes a label and then the command to run. The tests read the Medicaid totals in results/medicaid/, so run scripts/medicaid_totals.sh before pytest in a fresh clone that lacks them. Per-person outputs go to results/per_person/, which git ignores.

## License

MIT
