"""List the parameters a target-year cliff run reads that have no value for that year.

Runs the cliff calculation with the target year's reforms (health benefits
counted, so health program rules are read too, and before 2018 the
ACABefore2018 premium tax credit) on a state-stratified sample of the
target-year dataset, records every parameter the formulas read through
policyengine-core's parameter tracing, and compares each with the raw
parameter files. ``later_reads`` lists any instant after the target year at
which a formula reads the parameter, such as a state rule that fixes the
federal parameters of a later year.

Core's tracer misses two kinds of read, and ``traced_reads`` adds both for
the run inside it:

- scales: the tracer records a read only when the child is a node, an array
  or a scalar, so it misses bracket scales, which formulas read with
  ``.calc`` (age curves, state income tax rates);
- reads by path: a formula that writes ``parameters.gov.X(instant)`` instead
  of ``parameters(instant).gov.X`` reaches the raw parameter tree, which
  records nothing. In PolicyEngine-US, for example, the federal EITC,
  several state EITCs, Virginia TANF and SNAP's emergency allotments read
  parameters this way.

Each read is logged under the parameter's own name. The script then runs the
same cliff calculation without tracing and stops unless every person's cliff
flag and cliff gap match, so the extensions change no value.

PolicyEngine-US copies each parameter's earliest value back to 2015, so a
parameter whose raw history starts after the target year's first day takes
a later year's value in the run.

Usage: python scripts/audit_parameters.py 2017 40 > results/parameters_read_2017.csv
       (40 = households sampled per state)
"""

import sys
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pandas as pd
from huggingface_hub import hf_hub_download
from policyengine_core import periods
from policyengine_core.parameters import Parameter, ParameterNode, ParameterScale
from policyengine_core.taxscales import TaxScaleLike
from policyengine_core.tracers import SimpleTracer
from policyengine_core.tracers import tracing_parameter_node_at_instant as tracing

import policyengine_us
from policyengine_us import CountryTaxBenefitSystem, Microsimulation
from policyengine_us.data.dataset_schema import USSingleYearDataset

sys.path.insert(0, ".")
from cliffs2017.deflate import deflate  # noqa: E402
from cliffs2017.simulation import reforms  # noqa: E402


class TracedLeaf:
    """A parameter or scale a formula reached by path (``parameters.gov.X``).

    Calling it at an instant records the read under the parameter's own name
    and returns the value unchanged. Every other attribute comes from the
    wrapped parameter.
    """

    def __init__(self, leaf, tracer, branch_name):
        self.leaf = leaf
        self.tracer = tracer
        self.branch_name = branch_name

    def __call__(self, instant):
        return self.get_at_instant(instant)

    def get_at_instant(self, instant):
        value = self.leaf.get_at_instant(instant)
        period = str(periods.instant(instant))
        self.tracer.record_parameter_access(self.leaf.name, period, self.branch_name, value)
        return value

    def __getattr__(self, key):
        return getattr(tracing._wrapped(self, "leaf", key), key)

    def __getitem__(self, key):
        return self.leaf[key]


@contextmanager
def traced_reads():
    """Make core's parameter tracing also log scales and reads by path."""
    at_instant = tracing.TracingParameterNodeAtInstant
    node = tracing.TracingParameterNode
    saved = at_instant.get_traced_child, node.__getattr__
    original_child = saved[0]

    def get_traced_child(self, child, key):
        if isinstance(child, TaxScaleLike) and isinstance(key, str):
            parent = self.parameter_node_at_instant
            name = ".".join([parent._name, key])
            self.tracer.record_parameter_access(name, parent._instant_str, self.branch_name, child)
        return original_child(self, child, key)

    def path_getattr(self, key):
        child = getattr(tracing._wrapped(self, "parameter_node", key), key)
        if isinstance(child, ParameterNode):
            return node(child, self.tracer, self.branch_name)
        if isinstance(child, (Parameter, ParameterScale)):
            return TracedLeaf(child, self.tracer, self.branch_name)
        return child

    at_instant.get_traced_child = get_traced_child
    node.__getattr__ = path_getattr
    try:
        yield
    finally:
        at_instant.get_traced_child, node.__getattr__ = saved


