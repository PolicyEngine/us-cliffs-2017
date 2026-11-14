# Recent-population historical-law counterfactual

Proposed research protocol. Fresh estimation requires the population adapter and model/data qualification described below. Existing result files report the separate 2017-oriented hybrid sensitivity.

## Estimand and reference population

Compare the modeled 2017 and 2025 tax-benefit systems on one synthetic population with recent household characteristics. This estimates differences under the specified policy and resource conventions; it does not estimate actual 2017 incidence or population change.

Prepare the certified recent microdata once for 2025, freezing model/data/Core versions, source hashes, input projection, entity membership, ages, geography, survey weights, take-up draws and the selected adults. Record every retained payment input and every derived override. A change of input contract or data release requires a new preparation receipt. The `populace-us-2024-spm-20260909` and `populace-us-2024-spm-20260915` release tags have identical raw H5 bytes (SHA-256 `6496cc4393d4d3c6574f76eca231de5898c803b9067645591fd5c4d3e65aee84`), but this does not prove identical prepared inputs on a changed model.

Initialize each policy calculation at its native year, including parameter-driven structural reforms, and calculate at that year. An annual supplied age defines the synthetic person's age in each experiment. Exclude cohort-sensitive Social Security entitlement and claiming changes from this comparison; preserving actual birth cohorts is a different estimand. Do not silently alter loan or mortgage dates. Resolve their legal interpretation, or explicitly hold and exclude the affected deduction components before describing the covered historical tax provisions.

## Currency and historical timing

Use the published annual-average CPI-U, U.S. city average, all items, not seasonally adjusted. The frozen 2017–2025 values appear in [`price_basis.csv`](price_basis.csv). The primary [BLS table](https://www.bls.gov/regions/northeast/data/consumerpriceindex_us_table.htm) reports 245.120 for 2017 and 321.943 for 2025. Its [shutdown FAQ, question 10](https://www.bls.gov/cpi/additional-resources/2025-federal-government-shutdown-impact-cpi-faq.htm) explains that the 2025 annual average uses the 11 published months. There is no completed 2026 annual average in this artifact; 2026 rule tests do not require a 2026 population comparison.

For native year y, set D_y = CPI_y / CPI_2025. Multiply each approved primitive monetary input and the earnings increment by D_y, retaining its hourly, monthly, annual or stock unit. Divide the resulting cash-resource outcomes by D_y for presentation in 2025 dollars. Preserve ages, identifiers, relationships, weights, rates and date facts. Use this one price conversion instead of the old hybrid's distinct wage/COLA/health/population factors. Native statutory thresholds and rounding remain native; do not additionally rebase policy parameters or automatically project the seeded inputs again.

The model's CPI-U parameter contains monthly observations. Looking up its January value does not supply this annual-average price basis. Disclose the reference dataset's economic projection separately from the common price conversion.

Supply monthly variables through reviewed period dispatch; an annual payment is not its monthly amount repeated twelve times. Define reference-history inputs for y−1/y−2 and distinguish an instantaneous earnings shock from a steady-state increase. A model fallback to the earliest income record cannot silently select the lookback convention.

## Input and health accounts

Use source-backed dispositions for every live input. Preserve observed endowments; recompute taxes, eligibility and benefits. The static 377-label/94-monetary-field inventory is a starting list, not a runtime compatibility certificate. Resolve missing aliases and conflicting inputs explicitly. Missing independent qualified dependent-care costs remain missing/defaulted, not observed zero or an amount inferred from employer benefits or gross care bills.

Hold any declared exogenous Social Security background payments at the same real amount; audit constructor migration and final overrides so entitlement responses do not re-enter accidentally. Recompute covered taxability and means tests. Do not label those held payments as 2017 Social Security entitlement law.

The cash and near-cash account and the account including health coverage must use explicit, mutually consistent component lists. For the latter, use common unmasked reference health prices by location, age, family tier and benefit category, scaled into native currency. Recompute legal coverage and affordability under each law. An eligibility-masked SLCSP/CHIP output cannot be the common price. Medicaid's enrollment-dependent cost allocation requires an explicit reference-price convention, not just reuse of state spending totals. Count premium credits once. Government cost is a valuation proxy, not household willingness to pay.

## Earnings experiments and reporting

Freeze the selected-adult ranking on the reference preparation and change one adult at a time. The initial comparison uses the same real $1,000 annual earnings increase. Add larger increments after completing each scenario run, and label job entry at a law-specific minimum wage as a combined wage/policy experiment.

Report finite-increment endpoint losses. The sign test can capture a discrete notch, overlapping continuous phase-outs above 100%, or rounding; it does not separately identify the prevalence of mathematical discontinuities. Keep the existing tax-notch/kink literature and hypothetical household paths in the paper. Label every table with law year, reference population/preparation, real increment, resource account and covered/held components.

Run every reported law, earnings transition and valuation scenario through the managed model. Use MicroSeries operations and entity mapping for weighted statistics; do not reconstruct person, tax-unit or household weights in analysis code. Retain the survey-source household cluster for paired uncertainty. Saved totals from the hybrid or another scenario cannot substitute for a fresh run.

## Validation before estimation

Before population execution, obtain the historical policy integration and a supported managed model/Core/data contract. On November 14, 2026, the available certificate in `policyengine` 6.19.0, bound to the 20260915 data release, refused the development target declaring US 2.124.0 and Core 3.36.0 (country source `43ca7bd3cd8615cac187db1b270ec2c3dd77f85f`). Unchanged H5 bytes and matching version text do not establish compatibility. Use the existing US qualification and publisher workflow with genuine wheel identities, loader/input checks and measured drift.

Verify the native-year adapter on bounded cases: structural initialization, entity/age/weight and real-input invariants, monthly dispatch, lookbacks, source-input migrations, fresh-versus-clone/order agreement, a zero earnings change, and known tax/benefit boundaries. Verify the common health-price account separately. The currency helper in `cliffs2017/native_currency.py` has pure synthetic example and property tests; it is neither an engine adapter nor a population qualification.

Execute each population scenario, retain its complete run and provenance records, and independently review the resulting estimates before replacing the paper's tables.
