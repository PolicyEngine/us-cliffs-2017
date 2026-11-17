# Synthetic native-period packets

`cliffs2017.native_periods.build_period_packet` compiles explicitly supplied
synthetic inputs into immutable variable → period → tuple mappings. It imports no
engine and loads no population. A packet supplies input declarations; it cannot
qualify a runtime, dataset or scientific comparison.

Supply complete reference-currency input blocks as a sequence of `(year, values)`
pairs. The compiler calls the existing `to_native_inputs` converter once per block
and retains its exact fractions, units, dropped-field receipt and named
background/calendar scopes. Also supply an `InputContract`, `PriceBasis`, explicit
law year and history-year list, variable schema and separate `fixed_facts`
snapshot. The schema maps every name to `(entity, definition_period)`; the caller
declares it without claiming a validated export of the model's live input contract.

Declare all six entity counts, unique eternal entity IDs and explicit eternal
person membership/role vectors. Memberships must reference declared group IDs.
The compiler preserves role labels but does not check them against engine roles.
Every retained nonmonetary fact must match the separately supplied snapshot in
value and scalar type across all blocks. This includes declared ages, original
weights, geography, take-up flags and retained calendar facts. The compiler changes
no dates and rescales no weights. It rejects undeclared fields, wrong vector sizes,
conflicting topology, duplicate year bindings and missing or extra history blocks.

Annual blocks bind to `YYYY`; monthly blocks require twelve explicit month vectors
and bind to `YYYY-MM`. Eternal facts bind once to `eternity`. The compiler does not
spread annual money across months or infer lookback inputs. Supply reference-2025
amounts for each requested year; the compiler converts each block using that
year's price factor. This limited convention refuses pre-2017 history. Review a
separate contract before applying an instantaneous earnings shock, steady-state
shock or different history-price convention to real inputs.

The compiler supports period identity for 2017–2026 and monetary blocks for
2017–2025. The [published annual-average price file](price_basis.csv) ends in 2025.
The compiler refuses 2026 money even if a caller supplies an extra index.
Fact-only 2026 synthetic fixtures use an explicit hypothetical index to exercise
period identity. They supply no price measurement. The compiler performs no engine
float conversion, statutory rounding or parameter rebasing.

When fixed age accompanies a recognized birth fact on any entity, the compiler
requires a named hold/drop disposition. That declaration does not enforce a hold
on model formulas: the engine can derive birth year from policy year minus fixed
age. Review cohort-sensitive consumers, mortgage treatment, Social Security
background payments and health valuation separately before native execution.

The [counterfactual protocol](counterfactual-protocol.md) proposes one recent
reference population prepared once for 2025, fixed household characteristics and
native historical law, expressed in common 2025 dollars. It excludes actual 2017
incidence. Synthetic tests assert period identity, exact rational currency round
trips, fixed topology, immutability and refusal cases through the fixed
import-blocking runner, alongside the existing currency tests. They cannot
validate constructor migrations, live variable semantics, structural reforms,
managed-model admission, common unmasked health prices, reference-cohort choice,
drift, certification or population estimates. Preserve the existing wrapper,
Microcosm, source-parent, study and publication holds.
