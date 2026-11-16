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

## National wage conventions

`scripts/job_entry_wages.py` reads the audited rates in
`research/minimum-wages-2017/wages.json` (sources and corrections in
`research/minimum-wages-2017/evidence.md`) and applies five conventions:

1. **Within-year changes.** The statewide general rate is weighted by calendar
   day over 2017, which spreads the 2,080 hours evenly through the year. This
   applies to every jurisdiction that evidence.md lists as changing after
   1 January: the District of Columbia, Maine, Maryland, New York and Oregon.
   Each needs dated rates that cover every day of 2017 exactly once.
2. **Employer-size tiers.** Where a state's rate depends on employer size or
   receipts, the job pays the large-employer rate: California (26 or more
   employees), Minnesota (sales of at least $500,000), Ohio (receipts of at least
   $299,000), Montana (sales over $110,000), and Arkansas, Illinois, Michigan,
   Nebraska, Vermont and West Virginia (employers covered by state law rather
   than exempt small employers). The code selects each by the label in
   wages.json and checks that it is the highest tier.
3. **Region tiers.** Where a state's rate depends on region, the job pays the
   standard statewide rate: Oregon's standard rate, and New York's rest-of-state
   rate, below its New York City and Long Island/Westchester tiers. No work
   location is assigned.
4. **No local ordinances.** wages.json records none, and the job pays none.
5. **Federal floor.** Each dated rate is at least $7.25, the floor for this
   FLSA-covered job. Where a state has no minimum wage, or a lower one, the job
   pays $7.25.

Nevada tiers by whether the employer offers qualifying health benefits. The job
offers no new employer coverage, so it pays Nevada's higher rate, $8.25, as
wages.json records. Gross pay is the effective hourly rate times 2,080. The
table also checks that each jurisdiction's selected 1 January rate equals its
recorded `amount` and `reference_hourly`, and stops on any contradiction, gap or
overlap.

Maine's $9.00 rate took effect on 7 January 2017. The codified text of 26 MRSA
§664(1) says "starting January 1, 2017", but the initiated act that enacted it
(IB 2015, c. 2) is printed in the Laws of Maine as effective 7 January 2017, and
the Maine DOL's 15 December 2016 release gives the same date, 30 days after the
Governor certified the referendum. The time-weighted rate therefore has six days
at $7.50. The codified date would have paid $9.00, or $51.29 more a year.

Maryland and New York were unresolved in the first national run, because
wages.json lacked one dated rate for each. On 16 November 2026 wages.json gained
Maryland's $9.25 from 1 July 2017 (2014 Laws of Maryland, ch. 262, enacting Lab.
& Empl. §3-413(c)) and New York's rest-of-state $10.40 from 31 December 2017 (NY
DOL minimum-wage history). evidence.md gives each source and access date, and
`research/minimum-wages-2017/sources/` holds the relevant text. The first run
tested the other 49 jurisdictions and counted Maryland and New York candidates as
deferred; the `states:MD,NY` scope tests them (see National run).

