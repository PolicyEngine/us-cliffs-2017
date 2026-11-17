# Coverage split of the with-health strict group, 2017 rules

With health coverage counted at government cost, about 31.9 million people live in
households that a raise or a job would leave with less (`with_health` strict, the
51-jurisdiction combined union, run `1c0cc9ddcfd7d876`). Without health coverage, the
same test finds 3.1 million. A largest-loss cut names the program behind each loss but
not whether coverage ended. `scripts/coverage_split.py` asks, for each person whose
health value falls in a strict scenario, whether their public coverage ended, moved to
another program, or only shrank within the same program. Results:
`results/coverage_split_2017.json` (aggregates only).

## Results

Weighted household members, with unweighted sample households in parentheses. Each
strict household falls in exactly one category, so the four middle columns add up to
the strict count.

| Set | Strict | Coverage ends (any a) | Program switch, no end (b) | Same program only (c) | No health fall | Strict after zeroing c |
|---|---:|---:|---:|---:|---:|---:|
| Job | 10,775,585 (1,124) | 9,634,688 (1,008) | 981,309 (96) | 7 (1) | 159,580 (19) | 10,775,585 (1,124) |
| Raise union | 24,003,304 (3,340) | 17,893,599 (2,533) | 3,446,809 (451) | 485,334 (77) | 2,177,561 (279) | 23,807,585 (3,300) |
| Combined | 31,909,535 (4,126) | 25,347,359 (3,269) | 3,990,596 (501) | 485,334 (76) | 2,086,247 (280) | 31,713,817 (4,087) |
| Combined, $1,000 raise | 15,970,727 (2,024) | 12,433,037 (1,568) | 1,912,890 (225) | 235,405 (42) | 1,389,395 (189) | 15,907,552 (2,009) |

- **Coverage ends for most.** In the combined set, 79% of the 31.9 million live in a
  household where someone's public coverage ends. Another 12.5% live where coverage only
  moves to another program, mostly from Medicaid to CHIP (1,726 sample person-scenarios)
  or from Medicaid to the premium credit (438). In 6.5%, nobody's health value falls: the
  loss is in cash or other benefits.
- **Same-program shrinkage is small.** Only 1.5% (485,334) live where coverage only
  shrinks within a program. Of these, 289,616 lose through a smaller premium credit or a
  larger CHIP premium (`only_c_other`), and 195,718 through a smaller Medicaid, CHIP or
  MSP value (`only_c_mcm`).
- **The counterfactual removes 0.6%.** Adding back the Medicaid/CHIP/MSP change of every
  bucket (c) person takes the combined count from 31,909,535 to 31,713,817. It removes
  exactly the `only_c_mcm` households in every set: 195,718 from the raise union, 63,176
  from combined with the $1,000 raise, and none from the job test.
- **Where within-program values fall.** Among strict scenarios, 274 sample people lose
  Medicaid, CHIP or MSP value within the same program (`c_mcm`):
  - 160 keep Medicaid, all in New York, where the family-tier share changes when the
    number of enrollees in the tax unit changes;
  - 114 keep MSP but drop from a full year of QMB to SLMB (113) or QI (1), which cuts
    `msp_cost` from $4,071.80 to $1,608.00 a year.

  No Medicaid enrollee outside a family-tier state changes value, as the cost formula
  implies.
- **People by bucket (combined, weighted people).** Each person takes the worst bucket
  over the set's strict scenarios:
  - a: 12,404,565 (5,386 sample people);
  - b: 2,722,912 (1,296);
  - c_other: 411,030 (265);
  - c_mcm: 279,950 (137);
  - other: 0.

  The JSON gives these for every set, with the members of their households.
- **Sensitivity.** Adding back every same-program Medicaid/CHIP/MSP change in either
  direction, in every tested household, gives 31,744,212 combined. That is more than the
  primary counterfactual, because within-program gains (a New York enrollee's share rises
  when a relative leaves Medicaid) are also removed. For the job test it gives
  10,784,012, above the strict count: two sample households that were not strict become
  strict once their gains are removed.

