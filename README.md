# Tax-benefit cliffs under 2017 federal rules

How many American adults would see their household's net income fall if they earned $1,000 more? We estimate that count under 2017 federal tax and benefit rules and, for comparison, under 2025 rules, with and without counting health coverage as income. Where PolicyEngine-US holds no 2017 value for a rule, as for state Medicaid limits and most state taxes, the 2017 runs read its earliest later value; METHODOLOGY.md lists them. We use [PolicyEngine-US](https://github.com/PolicyEngine/policyengine-us) and Microcosm, PolicyEngine's US microdata.

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
| cliffs2017/changes.py | The cliff test with other changes in earnings: raises and cuts, in dollars or in proportion to earnings |
| cliffs2017/medicaid.py | Medicaid's full-sample state totals, which the health runs hold fixed so each household's Medicaid value doesn't depend on the other households in a run |
| cliffs2017/benefits.py | Leaves the Commodity Supplemental Food Program out of household benefits, so 2025 runs count the benefits 2017 runs do |
| cliffs2017/wic_take_up.py | Sets WIC take-up from the draw Microcosm stores, as policyengine.py does |
| cliffs2017/combine.py | Adds the household groups into one result per configuration |
| scripts/medicaid_totals.sh | The Medicaid totals, from per-state sums over each household group |
| scripts/run_final.sh, scripts/combine_final.sh | The final runs and their combination; `CSFP=keep scripts/run_final.sh` runs 2025 on the model's own benefit list, for the sensitivity in results/csfp/ |
| scripts/csfp_reach.py | How many people the model gives a Commodity Supplemental Food Program package, against the funding and participation its parameters cite |
| scripts/check_part_scaling.py, scripts/run_batch.sh | Checks one group's run against the subsample run over the same households, which run_batch.sh makes (`CSFP=keep` for the runs in results/csfp/) |
| scripts/counted_once.py, scripts/run_counted_once.sh | Recounts the health runs with the premium tax credit counted once, at each Medicaid valuation, and counts the adults who lose the credit when the raise lifts their tax unit past 400% of the poverty line (results/counted_once/) |
| scripts/take_up_bounds.py | Counts the cliffs that would disappear without the change in benefits the model gives to everyone eligible: school meals, state benefits such as child care subsidies, CHIP, Medicare Savings Programs and state health programs (results/take_up_bounds.json) |
| scripts/driver_intervals.py | Gives each count by largest loss, and its share of the total, a 95% interval from resampling survey households, and counts the survey households that carry it (results/driver_intervals.json) |
| scripts/health_only.py | Compares the counts with and without health coverage adult by adult: which adults appear in both, which in only one, and what moves for the adults only in the count with health coverage (results/health_only.json) |
| scripts/earnings_changes.py, scripts/run_earnings_changes.sh | Rebuild each part of the final runs with health coverage and repeat the test for each change in earnings, writing each change as it finishes (results/earnings_changes/parts/) |
| scripts/earnings_changes_summary.py | Adds the parts for each change, with 95% intervals; counts the adults whose tax unit crosses 400% of the poverty line and the adults on either side of each raise and cut; and checks the $1,000 raise against the final runs (results/earnings_changes.json and .md) |
| scripts/runner.zsh | Runs each job directly, or through a queue you name |
| results/medicaid/ | The Medicaid sums and totals the health runs read |
| results/csfp/ | The 2025 runs that count the Commodity Supplemental Food Program, and its reach |
| scripts/render_results.py | Writes results/summary.md from the combined results |
| scripts/audit_*.py, scripts/summarize_parameters.py | The parameter and formula audits behind the coverage notes in METHODOLOGY.md, and the counts it quotes from the parameter audit |
| tests/ | Property and example tests (pytest) |

## Running it

```bash
uv venv --python 3.13 && uv pip install -e ".[test]" && source .venv/bin/activate
scripts/medicaid_totals.sh 4 0
pytest
scripts/run_final.sh 4 0 0,1 && scripts/run_final.sh 4 0 2,3
CSFP=keep scripts/run_final.sh 4 0 0,1,2,3 2025-plain,2025-health
python scripts/csfp_reach.py --year 2025 --fraction 0.25 --out results/csfp/reach_2025.json
scripts/run_batch.sh 0.25 0 && CSFP=keep scripts/run_batch.sh 0.25 0
scripts/combine_final.sh 4 0
scripts/run_counted_once.sh 4 0 0,1 && scripts/run_counted_once.sh 4 0 2,3
python scripts/take_up_bounds.py
python scripts/driver_intervals.py
python scripts/health_only.py
scripts/run_earnings_changes.sh 2017,2025 0,1 && scripts/run_earnings_changes.sh 2017,2025 2,3
python scripts/earnings_changes_summary.py
python scripts/render_results.py results/final_*.json --csfp results/csfp/final_*.json > results/summary.md
```

Each part needs about 11 GB of memory. To queue the runs under a memory limit, set `CLIFFS_RUNNER` (or write its value to a `.runner` file) to a command that takes a label and then the command to run. The tests read the Medicaid totals in results/medicaid/, so run scripts/medicaid_totals.sh before pytest in a fresh clone that lacks them. Per-person outputs go to the per_person/ folders under results/, which git ignores.

Each result file records the repository commit and a hash of the cliffs2017/ code that produced it. The final results in this repository came from commit cd77a87, whose cliffs2017/ code hashes to 04f6b6c3. The files in results/counted_once/ came from commit cd77a87; each part stops unless it reproduces the counts of the committed run it rebuilds. results/take_up_bounds.json came from commit 5a53e32; the script reads the per-person files of the final runs, which those runs write and git ignores, and stops unless the files reproduce each run's count. results/driver_intervals.json came from commit 79a52f4; scripts/driver_intervals.py reads the same files and stops unless they reproduce each run's counts, in total and by largest loss. results/health_only.json came from commit 13e1553; scripts/health_only.py reads the same files and stops unless they reproduce each headline count. results/csfp/reach_2025.json holds the number of people the model gives a Commodity Supplemental Food Program package. It came from commit efa0b34, before the runs set WIC take-up, and no formula behind that program reads WIC. The Medicaid totals in results/medicaid/ also predate cliffs2017/wic_take_up.py, and tests/test_wic_take_up.py checks on a sample that setting WIC take-up from the draw leaves Medicaid's sums unchanged. We last regenerated the parameter and formula audit files before cliffs2017/wic_take_up.py existed (commits 3286bdd and 6915a57).

## License

MIT
