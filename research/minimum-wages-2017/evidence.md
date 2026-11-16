# 2017 minimum-wage input audit

This file documents general, non-tipped adult hourly wage facts for the 50 states and DC. The accompanying `wages.json` uses January 1, 2017 as a reference date and assumes FLSA-covered employment with no newly offered employer health coverage. It does **not** authorize an unqualified national legal-minimum-wage scenario. The data contain one unresolved effective-date issue, several employer/region choices, and no exhaustive local-wage audit.

## Sources and checks

The baseline comes from the [DOL historical table](https://beta.dol.gov/policy-regulations/pay-benefits/wages-hours/state-laws/minimum-wage/history), 2014–2019 section, 2017 column. Direct requests returned HTTP 403. Search retrieval returned the complete parsed table, saved in `dol-history-retrieval.txt`; the same source was retrieved in the job-pilot research. We cross-checked its rates against the contemporaneous [Hawaii government Data Book 2016, Table 12.43](https://files.hawaii.gov/dbedt/economic/databook/db2016/section12.pdf), PDF pages 57–58. That table explicitly reproduces DOL's January 1, 2017 state table, accessed January 5, 2017.

The [dated DOL January 1, 2017 tipped-wage table](https://www.dol.gov/agencies/whd/state/minimum-wage/tipped/2017) supplies the combined full minimum wage, rather than only the tipped cash wage, for most states and includes employer-size footnotes. It also identifies states requiring the full minimum before tips. We use its full-rate and coverage information to corroborate the general wage facts; no tipped cash rate enters the hypothetical job.

The federal covered-job floor is $7.25. States with no minimum wage, or a lower state rate, therefore use $7.25 for this particular FLSA-covered hypothetical job. This does not claim the same floor for every FLSA-exempt worker.

## Corrections and choices

- **DC:** Reject the DOL history table's malformed 2017 value of $17.00. A [DC wage-and-hour notice](https://does.dc.gov/sites/default/files/dc/sites/does/page_content/attachments/DC%20Minimum%20Wage%20Increase%20-%20DC%20Register%20Public%20Notice_1.pdf), page 1, verifies $11.50 before July 1, 2017 and $12.50 from July 1. The Jan 1 reference uses $11.50. A full calendar-year wage path needs the July increase.
- **California:** The [state history table](https://www.dir.ca.gov/iwc/MinimumWageHistory.htm) verifies $10.50 for employers with 26 or more employees and $10.00 for 25 or fewer. The DOL history headline of $10.00 selects the smaller-employer category. The JSON exposes both and leaves `reference_hourly` unset until the employer convention is selected.
- **New York:** The [state's detailed history](https://dol.ny.gov/history-minimum-wage-new-york-state) verifies rates from December 31, 2016: NYC $11.00 for 11 or more employees and $10.50 for 10 or fewer; Nassau/Suffolk/Westchester $10.00; rest of state $9.70. Fast-food categories are higher and separate. The general rest-of-state amount is not locally compliant everywhere. The JSON retains the variants; December 31, 2017 changes are not part of a frozen Jan 1 scenario.
- **Oregon:** The [BOLI schedule](https://www.oregon.gov/boli/workers/Pages/minimum-wage-schedule.aspx) verifies the July 2016 rates applicable on Jan 1: standard $9.75, Portland Metro $9.75, nonurban counties $9.50. From July 1, 2017 these become $10.25, $11.25, and $10.00. Portland's urban-growth-boundary classification can require finer geography than a county. The JSON exposes all six dated variants.
- **Nevada:** [Official 2016](https://www.business.nv.gov/news-media/press-releases/2016/labor/nevada-s-minimum-wage-and-daily-overtime-rates-remain-flat-in-2016/) and [2017 releases](https://www.business.nv.gov/news-media/press-releases/2017/labor/nevada-s-minimum-wage-and-daily-overtime-rates-will-not-increase-in-2017/) verify unchanged $8.25 without qualifying employer health benefits and $7.25 with such benefits. The no-new-health-coverage job scenario requires $8.25. The [2017 annual bulletin](https://labor.nv.gov/uploadedFiles/labornvgov/content/About/Forms/2017%20Annual%20Bulletin%20-%20Minimum%20Wage.pdf) independently confirms the categories.
- **Minnesota:** The [state legislature's 2014 law summary](https://www.house.mn.gov/hinfo/leginfo/0814nlrelease.pdf) and the DOL dated table verify $9.50 for large employers and $7.75 for smaller employers from August 2016. Large means annual sales/business of at least $500,000. The Hawaii table's small-employer footnote still says $7.25; that stale footnote is rejected in favor of the state schedule and the dated DOL table.
- **Ohio:** The [Ohio Legislative Service Commission's December 2016 analysis](https://www.legislature.ohio.gov/download?format=pdf&key=6102), printed page 33 and footnote 106, verifies the Jan 1, 2017 general rate of $8.15 and the $7.25 category for businesses below $299,000 in gross annual receipts. Both remain explicit variants.
- **Montana:** The [state minimum-wage history](https://erd.dli.mt.gov/labor-standards/wage-and-hour-payment-act/minimum-wage-history) verifies $8.15 for 2017 and the small-business state-law exception of $4.00 for annual sales of $110,000 or less. The dated DOL table explains that individual FLSA coverage can raise the applicable wage to the federal rate. The JSON uses $7.25 for that FLSA-covered lower category.
- **Maine remains unresolved for a strict Jan 1 convention.** The contemporaneous [Maine DOL release](https://www.maine.gov/labor/Templates/news_template.shtml?id=727132) and [2017 official poster packet](https://www.maine.gov/mdot/contractors/projects/2017/2017civilrightswholepacket/2017fullpacket.pdf) make the $9.00 increase effective January 7. DOL's dated table and the Hawaii republication explicitly note Jan 7. The earlier rate was $7.50. However, the [codified statutory text](https://president.maine.gov/legis/statutes/26/title26sec664.html) says January 1. The JSON records $7.50 as the tentative Jan 1 amount, $9.00 from Jan 7, and `verified:false` until that date convention is resolved. A clearly labeled Jan 7 reference-date scenario would avoid this particular ambiguity.

## Readiness

The matrix contains all 51 jurisdictions and source-supported general rate facts; it deliberately keeps null `reference_hourly` values where selecting a region or employer category would otherwise be implicit. The `amount` field is a documented category's headline, **not** a safe fallback for every null reference.

Before a national job-entry calculation:

1. Choose the hypothetical employer's size/coverage convention. California, Minnesota, Montana, Ohio, Arkansas, Illinois, Nebraska, Michigan, Vermont and West Virginia need explicit treatment. A specified large, state-covered employer is one possible benchmark; it is an analyst assumption.
2. Choose New York and Oregon work-region mappings, or explicitly label a state-reference wage scenario. Residence geography and work geography are not identical.
3. Resolve Maine's Jan 1/Jan 7 reference. Do not silently fill it with $9.00 under a Jan 1 label.
4. State that local floors and special industries are excluded, or audit and implement them.
5. Decide between freezing Jan 1 rates for an annualized benchmark and applying the actual within-year path. DC and Oregon change July 1; Maryland and New York also have within-year changes to address if using the latter convention.

No new policy computations or simulations were run. `metadata.national_run_ready` is false.

## Oregon refinement for a frozen Jan 1 scenario

The [statute itself](https://www.oregonlegislature.gov/bills_laws/ors/ors653.html), ORS 653.025–653.026, retains the dated 2016/2017 rates and the nonurban-county definition enacted in 2016. On Jan 1 the Portland Metro and standard rates are both $9.75. Therefore county classification is sufficient for that frozen-date scenario: the 18 named nonurban counties receive $9.50 and every other county receives $9.75. The finer urban-growth-boundary distinction matters after July 1. The JSON includes the 18 county names. Assuming job location equals residence county remains an analyst choice.