class ParameterRecorder(SimpleTracer):
    """A tracer that keeps only the names and instants of parameters read.

    ``reads`` maps each name to the earliest instant read, ``instants`` to
    every instant read.
    """

    def __init__(self):
        super().__init__()
        self.reads = {}
        self.instants = {}

    def record_parameter_access(self, parameter, period, branch_name, value):
        key = str(parameter)
        period = str(period)
        self.instants.setdefault(key, set()).add(period)
        first = self.reads.get(key)
        if first is None or period < first:
            self.reads[key] = period


def stratified(dataset, per_state, seed=0):
    rng = np.random.default_rng(seed)
    household = dataset.household
    picks = []
    for _, group in household.groupby("state_fips"):
        n = min(per_state, len(group))
        picks.extend(rng.choice(group.household_id.to_numpy(), n, replace=False))
    keep = set(picks)
    person = dataset.person[dataset.person.person_household_id.isin(keep)]

    def members(frame, id_column, person_column):
        return frame[frame[id_column].isin(set(person[person_column]))]

    return USSingleYearDataset(
        person=person,
        household=household[household.household_id.isin(keep)],
        tax_unit=members(dataset.tax_unit, "tax_unit_id", "person_tax_unit_id"),
        spm_unit=members(dataset.spm_unit, "spm_unit_id", "person_spm_unit_id"),
        family=members(dataset.family, "family_id", "person_family_id"),
        marital_unit=members(dataset.marital_unit, "marital_unit_id", "person_marital_unit_id"),
        time_period=int(dataset.time_period),
    )


def raw_lookup(raw_root, name):
    node = raw_root
    for part in name.split("."):
        children = getattr(node, "children", None)
        if children is None or part not in children:
            return None
        node = children[part]
    return node


def leaves(node):
    if hasattr(node, "values_list"):
        yield node
        return
    for child in getattr(node, "children", {}).values():
        yield from leaves(child)
    for bracket in getattr(node, "brackets", []) or []:
        yield from leaves(bracket)


def main():
    target = int(sys.argv[1])
    per_state = int(sys.argv[2])
    system = CountryTaxBenefitSystem()
    path = hf_hub_download(
        "policyengine/populace-us",
        "populace_us_2024.h5",
        repo_type="dataset",
        revision="populace-us-2024-spm-20260909",
    )
    sample = stratified(USSingleYearDataset(path), per_state)
    dataset, _ = deflate(sample, system, target)

    def simulation():
        return Microsimulation(
            dataset=dataset,
            reform=reforms(health=True, aca_before_2018=target < 2018),
            dataset_end_year=target,
        )

    checked = ("is_on_cliff", "cliff_gap")
    with traced_reads():
        sim = simulation()
        sim.trace = True
        recorder = ParameterRecorder()
        sim.tracer = recorder
        traced = {v: sim.calculate(v, target).values for v in checked}
    untraced = simulation()
    same = all(np.array_equal(traced[v], untraced.calculate(v, target).values) for v in checked)
    print(f"# cliff flags and gaps match a run without tracing: {same}", file=sys.stderr)
    if not same:
        sys.exit("tracing changed the results")
    raw_root = ParameterNode(directory_path=Path(policyengine_us.__file__).parent / "parameters")
    cutoff = f"{target}-01-01"
    next_year = f"{target + 1}-01-01"
    rows = []
    for name, first_read in sorted(recorder.reads.items()):
        later = ";".join(sorted(i for i in recorder.instants[name] if i >= next_year))
        node = raw_lookup(raw_root, name)
        if node is None:
            rows.append(dict(parameter=name, first_read=first_read, later_reads=later, status="not in raw files"))
            continue
        firsts = [leaf.values_list[-1].instant_str for leaf in leaves(node) if leaf.values_list]
        if not firsts:
            rows.append(dict(parameter=name, first_read=first_read, later_reads=later, status="no values"))
            continue
        late = [f for f in firsts if f > cutoff]
        rows.append(
            dict(
                parameter=name,
                first_read=first_read,
                later_reads=later,
                status="later start" if late else "covered",
                leaves=len(firsts),
                leaves_starting_after=len(late),
                earliest_start=min(firsts),
                latest_start=max(firsts),
                unit=(getattr(node, "metadata", {}) or {}).get("unit"),
            )
        )
    out = pd.DataFrame(rows)
    out.to_csv(sys.stdout, index=False)
    print(
        f"# {len(out)} parameters read; "
        + ", ".join(f"{k}: {v}" for k, v in out.status.value_counts().items())
        + f"; also read at an instant after {target}: {(out.later_reads != '').sum()}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