| Jurisdiction | Hourly rate | Gross pay | Convention |
|---|---:|---:|---|
| Alabama | $7.25 | $15,080.00 | federal floor; no state rate |
| Alaska | $9.80 | $20,384.00 | statewide |
| Arizona | $10.00 | $20,800.00 | statewide |
| Arkansas | $8.50 | $17,680.00 | large-employer rate |
| California | $10.50 | $21,840.00 | large-employer rate |
| Colorado | $9.30 | $19,344.00 | statewide |
| Connecticut | $10.10 | $21,008.00 | statewide |
| Delaware | $8.25 | $17,160.00 | statewide |
| District of Columbia | $12.0041 | $24,968.55 | by day: $11.50 for 181 days, $12.50 for 184 |
| Florida | $8.10 | $16,848.00 | statewide |
| Georgia | $7.25 | $15,080.00 | federal floor; state rate $5.15 |
| Hawaii | $9.25 | $19,240.00 | statewide |
| Idaho | $7.25 | $15,080.00 | statewide |
| Illinois | $8.25 | $17,160.00 | large-employer rate |
| Indiana | $7.25 | $15,080.00 | statewide |
| Iowa | $7.25 | $15,080.00 | statewide |
| Kansas | $7.25 | $15,080.00 | statewide |
| Kentucky | $7.25 | $15,080.00 | statewide |
| Louisiana | $7.25 | $15,080.00 | federal floor; no state rate |
| Maine | $8.9753 | $18,668.71 | by day: $7.50 for 6 days, $9.00 for 359 |
| Maryland | $9.0021 | $18,724.27 | by day: $8.75 for 181 days, $9.25 for 184 |
| Massachusetts | $11.00 | $22,880.00 | statewide |
| Michigan | $8.90 | $18,512.00 | large-employer rate |
| Minnesota | $9.50 | $19,760.00 | large-employer rate |
| Mississippi | $7.25 | $15,080.00 | federal floor; no state rate |
| Missouri | $7.70 | $16,016.00 | statewide |
| Montana | $8.15 | $16,952.00 | large-employer rate |
| Nebraska | $9.00 | $18,720.00 | large-employer rate |
| Nevada | $8.25 | $17,160.00 | employer offers no health coverage |
| New Hampshire | $7.25 | $15,080.00 | statewide |
| New Jersey | $8.44 | $17,555.20 | statewide |
| New Mexico | $7.50 | $15,600.00 | statewide |
| New York | $9.7019 | $20,179.99 | rest of state, by day: $9.70 for 364 days, $10.40 for 1 |
| North Carolina | $7.25 | $15,080.00 | statewide |
| North Dakota | $7.25 | $15,080.00 | statewide |
| Ohio | $8.15 | $16,952.00 | large-employer rate |
| Oklahoma | $7.25 | $15,080.00 | federal floor; DOL lists a $2.00–7.25 state range |
| Oregon | $10.0021 | $20,804.27 | standard region, by day: $9.75 for 181 days, $10.25 for 184 |
| Pennsylvania | $7.25 | $15,080.00 | statewide |
| Rhode Island | $9.60 | $19,968.00 | statewide |
| South Carolina | $7.25 | $15,080.00 | federal floor; no state rate |
| South Dakota | $8.65 | $17,992.00 | statewide |
| Tennessee | $7.25 | $15,080.00 | federal floor; no state rate |
| Texas | $7.25 | $15,080.00 | statewide |
| Utah | $7.25 | $15,080.00 | statewide |
| Vermont | $10.00 | $20,800.00 | large-employer rate |
| Virginia | $7.25 | $15,080.00 | statewide |
| Washington | $11.00 | $22,880.00 | statewide |
| West Virginia | $8.75 | $18,200.00 | large-employer rate |
| Wisconsin | $7.25 | $15,080.00 | statewide |
| Wyoming | $7.25 | $15,080.00 | federal floor; state rate $5.15 |

Colorado, North Carolina and Washington keep the pilot's rates. The table holds
time-weighted rates unrounded; `tests/test_job_entry_national.py` checks each
against its exact day-weighted fraction.

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

## National run

`scripts/modal_job_entry.py` runs the test on Modal, one candidate rank of one
household part per container (2 CPUs, 32 GiB). The parts are the frozen
experiment's four disjoint household parts (`--parts 4`, seed 0, full weight),
the same partition the raise union reads; the full-sample Medicaid totals make
each household's result independent of its part. Each container runs
`scripts/expanded_job_entry_national.py`, which reuses the pilot's eligibility,
rank, job inputs, branch and resource measure, and stops on any failed check:

1. a zero-change branch leaves every household's net income, resources and every
   part of net income exactly unchanged;
2. the job branch leaves every household without a tested adult exactly unchanged;
3. each entrant's earnings equal the table's rate times 2,080 (within $0.02 for
   float32), at 40 hours and 52 weeks, and nobody else's earnings change;
4. every month's stored WIC take-up draw is unchanged;
5. the parts of net income add up to its change, and the pilot's resource measure
   agrees with its decomposition, both within $1;
6. the count of tested adults matches the part's plan for that rank.

The smoke run adds the pilot's fresh-simulation check.

