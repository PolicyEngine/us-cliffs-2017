# Combined raise and job-entry union, 2017 rules

`scripts/expanded_combined_union.py` counts the people in households that trip
the raise test, the job test, or either, under 2017 federal rules, counting each
person once. Results: `results/expanded_combined_union_2017.json`.

## The tests and sets

- **Raise test.** A current worker among the household's two highest-earning
  adults gets a $1,000, $2,000 or $5,000 raise, one adult at a time. The rows are
  the saved raise experiment that `scripts/expanded_raise_union.py` reads.
- **Job test.** A working-age adult with no earnings takes a full-time job at the
  state's 2017 minimum wage, one adult at a time (`EXPANDED_JOB_ENTRY.md`).

A household trips a test at threshold t when any tested adult's household keeps
strictly less than t of the gross change: the change in household resources
divided by the gross pay change, for t = 0.6, 0.5, 0.2 and 0. The job runner
counts `d < t x pay`; the union counts `d / pay < t`, as the raise union does, and
checks that the two give the same sample counts at every threshold.

The sets are `raise_1000`, `raise_2000`, `raise_5000`, `raise_union` (the three
raises), `job`, `combined` (raise union and job) and `combined_1000` ($1,000 raise
and job). For each set, threshold and resource measure (with and without health
coverage, as the raise union defines them) the JSON gives households, flagged
adults and household members.

For each set:

- the **strict-loss group** is the households below 0% on any test in the set;
- the **additional group** is the households below 50% on any test in the set,
  excluding every household below 0% on any test in the set;
- the **below-half total** is the households below 50% on any test in the set.

Each is its own household set, mapped to residents with `map_to="person"`; none is
a difference of counts. For `combined` and `combined_1000`, `added_by_job` counts
the households in the set but not in its raise-only counterpart. The overlap
section compares the original 6.2 million group (all tested adults, $1,000 raise,
with health) with each union's strict and below-half sets.

## How it counts

No tax or benefit formula runs. Each of the frozen experiment's four household
parts loads its historical simulation only for the entity mapping and the
calibrated weights. The saved changes become analysis flags in that simulation,
and MicroSeries sums them; stored weight columns are never read. Per-source-household
totals for the intervals come from `MicroSeries.groupby(...).sum()` on the same
flags.

Job coverage comes from the job-entry records and plans, not from wages.json. A
wage scope counts only when every part has its plan and a validated record for
every planned rank, and a jurisdiction counts as covered only when its tested rows
equal the plans' count of its candidates in all four parts. Every other
jurisdiction is deferred, and the JSON's status is
`preliminary_partial_jurisdictions` while any is. Later scopes, such as Maryland
and New York's `states-MD-NY`, enter with no code change; `--scopes` limits a run
to named scopes.

## Invariants

Every part stops unless all of these hold, and the tests check each on random
synthetic households against a brute-force count:

1. Thresholds nest at household level: below 0% within below 20% within below 50%
   within below 60%.
2. Each union contains each of its components, and its count lies between the
   largest component's and their sum.
3. The strict and additional groups are disjoint and together equal the below-half
   union, in households and in residents.
4. Each person is counted at most once: person IDs and rows are unique, residents
   map to 0 or 1, flagged adults live in flagged households, and no raise worker is
   also a job candidate.
5. With the job rows emptied, `combined` equals `raise_union` and `combined_1000`
   equals `raise_1000`, and the recount reproduces
   `results/expanded_raise_union_2017.json` in every part and nationally.
6. The job rows reproduce the job runner's own per-rank totals: weighted candidates
   tested, weighted members of touched households, and the sample counts below
   each threshold.
7. Adding a test never lowers the strict or below-half union.

The national totals add the parts in part order, as the raise union did, so the
reproduction is exact.

## Intervals

The 95% intervals are percentiles over 5,000 resamples of all 47,277 source
households jointly, with the same draw for every count, as
`scripts/driver_intervals.py` resamples (seed 0). A survey household and its clone
share a source household and always fall in the same part.

## Running it

The parts run on Modal, one container per household part. Inputs ship as bytes,
each checked against the manifest's SHA-256; the code is checked against the
launching commit. Results are keyed by the manifest digest and installed without
overwriting, so a relaunch resumes.

```sh
MODAL_PROFILE=policyengine modal run scripts/modal_combined_union.py \
    --job-root PATH --raise-rows-root PATH [--scopes resolved]
python scripts/expanded_combined_union.py combine --digest DIGEST
```

`--job-root` is a checkout that holds the git-ignored `results/job_entry/`, and
`--raise-rows-root` one that holds the raise experiment's
`results/parts/per_person/` rows. The part records and per-source-household totals
stay in `results/combined_union/`, which git ignores.
