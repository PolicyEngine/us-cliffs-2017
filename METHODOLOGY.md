# Tax-benefit cliffs under 2017 rules: methodology

PolicyEngine, November 2026

## What we estimate

A person faces a cliff when their household's net income would fall if they earned $1,000 more in a year. We count three things nationally:

1. the people who face a cliff;
2. the households they live in;
3. everyone who lives in those households.

We run the count under 2017 tax and benefit rules, and under 2025 rules for comparison. Each year has two versions: one counting cash and near-cash income only, and one that also counts health coverage (Medicaid, CHIP and ACA premium tax credits).

The results table in [results/summary.md](results/summary.md) comes straight from the runs described here. The scripts write it, so every number in it traces to a run in this repository.

## How the model finds a cliff

We use PolicyEngine-US, an open-source microsimulation model of federal and state taxes and benefits ([github.com/PolicyEngine/policyengine-us](https://github.com/PolicyEngine/policyengine-us)). The model computes each household's net income, then runs a second version of the household with one adult's earnings $1,000 higher and computes it again. If net income falls, that adult faces a cliff, and the drop is their cliff gap.

- **Who it tests.** The model ranks a household's adults by market income and tests the top two, one at a time. It doesn't test children or a third adult, so a household counts at most two people as facing a cliff. The model tests the top two even when they have no earnings; our worker counts keep only people with positive earnings.
- **How it adds the $1,000.** The raise follows the adult's current mix of wages and self-employment income, and goes to wages when they have no positive earnings. The second version keeps every input and recomputes everything that depends on earnings: taxes, credits and benefits.
- **Net income.** Household net income equals market income plus benefits and refundable tax credits, minus taxes before refundable credits. Benefits include Social Security, SSI, SNAP, WIC, free and reduced-price school meals, TANF, unemployment compensation, housing assistance, Head Start and state benefit programs, as the model's `gov.household.household_benefits` parameter lists them.
- **Health coverage.** With health coverage counted, net income also adds Medicaid, CHIP, the ACA premium tax credit, Medicare Savings Programs and state health programs, and subtracts CHIP premiums and marketplace premiums net of the premium tax credit. The model values Medicaid at government cost: each state's Medicaid spending, spread across enrollees with an age-based cost index.

### The premium tax credit counts twice

With health coverage counted, PolicyEngine-US adds the premium tax credit to net income and also subtracts the marketplace premium net of that credit. A $1 cut in the credit therefore lowers net income by $2 for an enrollee who pays a premium: $1 less credit and $1 more net premium. We report the counts as the model computes them and again with the credit counted once, at its value to the government, the way the model counts Medicaid and CHIP.

### What lowers net income

For each person on a cliff we break the change in net income into its parts (earnings, each benefit, refundable credits, taxes and health costs) and name the part that falls most. The parts add up to the model's own change in net income for every person tested. Each result file reports `decomposition_flag_mismatches`, the number of people whose cliff flag the breakdown fails to reproduce.

## The population

We use Microcosm, PolicyEngine's microdata for the US, in its 2024 build (`policyengine/populace-us`, file `populace_us_2024.h5`, revision `populace-us-2024-spm-20260909`). Microcosm builds on the Census Bureau's Current Population Survey Annual Social and Economic Supplement (2022 to 2024 surveys). It adds imputations from the IRS Statistics of Income Public Use File, the Federal Reserve's Survey of Consumer Finances, the Survey of Income and Program Participation, the CPS Outgoing Rotation Groups, the MEPS Insurance Component and the American Community Survey, then calibrates household weights to IRS, Census and program totals.

PolicyEngine-US can age a dataset forward but not back, so we build the 2017 inputs ourselves. We scale every dollar amount in the 2024 data to 2017 levels with the index that fits it:

| Inputs | Index | 2017 ÷ 2024 |
|---|---|---|
| Wages, self-employment income, tips and wage-linked benefits (unemployment and workers' compensation, disability benefits) | SSA national average wage index | 0.7205 |
| Social Security, reported SSI and veterans' benefits | Cumulative Social Security cost-of-living adjustments | 0.7800 |
| Employer health premiums | CMS premium per enrollee | 0.6875 |
| Individual-market premiums | CMS premium per enrollee | 0.7111 |
| Out-of-pocket medical spending | CMS spending per person | 0.7212 |
| Every other dollar amount | CPI-U | 0.7839 |
| Household weights | Census population | 0.9556 |

Ages, family structure and the model's other non-dollar inputs stay as they were. The 2017 run therefore describes **2017 rules applied to today's population, with incomes and prices scaled back to 2017 levels and weights scaled to the 2017 population**. It doesn't capture how the population's makeup, its income distribution beyond these indices, or program take-up differed in 2017. Building a true 2017 population from the 2018 CPS survey would capture those differences. It is a larger project.

The 2025 runs use the same Microcosm build, which PolicyEngine-US ages forward to 2025 with its own indices.

## 2017 rules

The model holds each tax and benefit parameter with the date it took effect, and a 2017 run reads the values in force in 2017. Two gaps matter:

- **The ACA premium tax credit before 2018.** PolicyEngine-US returns no premium tax credit before 2018, because its benchmark premium data start in 2018. Our `ACABefore2018` reform (cliffs2017/aca2017.py) applies the model's 2018 formula to 2017 with the 2017 applicable percentages from IRS Revenue Procedure 2016-24 (2.04% of income below 133% of the poverty line, up to 9.69% from 300% to 400%), and scales the 2018 benchmark premiums back with the model's own premium index (359 in 2017, 481 in 2018). The model already ends eligibility above 400% of the poverty line before 2021, which reproduces the 2017 subsidy cliff.
- **Parameters that start after 2017.** Where a parameter's first value postdates 2017, the model uses the earliest value it has. That affects state programs most: many state income tax parameters start in 2021, most state child care subsidy parameters start after 2017, and SNAP's state utility allowances start in fiscal 2018. results/parameters_read_2017.csv lists every parameter the 2017 runs read and the date of its first value.

Two programs barely register in either year: Head Start comes out at $0, and housing assistance totals about $4 billion, far below actual federal spending. Cliffs from those programs go uncounted.

## Uncertainty

Each count comes with a 95% interval from a household bootstrap: 200 resamples of the survey's households, with the same weights. The intervals cover sampling error only, not error in the model or the data.

## Running it

The full sample needs more memory than one run can use, so we split households into four disjoint groups, run each at full weight and add them up. Households don't interact in the model, so the sum equals a single full-sample run.

```bash
uv venv --python 3.13 && uv pip install -e ".[test]"
scripts/run_final.sh 4 0 0,1   # parts 0 and 1
scripts/run_final.sh 4 0 2,3   # parts 2 and 3
scripts/combine_final.sh 4 0   # results/final_*.json and results/summary.md
```

`pytest` runs the tests: the bootstrap, the household split, the deflation, the pre-2018 credit, and a check that the breakdown adds up and matches a fresh simulation of the raised household. Each result file records the PolicyEngine-US and policyengine-core versions, the dataset revision, the factors applied and the run time.

## How these numbers relate to our April 2025 estimate

In April 2025 we estimated that 7.4 million people face cliffs nationally. A bug in the model version we used then inflated that count about ninefold. [CORRECTION.md](CORRECTION.md) explains the bug and gives the corrected figures.
