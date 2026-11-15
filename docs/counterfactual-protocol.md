# Recent-population historical-law counterfactual

The proposed comparison uses one recent reference population. Fresh estimates require a population adapter and model/data qualification. Existing result files report the separate 2017-oriented hybrid sensitivity.

## Estimand and reference population

Compare the modeled 2017 and 2025 tax-benefit systems on one synthetic population with recent household characteristics. Estimate differences under the specified policy and resource conventions, excluding actual 2017 incidence and population change.

Prepare the selected recent microdata once for 2025 after qualification. Freeze model/data/Core versions, source hashes, input projection, entity membership, ages, geography, survey weights, take-up draws and the selected adults. Record every retained payment input and every derived override. A change of input contract or data release requires a new preparation receipt. The `populace-us-2024-spm-20260909` and `populace-us-2024-spm-20260915` release tags have identical raw H5 bytes (SHA-256 `6496cc4393d4d3c6574f76eca231de5898c803b9067645591fd5c4d3e65aee84`). A changed model still requires verification of its prepared inputs.

Initialize each policy calculation at its native year, including parameter-driven structural reforms, and calculate at that year. An annual supplied age defines the synthetic person's age in each experiment. For stored birth facts derived from age, record a reviewed drop disposition with its named scope and reason. Retain a birth fact alongside fixed age only under an explicitly reviewed compatible hold of birth-cohort consumers. The population adapter must keep held birth facts out of calculations that would contradict the fixed synthetic age. Never shift or clamp a retained date.

Exclude cohort-sensitive Social Security entitlement and claiming changes from this comparison. Preserving actual birth cohorts defines a different estimand. Preserve loan and mortgage dates; resolve their legal interpretation or explicitly hold and exclude the affected deduction components before describing the covered historical tax provisions.

## Currency and historical timing

Use the published annual-average Consumer Price Index for All Urban Consumers (CPI-U), U.S. city average, all items, not seasonally adjusted. The frozen 2017–2025 values appear in [`price_basis.csv`](price_basis.csv). The [BLS annual-average table](https://www.bls.gov/regions/northeast/data/consumerpriceindex_us_table.htm) reports 245.120 for 2017 and 321.943 for 2025. BLS explains in its [shutdown FAQ, question 10](https://www.bls.gov/cpi/additional-resources/2025-federal-government-shutdown-impact-cpi-faq.htm) that the 2025 annual average uses the 11 published months. This price file ends in 2025; a 2026 population comparison requires a completed annual-average price basis. Rule tests for 2026 do not require that population comparison.

For native year y, set D_y = CPI_y / CPI_2025. Multiply each approved primitive monetary input and the earnings increment by D_y, retaining its hourly, monthly, annual or stock unit. Divide each reported native-currency cash or health-inclusive resource total and loss by D_y before presentation in 2025 dollars or comparison with common-dollar thresholds. Preserve ages, identifiers, relationships, weights, rates and retained date facts. Apply this one price conversion throughout the comparison. Native statutory thresholds and rounding remain native; do not additionally rebase policy parameters or project the seeded inputs again.

The model's CPI-U parameter contains monthly observations. Use the annual-average price basis above for this conversion and disclose the reference dataset's economic projection separately.

Supply monthly variables through reviewed monthly blocks and retain annual payment totals in annual variables. Define reference-history inputs for y−1/y−2 and distinguish an instantaneous earnings shock from a steady-state increase. Specify the lookback convention before relying on a model fallback to its earliest income record.

## Input and health accounts

Use source-backed dispositions for every live input. Preserve observed endowments and recompute taxes, eligibility and benefits. Review the preliminary 377-label inventory against the actual runtime contract, resolving missing aliases and conflicting inputs explicitly. Record missing independent qualified dependent-care costs as missing or defaulted. Employer benefits and gross care bills do not establish those costs.

Hold declared exogenous Social Security background payments at the same real amount and exclude entitlement and claiming responses. Audit constructor migration and final overrides so those responses cannot re-enter accidentally. Recompute covered taxability and means tests, and identify held payments separately from historical Social Security entitlement law.

Define explicit, mutually consistent component lists for the cash and near-cash account and the account including health coverage. For the latter, use common unmasked reference health prices by location, age, family tier and benefit category, scaled into native currency. Recompute legal coverage and affordability under each law. Obtain common prices independently of eligibility-masked second-lowest-cost silver plan (SLCSP) and Children's Health Insurance Program (CHIP) outputs. Specify reference prices for Medicaid separately from its enrollment-dependent cost allocation. Count premium credits once. Value coverage at government cost and exclude interpretations of household willingness to pay.

## Earnings experiments and reporting

Freeze the selected-adult ranking on the reference preparation and change one adult at a time. The initial comparison uses the same real $1,000 annual earnings increase. Add larger increments after completing each scenario run, and label job entry at a law-specific minimum wage as a combined wage/policy experiment.

Report finite-increment endpoint losses. These losses can reflect a discrete notch, overlapping continuous phase-outs above 100%, or rounding. Distinguish the endpoint-loss count from the prevalence of mathematical discontinuities. Label every table with law year, reference population/preparation, real increment, resource account and covered or held components.

Run every reported law, earnings transition and valuation scenario through the managed model. Preserve entity mappings when applying frozen survey weights, and retain the survey-source household cluster for paired uncertainty. Compute each scenario afresh; saved totals from the hybrid or another scenario cannot supply its results.

## Validation before estimation

Before population execution, obtain the historical policy integration and a supported managed model/Core/data contract. Use the US qualification and publisher workflow with genuine wheel identities, loader/input checks and measured drift. Matching raw H5 bytes or version labels alone cannot establish compatibility.

Verify the native-year adapter on bounded cases: structural initialization, entity/age/weight and real-input invariants, reviewed age/birth dispositions, monthly dispatch, lookbacks, source-input migrations, fresh-versus-clone/order agreement, a zero earnings change, and known tax/benefit boundaries. Verify the common health-price account separately. The currency helper converts declared input units and has pure synthetic example and property tests. Adapter and population qualification require their own checks.

Execute each population scenario, retain its complete run and provenance records, and independently review the resulting estimates before replacing the paper's tables.
