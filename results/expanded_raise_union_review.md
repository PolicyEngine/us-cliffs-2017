# Independent review of expanded raise-union postprocessing

Review date: 11 November 2026. Reviewed `scripts/expanded_raise_union.py`, `scripts/expanded_historical.py`, `tests/test_expanded_raise_union.py` and `results/expanded_raise_union_2017.json`. No tax-benefit simulations, survey-weight aggregation, external messages or original-checkout edits were performed.

## Verdict

**APPROVE after the worker-guard delta reviewed below.** The preliminary numerical artifact and implementation pass the checks below. The result remains a selected-current-worker, three-point raise-grid result; it does not complete job entry, all-worker coverage, continuous-range exposure or the final combined analysis.

## Finding U1: verify the saved current-worker selection against its metadata

**Where:** `scripts/expanded_raise_union.py:234-259`, particularly the transition from the all-adult baseline recount to the worker-restricted masks.

The script checks each saved raise's all-adult strict-cliff totals and requires its CSV worker flags to agree across the three raise sizes. It does not compare the worker population reached or the strict-worker count with the source metadata's `change.workers_reached` and `change.<measure>.workers_on_cliff`. Consistently incorrect worker flags across all three CSVs therefore pass the existing identity/universe checks and leave every all-adult baseline check unchanged, while changing the analysis's defining current-worker population.

**Fix:** Count the saved worker mask through MicroSeries and compare it with `workers_reached`; compare each resource-specific zero-retention worker count with `workers_on_cliff`. Include a negative test where the worker flag changes consistently across every raise. This requires no economic-formula rerun or new weight arithmetic.

**Current numbers:** Independent spot verification of all 24 part/size/resource strict-worker adult counts already matches `workers_on_cliff` to the existing tolerance. Thus the current artifact does not exhibit this corruption, and the guard should not change its estimates.

## Checks that passed

- `uv run --no-sync pytest tests/test_expanded_raise_union.py -q -p no:cacheprovider`: **9 passed**.
- Every retention test uses a strict inequality, with finite, strictly positive earnings changes. Exactly 50% retained fails the below-half test; exactly zero retained fails the strict-loss test.
- The grid is limited to the already simulated $1,000/$2,000/$5,000 increases, one selected adult at a time. Dollar changes and resource changes are joined by original person index and checked against person and household identities.
- All three raises must preserve the same person, rank, household and worker universe. Duplicated identities, mismatched raise amounts, out-of-range indices and nonfinite resource changes fail.
- Source results check year, part count/index, seed, package pins, original-$1,000 replication, code hashes and committed code. New outputs record metadata/CSV hashes and the postprocessor's script hash.
- Stored CSV weight columns are excluded from `usecols`. New weighted counts use `simulation.calc(...).sum()` and `map_to='person'`; household unions use the model's household membership operations.
- The additional group is correctly formed at the **household level**: any tested raise retaining less than half, excluding every household with any tested strict-loss flag. This avoids counting a household in both narration groups when different adults satisfy different tests.
- The synthetic test exercises precisely that mixed-adult household case and confirms that household residents count once.
- The output documents the unmanaged frozen historical adapter, current-wrapper certification limitation, exact versions, government-cost resource measure, selected-current-worker population, finite grid and absence of new union sampling intervals. It does not claim a managed current-law analysis or bypass certification.

## Independently checked aggregate results

These are point estimates for the selected-current-worker population and the finite three-raise grid, counting household residents once:

| Health-inclusive group | Household members |
|---|---:|
| Negative retention at any tested raise | 24,003,303.574607007 |
| Below-half retention at any tested raise | 57,185,059.265749425 |
| Below-half households excluding every strict-loss household | 33,181,755.69114242 |

The first and third household-member counts add to the second, to numerical precision. The artifact also crosswalks the original all-selected-adult $1,000 household set: 6,045,189.590398442 original household members fall inside the new below-half union and 154,527.50188846642 fall outside. This confirms why retaining the old rounded household-member figure and subtracting it from the new union would be unsound.

No final placeholder, universal prevalence estimate, job-entry union or sampling interval follows from these selected-subset values alone.

## Final delta review: APPROVE

U1 is resolved. `summarize_part` now aggregates the saved worker mask through MicroSeries and validates `workers_reached` for each of the three raises. It also validates worker-only strict counts against `workers_on_cliff` for each size and resource measure before constructing the broader retention groups. The new regression tests cover both a consistently false mask across all raise sizes and a same-weight worker swap that preserves total workers and every all-adult strict total; the latter correctly fails the worker-specific strict guard.

Independent checks on the final artifacts:

- Re-ran the fast test file: **11 passed in 1.65 seconds**.
- Verified script SHA-256: `06ca2cbe6eae66cf7e8e16799cbdd700f68d863a8878ee2dff398477d8840475`.
- Verified result SHA-256: `382898ef389f9aa368ca6fed5933d5a859dac06dfb9541ca5b6fc16edacc9715`.
- Read the verification artifact and confirmed **108 checks, all passing**.
- Confirmed the final runtime records restored historical `microdf-python==1.5.12`, no installed current wrapper, and the unsuccessful current-wrapper loading attempt as a disclosed limitation.
- Rechecked the exact strict, broad and additional household-member totals above, and their household-level and resident-level disjointness. The headline metrics remain unchanged.

No further actionable code, arithmetic or scope findings remain for this preliminary historical-output postprocessor. This approval does not extend its coverage to untested workers, job entry, a continuous earnings range, or a final population estimate.

STATUS: complete; APPROVE.
