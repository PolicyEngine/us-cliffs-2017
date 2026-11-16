# Independent job-entry pilot review

Reviewed 11 November 2026 by the separate methods-audit agent. The reviewer read
`scripts/expanded_job_entry.py` and `tests/test_expanded_job_entry.py` end to end
after the household-projection cache fix.

**PASS: no remaining actionable numerical or scope bug identified.**

The reviewer checked that candidate ranks cover all eligible adults; the
historical hourly wage times 2,080 agrees with the new earnings; unemployment
and work-time inputs agree with the full-year wage-job scenario; health resources
match the inherited premium-tax-credit-counted-once measure; and each reused
household projection clears its dependent cache.

The input-based sample selection checks college-student status, while final
model eligibility checks full-time-student status. The final eligibility check
prevents excluded students from entering the test. The reviewer accepted the
result-field name `microseries_mapping_verified`, which describes the checked
mapping types without implying that this selected sample yields national totals.

The executable pilot additionally checks zero-change identity, a fresh simulation
of the changed inputs, unchanged WIC take-up draws, untouched households, complete
candidate coverage, nested retention groups and valid household unions.

Limits remain explicit: nine selected households in three states; no population
inference; no complete national wage schedule; no full job-entry/raise overlap;
no new childcare-cost or SSDI-cutoff estimate. No national simulation or cloud
launch was requested in this pilot.
