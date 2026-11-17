# Native-law experiment interfaces

The experiment interfaces separate the policy year from the price year. They target 2017 law on a recent reference population. Callers convert 2025-dollar money inputs to native 2017 units before construction; the account reports outputs in 2025 dollars. The modules provide account, price, managed-input and branch-integrity interfaces. The runtime bridge composes these interfaces; native execution still requires qualified reference inputs, health unit values and integration checks.

The `any_raise` table combines the discrete $1,000, $2,000 and $5,000 real-2025 raise scenarios. It counts each person flagged under at least one tested raise, then combines the job-entry flags through the household mapping. Its additional group excludes every household with a strict loss under any tested raise or job entry.

## Resource account

`AccountSpec` requires explicit nonhealth benefits, net government health components and runtime, input-preparation and price identities. `make_account_reform` registers two household accounts:

```text
C0 = market income + nonhealth benefits + refundable credits
     - tax before refundable credits - premium tax credit
G  = C0 + premium tax credit + net government health benefits
```

The government-transfer account counts the used premium tax credit once. It retains CHIP's net government cost and subtracts no additional marketplace or CHIP premium. `GovernmentTransferAccount` requests the managed household or person projection and converts native 2017 money to 2025 dollars once.

## Fixed reference prices

`make_reference_benchmark_reform` reads the model's 2025 silver and bronze base-premium tables and multiplies those prices by the 2017-to-2025 consumer-price ratio. It replaces only the two base-premium variables, leaving native 2017 age, family and credit rules in place. This convention does not supply observed 2017 premiums.

A caller must reject stored derived-price inputs before construction, qualify geography and freeze unmasked health unit values across earnings branches. The account checks the context that its caller returns; the caller must check current model and price state after mutations. A constructor receipt cannot detect later changes by itself.

The reference capture reads unmasked Medicaid, CHIP and Medicare unit values once on the full prepared 2025 sample. It converts those unit inputs to native money once and retains native enrollment and Medicare premium rules across earnings branches. It does not replace the native premium parameters.

## Native input and branch checks

The managed adapter preserves explicit monthly vectors, household structure and declared runtime identities. The materializer requires source dispositions for supplied fields and separate declarations for pre-2017 lookbacks; it never fills missing history with zeros. The live witness checks selected formula objects, parameter values and frozen supplied inputs before account reads and after branches.

For Medicare income-related premiums, the materializer evaluates the existing two-year-prior income imputation once on the unperturbed native baseline and freezes that benefit-year input across branches. That input represents model-imputed history.

`WageBenchmark` supplies January 7, 2017 state and regional rates for a hypothetical adult job at a large covered employer. It assumes residence equals workplace and excludes local ordinances, special-industry rates and later changes within 2017. NY and OR county checks select regional rates; callers retain the weighted person projection.

## Paired uncertainty

An optional contribution sink collects each metric through the maintained household mapping and `MicroSeries.weight()` interface. The resulting ledger applies survey weights once. Source-household clusters keep support clones together, and every scenario and cutoff uses the same resampling draws. The intervals condition on fixed calibration weights and model inputs; they do not cover survey design, imputation, calibration-fit or policy-encoding uncertainty.

## Real-engine requirements

The current adapter requires the native-period argument from [wrapper PR761](https://github.com/PolicyEngine/policyengine.py/pull/761) at `8ab66b5`; released wrapper 6.20.2 lacks that argument. The proposed country target uses commit `5b186949`, Core 3.36.0 and SPM 1.1.0. The historical source contract, actual reference health-unit capture and native integration checks still need completion. Synthetic checks of the bridge and health interfaces do not establish those results.

Synthetic tests exercise account arithmetic, input transport, currency conversion, native-age preservation, current-state checks and refusal paths with fake APIs. They do not establish real-engine compatibility or population results.