"Coverage ends" means the person holds no public program after the change. The model
assigns no value to employer coverage or unsubsidized marketplace coverage, so this
analysis cannot say whether the person becomes uninsured.

## Variables (policyengine-us 2.116.0)

The with-health measure is the change in `household_net_income` plus the change in
`marketplace_net_premium`, so the premium tax credit counts once. Its health parts are
`gov.household.household_health_benefits` (dated 2022-01-01; the model backdates
parameters to 2015) and the CHIP premium (`chip_premium`, a cost); the marketplace
premium cancels.

| Program | Enrolment | Value | Entity |
|---|---|---|---|
| Medicaid | `medicaid_enrolled` (eligible and takes up) | `medicaid_cost` = `medicaid_cost_if_enrolled` | person |
| CHIP | `chip_enrolled` | `chip` = `per_capita_chip` (state separate-CHIP spending per enrollee) | person |
| Medicare Savings Program | none; `msp_cost > 0` | `msp_cost` (monthly `msp_benefit_value` + `qmb_cost_sharing`; zero for Medicaid enrollees) | person |
| ACA premium credit | `is_aca_ptc_eligible` in a unit with `assigned_aca_ptc > 0` | `assigned_aca_ptc` = `aca_ptc` x `takes_up_aca_if_eligible` | tax unit |
| State programs | positive value | `assigned_ca_premium_subsidy`, `basic_health_program`, `co_omnisalud`, `assigned_co_premium_assistance`, `ct_covered_connecticut`, `ma_connector_care`, `md_premium_assistance`, `nj_njhps`, `assigned_nm_premium_assistance`, `vt_premium_assistance`, `wa_cascade_care_savings` (tax unit); `or_healthier_oregon_cost` (person) | |

Medicaid's eligibility category is `medicaid_category` and its spending group
`medicaid_group` (child, non-expansion adult, expansion adult, aged/disabled), but
neither sets the value: `medicaid_cost_if_enrolled` is the state's spending times the
person's cost index over the state's index-weighted enrolment
(`medicaid_slcsp_state_denominator`, fixed here at its full-sample total by
`cliffs2017/medicaid.py`). The cost index is the age-rated benchmark premium, or, where
family tiers apply (New York and Vermont), the tax unit's tier premium divided by its
Medicaid enrollees. The package's own test
`test_medicaid_cost_if_enrolled_is_not_pathway_dependent` checks that two enrollees of the
same age in the same state get the same value whatever their pathway. So a Medicaid
enrollee's value can change only when the tax unit's family tier or enrollee count
changes. The MSP value changes with the MSP category (QMB covers Part A and B premiums
and cost sharing; SLMB and QI cover the Part B premium).

## Method

1. **Rerun.** On Modal (app and volume `us-cliffs-2017-coverage-split`), each scenario of
   each household part is rerun exactly as the frozen experiment ran it: the job test at
   each candidate rank over every jurisdiction (the `resolved` and `states-MD-NY` scopes
   together, 22 containers), and each raise ($1,000, $2,000, $5,000) at adult ranks 1 and
   2 (24 containers). The inputs are the union run's own rows, read from their checkouts
   and checked against its manifest's SHA-256. Every container records each household
   member's coverage and value before and after, and stops, publishing nothing, unless
   every tested adult's household change matches the saved row to $0.01, both with and
   without health, and the rerun's strict set equals the saved one.
2. **Health value per person.** A person's value is their own `medicaid_cost`, `chip` and
   `msp_cost` plus shares of tax-unit amounts: the premium credit over the unit's
   credit-eligible members, state programs over every member, and minus the CHIP premium
   over the unit's CHIP enrollees (each over every member when nobody qualifies). The
   shares add up to the unit's amounts, so people's changes add up to their household's
   health change; the classifier checks this, and that each household's
   `medicaid_cost`, `chip` and `msp_cost` changes equal the sums over its members.