For each tested adult the person rows hold `person_index` (the position in the
part's person table, as in the raise union), `person_id`, `household_id`,
`state_code`, `rank`, `hourly_wage`, `gross_pay`, `d_net_single_ptc` (the
pilot's measure: health coverage at government cost, premium tax credit counted
once), `d_net_without_health` (every part of net income except health benefits
and costs, as in the raise experiment), `d_net`, and the signed change in every
part of net income. Rows are record-level and git-ignored
(`results/job_entry/per_person/`). Each JSON record under
`results/job_entry/parts/` names its rows by a unique run id, hashes them, and
records the checks, sample counts, MicroSeries-weighted counts, timing, peak
memory, wage rates and code hashes. Only a complete, validated pair is published
to the volume or installed locally, never over an existing file; a relaunch
skips every rank already written.

Under the wage scope `resolved`, Maryland and New York candidates were counted as
deferred by state, because wages.json then lacked their rates. With the rates
added, `--scope states:MD,NY` tests only them, with the same per-rank files under
its own scope name. A complete job-entry union needs both scopes, and every
candidate in exactly one. Now that wages.json resolves all 51 jurisdictions, a
fresh `resolved` run would cover Maryland and New York too, so the union reads
the existing `resolved` records with the `states-MD-NY` records rather than
rerunning `resolved`.

The smoke run (`results/job_entry/parts/smoke_job_entry_2017_p4_0_s0_h150_seed17/`)
tested rank 1 in a fixed 150-household subsample of part 0, seed 17: one
candidate household from each of the 51 jurisdictions, then random candidate and
non-candidate households. It tested 113 adults in 49 jurisdictions and deferred
Maryland and New York. Every check passed: the zero-change branch and the 37
untouched households changed by exactly $0; entrants' earnings were within
$0.0009 of the table's rate times 2,080, and nobody else's changed; no WIC draw
changed; the parts summed to net income within $0.03 and the resource measure
matched its decomposition within $0.02; the fresh simulation matched exactly. It
took 208 seconds with a peak of 3.7 GiB. These counts check the code path; the
selected subsample supports no population inference.

The plans (`results/job_entry/plan/`) count in-scope sample candidates by rank:
part 0 has ranks 1–5, part 1 ranks 1–5, part 2 ranks 1–8 and part 3 ranks 1–4,
22 containers in all.

The `resolved` run tested 12,772 sample candidates in 49 jurisdictions, every
in-scope candidate once, and deferred 838 in Maryland and New York. All 22
records validate against their rows and plans, and every check passed: zero
change and untouched households exactly $0, entrants' earnings within $0.0009
of the rate times 2,080, no other earnings or WIC draw changed, the parts summed
to net income within $0.25 and the resource measure matched its decomposition
within $0.05. Containers took 5.5 to 11 minutes, with a peak of 6.3 GiB. The
records and rows stay out of git; they are the input to the union step.

The `states:MD,NY` run (commit aa3309b) tested the 838 deferred candidates,
265 in Maryland and 573 in New York, in 15 containers: part 0 ranks 1–4, part 1
ranks 1–3, part 2 ranks 1–4 and part 3 ranks 1–4. In each part its plan counts
exactly the candidates the `resolved` plan deferred, and its rows share no
person with that part's `resolved` rows; together the two scopes cover every
candidate of each part once. All 15 records validate against their rows and
plans, and every check passed: zero change and untouched households exactly $0,
entrants' earnings within $0.0008 of the rate times 2,080 ($9.0021 in Maryland,
$9.7019 in New York), no other earnings or WIC draw changed, the parts summed to
net income within $0.10 and the resource measure matched its decomposition within
$0.02. Containers took 5.5 to 10 minutes, with a peak of 6.3 GiB. These records
carry the new wages.json hash; the other 49 jurisdictions' rates are identical
to those the `resolved` records used.

```sh
MODAL_PROFILE=policyengine modal run scripts/modal_job_entry.py --check-only
MODAL_PROFILE=policyengine modal run scripts/modal_job_entry.py --smoke
MODAL_PROFILE=policyengine modal run scripts/modal_job_entry.py --plan-only [--scope states:MD,NY]
MODAL_PROFILE=policyengine modal run --detach scripts/modal_job_entry.py [--scope states:MD,NY]
MODAL_PROFILE=policyengine modal run scripts/modal_job_entry.py --fetch
```

## Remaining work

Write the job-entry union step over the per-rank rows of both scopes, checking
that every candidate appears exactly once across ranks and scopes; review the
observable availability
restrictions; compare job-entry resource components with the main raise
experiment; and validate the main strict-cliff group and the additional
high-loss group under the same union. Uncertainty must resample source
households together with their duplicate records. The national run produces
per-person changes only: no job-entry union, population total or overlap with
the raise union exists yet.
