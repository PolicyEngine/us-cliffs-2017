# Tax-benefit cliffs under 2017 rules

How many Americans would see their household's net income fall if they earned $1,000 more? This repository estimates that count under 2017 tax and benefit rules and, for comparison, under 2025 rules, with and without health coverage counted as income. It uses [PolicyEngine-US](https://github.com/PolicyEngine/policyengine-us) and Microcosm, PolicyEngine's US microdata.

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
| cliffs2017/combine.py | Adds the household groups into one result per configuration |
| scripts/run_final.sh, scripts/combine_final.sh | The final runs and their combination |
| scripts/render_results.py | Writes results/summary.md from the combined results |
| scripts/audit_*.py | The parameter and formula audits behind the coverage notes in METHODOLOGY.md |
| tests/ | Property and example tests (pytest) |

## Running it

```bash
uv venv --python 3.13 && uv pip install -e ".[test]"
pytest
scripts/run_final.sh 4 0 0,1 && scripts/run_final.sh 4 0 2,3
scripts/combine_final.sh 4 0
```

Each part needs about 9 GB of memory. Per-person outputs go to results/per_person/, which git ignores.

## License

MIT
