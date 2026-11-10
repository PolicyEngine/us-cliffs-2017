# Tax-benefit cliffs under 2017 rules: methodology

PolicyEngine, November 2026

## What we estimate

An adult faces a cliff when their household's net income would fall if they earned $1,000 more in a year. We count three things nationally:

1. the adults who face a cliff;
2. the households they live in;
3. everyone who lives in those households, children included.

We run the count under 2017 tax and benefit rules, and under 2025 rules for comparison. Each year has two versions: one counting cash and near-cash income only, and one that also counts health coverage (Medicaid, CHIP and ACA premium tax credits).

The scripts in this repository write the results table, [results/summary.md](results/summary.md), so every number in it traces to a run described here.

## How the model finds a cliff

We use PolicyEngine-US, an open-source microsimulation model of federal and state taxes and benefits ([github.com/PolicyEngine/policyengine-us](https://github.com/PolicyEngine/policyengine-us)). The model computes each household's net income, then runs a second version of the household with one adult's earnings $1,000 higher and computes it again. If net income falls, that adult faces a cliff, and the drop is their cliff gap.

- **Who it tests.** The model ranks a household's adults by market income and tests the top two, one at a time. It doesn't test children or a third adult, so it counts at most two adults per household as facing a cliff. The model tests the top two even when they have no earnings; our worker counts keep only adults with positive earnings: wages plus self-employment income, including the self-employment income from specified service businesses that the model holds separately.
- **Share of workers.** We divide the adults on a cliff who have earnings by everyone with earnings. That base includes the people with earnings whom the model doesn't test, children and adults below the top two, who can't count as facing a cliff: 23.5 million of the 177.8 million people with earnings in 2017. Among tested workers alone, each share would be about 1.15 times as large.
- **How it adds the $1,000.** The raise follows the adult's current mix of wages and self-employment income, and goes to wages when they have no positive earnings. The second version keeps every input and recomputes everything that depends on earnings: taxes, credits and benefits.
- **Net income.** Household net income equals market income plus benefits and refundable tax credits, minus taxes before refundable credits. Benefits include Social Security, SSI, SNAP, WIC, free and reduced-price school meals, TANF, unemployment compensation, housing assistance, Head Start and state benefit programs, as the model's `gov.household.household_benefits` parameter lists them. We leave out the Commodity Supplemental Food Program, which the model's list adds from 2024 (below).
- **Health coverage.** With health coverage counted, net income also adds Medicaid, CHIP, the ACA premium tax credit, Medicare Savings Programs and state health programs, and subtracts CHIP premiums and marketplace premiums net of the premium tax credit. The model values Medicaid at government cost: it spreads each state's Medicaid spending across the state's enrollees in proportion to a cost index built from the benchmark marketplace premium: the premium for the enrollee's age, or an equal share of a family-tier premium among the tax unit's enrollees.

### Medicaid's state totals

Two of the formulas behind Medicaid's value add up over everyone in a run, not over one household. One gives each state's average cost index, which stands in for an enrollee whose own index is zero; the other adds the cost indices of the state's enrollees, and the model divides the state's spending by that sum. A run over a quarter of the households at full weight therefore finds about a quarter of each state's sum: across our four household groups in 2017, it would value each enrollee at a median of about four times the full-sample amount, and at 2.2 to 11.7 times depending on the state and group. Under our pre-2018 premium tax credit reform (below), the model would also take the sum from the unreformed policy while taking each enrollee's index from the reform.

So we compute both totals for the full sample under each configuration's own policy and hold them fixed in every run ([cliffs2017/medicaid.py](cliffs2017/medicaid.py)). Each household's Medicaid value then depends only on its own records and its state, and Medicaid's value over the full sample equals the spending the model spreads. PolicyEngine-US holds state Medicaid spending for 2020 through 2023 only, so the 2017 runs spread the 2020 totals ($661.5 billion across the states and DC) and the 2025 runs spread the 2023 totals ($880.0 billion).

Each Medicaid value is proportional to its state's spending, so scaling every state's spending by a factor scales each adult's change in Medicaid by the same factor, and the runs compute the counts at 0.8, 0.9, 1.1 and 1.2 times the spending they spread ([results/summary.md](results/summary.md)). Counting the premium tax credit twice, as the model does, valuing Medicaid at 0.8 times that spending lowers the 2017 count with health coverage by 1.2%, and 1.2 times raises it by 0.5%. The 2025 count doesn't change at any of the four factors.

### The premium tax credit counts twice

With health coverage counted, PolicyEngine-US adds the premium tax credit to net income and also subtracts the marketplace premium net of that credit. A $1 cut in the credit therefore lowers net income by $2 for an enrollee who pays a premium: $1 less credit and $1 more net premium. [scripts/ptc_household.py](scripts/ptc_household.py) shows one case: a Texas adult aged 40 who earns $30,000 in 2025 loses $94 of credit to a $1,000 raise, and net income rises $615.50 as the model counts it, or $709.50 with the credit counted once ([results/ptc_household.json](results/ptc_household.json)). We report the counts as the model computes them and again with the credit counted once, at its value to the government, the way the model counts Medicaid and CHIP. Our headline counts with health coverage count the credit once.

### The Commodity Supplemental Food Program

The Commodity Supplemental Food Program (CSFP) gives food packages to people aged 60 or older with low incomes. From 2024, PolicyEngine-US counts it in household benefits and gives a package to every person its eligibility rules admit, with no take-up rate. Weighted up from a quarter of the households, the model gives 8.4 million people a package in 2025, worth $5.0 billion in all. The parameter that sets the package's 2025 value, $601, divides $425 million of program cost by 707,000 participants ([scripts/csfp_reach.py](scripts/csfp_reach.py), [results/csfp/reach_2025.json](results/csfp/reach_2025.json)). A 2017 run reads the model's benefit list from before 2024, which has no CSFP. So that both years count the same benefits, the 2025 runs leave CSFP out as well ([cliffs2017/benefits.py](cliffs2017/benefits.py)). Counting it as the model does adds 166,000 adults, or 24%, to the 2025 count without health coverage; [results/summary.md](results/summary.md) gives both versions.

### What lowers net income

For each adult on a cliff we break the change in net income into its parts (earnings, each benefit, refundable credits, taxes and health costs) and name the part that falls most. The parts add up to the model's own change in net income for every adult tested. Each result file reports `decomposition_flag_mismatches`, the number of adults whose cliff flag the breakdown fails to reproduce.

## The population

We use Microcosm, PolicyEngine's microdata for the US, in its 2024 build (`policyengine/populace-us`, file `populace_us_2024.h5`, revision `populace-us-2024-spm-20260909`). Microcosm builds on the Census Bureau's Current Population Survey Annual Social and Economic Supplement, pooling its 2023, 2024 and 2025 surveys, which cover incomes in 2022 to 2024, into 57,240 household records. It adds imputations from the IRS Statistics of Income Public Use File, the Federal Reserve's Survey of Consumer Finances, the Survey of Income and Program Participation, the CPS Outgoing Rotation Groups, the MEPS Insurance Component and the American Community Survey, then calibrates household weights to IRS, Census and program totals. The file holds 9,963 survey households twice, in a record labeled `asec` and a record labeled `puf_tax_detail` that share a `household_source_id`, each with its own weight.

PolicyEngine-US can age a dataset forward but not back, so we build the 2017 inputs ourselves. We scale every dollar amount in the 2024 data to 2017 levels with the index that fits it:

| Inputs | Index | 2017 ÷ 2024 |
|---|---|---|
| Wages, self-employment income, tips and wage-linked benefits (unemployment and workers' compensation, disability benefits) | SSA national average wage index | 0.7205 |
| Social Security and veterans' benefits | Cumulative Social Security cost-of-living adjustments | 0.7800 |
| Employer health premiums | CMS premium per enrollee | 0.6875 |
| Individual-market premiums | CMS premium per enrollee | 0.7111 |
| Out-of-pocket medical spending | CMS spending per person | 0.7212 |
| Every other dollar amount | CPI-U, January 2017 over January 2024 | 0.7839 |
| Household weights | Census population | 0.9556 |

Each index is the model's own parameter. Ages, family structure and the model's other non-dollar inputs stay as they were. The 2017 run therefore describes **2017 rules applied to today's population, with incomes and prices scaled back to 2017 levels and weights scaled to the 2017 population**. It doesn't capture how the population's makeup, its income distribution beyond these indices, or program take-up differed in 2017. Building a true 2017 population from the 2018 CPS survey would capture those differences. It is a larger project.

The 2025 runs use the same Microcosm build, which PolicyEngine-US ages forward to 2025 with its own indices.

## 2017 rules

The model holds each tax and benefit parameter with the date it took effect, and a 2017 run reads the values in force in 2017. Three gaps matter:

- **The ACA premium tax credit before 2018.** PolicyEngine-US returns no premium tax credit before 2018, because its benchmark premium data start in 2018. Our `ACABefore2018` reform ([cliffs2017/aca2017.py](cliffs2017/aca2017.py)) applies the model's 2018 formula to 2017 with three changes. It sets the 2017 applicable percentages from IRS Revenue Procedure 2016-24 (2.04% of income below 133% of the poverty line, up to 9.69% from 300% to 400%). It scales the 2018 benchmark premiums back with the model's own premium index (359 in 2017, 481 in 2018). And it rates premiums by age with the curves CMS published for 2014 to 2017: the federal default rated everyone aged 0 to 20 at 0.635 of a 21-year-old's premium, while the model's 2018 curve, which it uses for every year, rates ages 0 to 14 at 0.765 and ages 15 to 20 at 0.833 to 0.970; New Jersey also had its own curve then. Medicaid's cost index uses the same curves, so this also changes how the 2017 runs spread Medicaid spending. The model already ends eligibility at 400% of the poverty line before 2021, which reproduces the 2017 subsidy cliff. It denies the credit at exactly 400%, which section 36B(c)(1)(A) allows, and agrees with the statute at every other income.
- **Parameters that start after 2017.** Where a parameter's first value postdates 2017, the model uses the earliest value it has, back to 2015. [results/parameters_read_2017.csv](results/parameters_read_2017.csv) lists the 4,155 parameters from the model's files that a 2017 run with health coverage reads, and when each one's values start. [scripts/audit_parameters.py](scripts/audit_parameters.py) records them with policyengine-core's parameter tracing, which it extends to two kinds of read the tracing misses, bracket scales and reads that formulas write as `parameters.gov.X(instant)`, and [scripts/summarize_parameters.py](scripts/summarize_parameters.py) prints the counts below. For 2,426 of them, at least one value starts after 1 January 2017, so the 2017 runs read a later year's value: 2,167 of the 3,336 state parameters, 48 of the 61 local ones and 208 of the 752 federal ones, 121 of which start in 2018. State programs carry most of it: 1,080 of the 1,571 state tax parameters start later, 841 of them in 2021, and so do 491 of the 536 state child care subsidy parameters. New Mexico's EITC, for example, takes the minimum age of 18 that the state set for workers without children from 2021. SNAP's state utility allowances by household size start in October 2017, the first month of fiscal 2018. The age curves start in 2018 as well; our reform replaces them for 2017. A few formulas also read a fixed later date. Oklahoma's EITC uses the federal credit's rules as of 2020, and Virginia TANF uses its need and grant standards as of October 2020. SNAP's time limit for adults without dependents follows the rules in force in June 2025: it covers ages 18 to 54, where the 2017 rule stopped at 49, and it exempts veterans, homeless people and former foster youth, which the 2017 rule didn't.
- **Formulas that start or change after 2017.** Before its first formula takes effect, a variable has no formula, and the model returns 0 for it unless the data supply it. [results/formula_starts_2017.csv](results/formula_starts_2017.csv) lists the 29 variables whose first formula starts after 2017, among them Maryland's senior tax credit and child tax credit, and the model's Medicaid rules for long-term care, which start in 2026, so the 2025 runs lack them too ([scripts/audit_formula_starts.py](scripts/audit_formula_starts.py)). [results/formula_changes_2017.csv](results/formula_changes_2017.csv) lists the 14 variables whose formula changes after 2017 ([scripts/audit_formula_changes.py](scripts/audit_formula_changes.py)). In 2017, four of them return a constant placeholder: the premium tax credit and the credit before its filing condition, which our reform replaces, New York's inflation refund, and the Basic Health Program, whose formula starts in 2026.

Two programs barely register in either year: Head Start totals $0, and housing assistance $5.5 billion in 2017 and $5.7 billion in 2025, while HUD spent $20.6 billion on housing vouchers alone in fiscal 2017 and $38.3 billion in fiscal 2025 (outlays, [USAspending](https://www.usaspending.gov/federal_account/086-0302)). The counts can miss cliffs from either program.

## Uncertainty

Each count comes with a 95% interval: the estimate plus or minus 1.96 standard errors from a bootstrap of 200 resamples of the survey's households, with the same weights. A resample draws Microcosm's two records of a survey household together, as one source household. With 200 resamples, each standard error carries Monte Carlo error of about 5%. The intervals cover sampling error only, not error in the model or the data, and they hold Medicaid's state totals fixed. They also ignore the CPS's design (its strata and clusters) and the overlap between the pooled surveys, which can interview the same household in consecutive years, so they likely understate sampling error. The rows of the results table share households, so the intervals don't tell whether two rows differ.

## Running it

The full sample needs more memory than one run can use, so we split the source households into four disjoint groups, run each at full weight and add the results. We found one way a household's results depend on other households in the model, Medicaid's state totals; with those held at their full-sample values, the four parts add up to a single full-sample run. [tests/test_additivity.py](tests/test_additivity.py) checks that on a small sample in every configuration: split in two, each person's marginal tax rate, net income and cliff flag match the unsplit run. The combine step checks that Medicaid's value over the four parts matches the spending it spreads, that every part ran the same code with the same settings, and that the first part's run without health coverage matches the run over the same households with four times their weights, which would catch results that depend on the weights' scale.

```bash
uv venv --python 3.13 && uv pip install -e ".[test]"
scripts/medicaid_totals.sh 4 0   # Medicaid's full-sample state totals, for the health runs
scripts/run_final.sh 4 0 0,1     # parts 0 and 1
scripts/run_final.sh 4 0 2,3     # parts 2 and 3
CSFP=keep scripts/run_final.sh 4 0 0,1,2,3 2025-plain,2025-health   # 2025 counting CSFP
python scripts/csfp_reach.py --year 2025 --fraction 0.25 --out results/csfp/reach_2025.json
scripts/run_batch.sh 0.25 0 && CSFP=keep scripts/run_batch.sh 0.25 0   # quarter-sample runs for the check
scripts/combine_final.sh 4 0     # results/final_*.json, results/csfp/ and results/summary.md
python scripts/ptc_household.py  # results/ptc_household.json
python scripts/audit_parameters.py 2017 40 > results/parameters_read_2017.csv
python scripts/summarize_parameters.py results/parameters_read_2017.csv 2017
```

`pytest` runs the tests. They cover the counts (exact values on a hand-built example, and the bootstrap's clusters), the household split and the check that one part scales to its subsample run, the deflation, the pre-2018 credit and its age curves, leaving out CSFP, and the parameter audit's tracing, which must record the reads core's tracing misses and change no value. For Medicaid's totals, they check that the sums add up across parts, follow the model's own formulas, never call the totals they replace, leave each household's value unchanged whichever part holds it, and spread exactly the states' spending. For the breakdown, they check that the parts add up, match a fresh simulation of the raised household, count the premium tax credit once on the Texas household above, name the largest loss, and reproduce the Medicaid scaling. Each result file records the PolicyEngine-US and policyengine-core versions, the dataset revision, the factors applied, the Medicaid totals file, the repository commit, a hash of the `cliffs2017` code and the run time.

## How these numbers relate to our April 2025 estimate

In April 2025 we estimated that 7.4 million people, all of them adults, would face a cliff in 2025. A bug in the model version we used then inflated that count about ninefold. [CORRECTION.md](CORRECTION.md) explains the bug and gives the corrected figures.