3. **Primary program.** The first a person holds of Medicaid, CHIP, MSP, the premium
   credit and a state program.
4. **Buckets.** A person's value falls when it drops by more than half a cent.
   - (a) a primary program before, none after;
   - (b) a primary program before and after, but a different one;
   - (c) the same primary program, lower value: `c_mcm` when the fall is mainly in
     `medicaid_cost`, `chip` or `msp_cost`, `c_other` when mainly in the premium credit,
     a state program or the CHIP premium;
   - `other`: a fall with no program before (a CHIP premium share), counted apart.
5. **Households and sets.** In each scenario a strict household is `any_a` if any member
   is in (a), else `b_no_a` if any is in (b), else `only_c` (split into `only_c_other`
   and `only_c_mcm`), else `other_only`, else `no_fall` (no member's health value fell:
   a loss outside health). In a test set (job; raise_union, the three raises;
   combined, either; combined_1000, the $1,000 raise or the job), a household is strict
   if it is strict in any of the set's scenarios, and takes the worst category over
   those. A person takes the worst bucket over them (a, b, c_other, c_mcm, other).
6. **Counterfactual.** In each strict scenario, add back the `medicaid_cost + chip +
   msp_cost` change of every bucket (c) person, whose program did not change, and test
   again whether the household keeps less than nothing. A smaller premium credit, state
   subsidy or larger CHIP premium stays a loss. A household stays strict in a set if it
   stays strict in any of its strict scenarios. A sensitivity adds back every
   same-program Medicaid/CHIP/MSP change in either direction, in every tested household.
7. **Counting.** On Modal, each part's frozen simulation counts the flags with
   MicroSeries: household flags mapped to residents with `map_to="person"`, as the
   combined union does; no stored weight column is read. The strict totals must
   reproduce the union's per part and nationally, and the categories must add up to
   them.

## Checks

- **Rerun versus saved rows.** All 46 scenarios ran: 22 job containers and 24 raise
  containers. They compared 320,039 tested adults. Every household change matches the
  saved row exactly, both with health (`d_net_single_ptc`) and without; the largest gap is
  $0.00. The rerun strict set equals the saved one in every scenario.
- **Classifier versus the union.** In every part and set, the strict adults equal those
  recomputed from the union's saved rows. The strict sample households equal the union's
  part records: job 1,124, raise union 3,340, combined 4,126, combined with the $1,000
  raise 2,024.
- **People add up to households.** People's `medicaid_cost`, `chip` and `msp_cost` changes
  add up to their household's exactly. Their health-value changes add up to the
  household's health change to within floating-point rounding (4e-12 dollars). No tax unit needed the fallback share for the
  premium credit.
- **Weighted counts.** Per part and nationally, the strict households, adults and members
  equal the union's exactly. In each part and set, the categories add up to the strict
  count.
- **Tests.** `tests/test_coverage_split.py` has a fixture for each bucket:
  - (a);
  - (b), Medicaid to the premium credit and Medicaid to CHIP;
  - `c_mcm`, the New York family tier and MSP from QMB to SLMB;
  - `c_other`, a smaller premium credit and a higher CHIP premium.

  It also tests the share allocation, category order, the counterfactual, the raise
  worker requirement and the set logic.

## Reproduction

```sh
MODAL_PROFILE=policyengine modal run scripts/modal_coverage_split.py --stage smoke
MODAL_PROFILE=policyengine modal run scripts/modal_coverage_split.py --stage job
MODAL_PROFILE=policyengine modal run scripts/modal_coverage_split.py --stage raise
python scripts/coverage_split.py classify
MODAL_PROFILE=policyengine modal run scripts/modal_coverage_split.py --stage aggregate
python scripts/coverage_split.py combine --tag 4721d56e6b03f659  # tag the aggregate stage prints
```

The scenario rows, classified flags and part records stay in `results/coverage_split/`,
which git ignores.
