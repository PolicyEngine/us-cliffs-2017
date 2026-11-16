# Policy-date audit provenance

`summary.json` records counts of parameter nodes read by the frozen model. The
2017 recount uses the archived audit CSV. The bounded 2025 trace samples two
households per state/DC jurisdiction and compares traced and untraced cliff
flags and gaps. It writes parameter metadata and sample sizes only.

A node can contain several leaves. The later-start classifier counts a node
when any leaf's earliest raw value falls after the cutoff. These counts do not
measure the share of laws, inaccurate values, or households affected. A first
raw date does not establish when the law changed. Programs can be gated off
even when the model reads their future-start parameters.

`future-history-2025.json` retains the 139 flagged parameter names, raw dates,
and earliest read dates from the completed trace. `source-hashes.json` identifies
the original inputs, audited sources, executed probe, and complete metadata
trace. The complete trace is unnecessary for the paper package and is omitted.
No survey records, IDs, weights, correspondence, or private paths appear here.

Recount 2017 from the repository root without loading the model:

```sh
python3 paper/inputs/policy-date-audit/recount_2017.py --check
```

To repeat the bounded 2025 trace, first prepare the paper's exact frozen
simulation environment and source checkout. Use a suitable resource guard and
an output directory outside the source package:

```sh
"$HEAVY_RUN" policy-date-probe .venv/bin/python \
  paper/inputs/policy-date-audit/probe_2025.py --output "$AUDIT_OUTPUT"
```

The portable adapter discovers the repository root and accepts an output path;
it retains the completed probe's sample, model calls, and classifications.
It additionally rejects mismatched model versions or public input hashes.
Its syntax and metadata logic were checked without repeating the model run.
`source-hashes.json` distinguishes the adapter from the source that generated
the archived counts. `manifest.json` hashes every file in this directory except
itself.
