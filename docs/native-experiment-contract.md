# Native-law experiment interfaces

The experiment interfaces separate the policy year from the price year. They target 2017 law on a recent reference population. Callers convert 2025-dollar money inputs to native 2017 units before construction; the account reports outputs in 2025 dollars. The current modules provide account and price-reform factories; they do not construct or qualify a real-engine run.

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

## Real-engine requirements

The remaining adapter must preserve explicit monthly vectors and household structure, bind the runtime and reference preparation, and enforce the price-input restrictions. For Medicare income-related premiums, it must evaluate the existing two-year-prior income imputation once on the unperturbed native baseline and freeze that benefit-year input across branches. That input represents model-imputed history.

Synthetic tests exercise account arithmetic, currency conversion, native-age preservation and refusal paths with fake APIs. They also demonstrate the limits of a static context receipt and an unenforced input denylist. Real-engine compatibility, historical input preparation, health-price anchors and population estimates require separate validation.
