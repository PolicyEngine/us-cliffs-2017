# Historical job-entry experiment: feasibility pilot

This analysis preserves the frozen 2017 experiment. It applies 2017 federal
rules, the model's 2018 Medicaid/CHIP limits and mostly later state rules to
2024 microdata scaled to 2017 population, income and price levels.

## Reproduction

```sh
uv venv --python 3.13 .venv
uv pip sync --python .venv/bin/python requirements-expanded.txt
uv run --no-sync pytest tests/test_expanded_job_entry.py -q
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 uv run --no-sync python scripts/expanded_job_entry.py --households-per-state 3 --out results/expanded_job_entry_pilot.json
```

The attempted base wrapper was `policyengine==6.17.2`, verified from live PyPI on
11 November 2026. Its bundle pins a different country model and refuses
the historical engine at import with `ValueError: Data release manifest is not
certified for the runtime model version 2.116.0 in country 'us'.` The
`allow_unmanaged` constructor is never reached. This pilot does not bypass that
certificate or claim current-bundle certification. The incompatible wrapper is
absent from the final environment. The complete original historical dependency
graph is pinned in `requirements-expanded.txt`, including
`policyengine-us==2.116.0`, `policyengine-core==3.34.10`,
`microdf-python==1.5.12` and `spm-calculator==1.1.0`. The pilot uses the
previously validated historical loader and records the exception in its result.

## Defined scenario

- Consider adults aged 18–64 with zero wages, zero non-SSTB self-employment income
  and zero SSTB self-employment income. Exclude full-time students and people with
  reported disability in the main pilot. The data do not establish availability
  for a particular job, and early retirement is not directly observed. The
  disability restriction is a declared choice, not an inference that everyone
  reporting disability cannot work.
- Offer each eligible adult a wage job for 40 hours a week and 52 weeks a year.
  Change one eligible adult per household at a time, continuing through every
  candidate rank rather than stopping after two adults.
- Set the entrant's reported unemployment compensation and weeks unemployed to
  zero; set work hours/weeks, hourly wage, hourly-pay status, self-employment
  status and never-worked status consistently with the new job.
- Preserve other household income, benefit take-up inputs, pre-existing employer
  coverage and childcare costs. Assume no additional employer health coverage.
  Additional childcare expenses and an SSDI earnings-cutoff calculation do not
  enter this pilot.
- Count health coverage at government cost using the existing fixed Medicaid
  state totals and the same WIC take-up mapping. Add back the marketplace net
  premium to health-inclusive household net income so the assigned premium tax
  credit contributes once, matching the inherited `d_net_single_ptc` measure.
- Classify a person when the household's resource change is strictly below 60%,
  50%, 20% or 0% of the entrant's gross pay. Group membership uses the same
  scenario at each threshold. Count household unions through an analysis flag
  mapped by `calc(..., map_to="household")`/`map_to="person"`; calibrated
  household weights remain inside MicroSeries. No weight arrays are aggregated.

## Wage evidence and bounds

The pilot covers three states whose 2017 rates match the DOL historical basic-rate
column and separate state primary sources:

| State | Hourly wage | Full-year gross pay | State primary source |
|---|---:|---:|---|
| Colorado | $9.30 | $19,344 | [Legislative Council fiscal note, table 1, p. 2](https://leg.colorado.gov/sites/default/files/documents/2019A/bills/fn/2019a_hb1210_00.pdf) |
| North Carolina | $7.25 | $15,080 | [NCDOL Wage and Hour Notice, p. 5](https://www.labor.nc.gov/communications/labor-ledger/2021-november-december-edition/open) states the rate took effect 24 July 2009 |
| Washington | $11.00 | $22,880 | [L&I minimum-wage history](https://www.lni.wa.gov/workers-rights/wages/minimum-wage/history-of-washington-states-minimum-wage), 1 January 2017 |

DOL source: [Changes in basic minimum wages, 2014–2019 table, 2017 column](https://www.dol.gov/agencies/whd/state/minimum-wage/history).
The migrated beta copy currently contains inconsistent cells for other
jurisdictions, including a District of Columbia value of $17 in its 2017 column.
The pilot does not ingest that table automatically. National work requires a
complete rate-by-state audit and explicit choices for within-year changes,
employer-size tiers and local rates. No missing rate receives a guessed default.

## Validation

The pilot selects three candidate-containing households in each state, with a
fixed random seed, preserving every member and benefit unit. This selected sample
cannot support national inference. Results contain sample record counts only;
they deliberately omit projected population totals.

The executable checks:

1. A zero-change branch leaves every household's resources exactly unchanged.
2. Each job branch leaves untouched households' resources unchanged.
3. Entrant earnings equal the historical hourly rate times 2,080; work hours and
   weeks equal 40 and 52.
4. Stored WIC take-up draws match the baseline after the earnings change.
5. The first candidate-rank branch matches an independently modified input
   dataset rebuilt as a fresh simulation, within one dollar for float32 rounding.
6. Every candidate appears exactly once, and the retention-threshold sets nest.

Unit tests also cover age boundaries, earnings-loss/nonworker distinctions,
student/disability restrictions, wage mapping without losing MicroSeries
metadata, job-input consistency, scope refusal, and serialization of actual
model scalar types. The pilot records the script's SHA-256 before computation.

The completed nine-household pilot contains 33 people and tests ten candidate
adults across two ranks. The zero-change, untouched-household, gross-pay and
fresh-simulation identities all agree exactly; no WIC take-up draw changes.
The sample's strict-cliff flag covers two adults in one household with six
members. These selected-sample record counts provide a feasibility check, not
a national estimate or an estimate for any of the three states.

## Remaining work

Complete the national wage audit; review the observable availability restrictions;
compare job-entry resource components with the main raise experiment; validate
the main strict-cliff group and the additional high-loss group under the same
union; then run the approved full sample through the shared resource queue.
Uncertainty must resample source households together with their duplicate
records. A full-sample job-entry union and its overlap with the raise union are
not produced by this pilot.
