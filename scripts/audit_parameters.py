"""List the parameters a target-year cliff run reads that have no value for that year.

Runs the cliff calculation (with health benefits counted, so health program
rules are read too) on a state-stratified sample of the target-year dataset,
records every parameter the formulas read through policyengine-core's
parameter tracing, and compares each with the raw parameter files.
PolicyEngine-US copies each parameter's earliest value back to 2015, so a
parameter whose raw history starts after the target year's first day takes
a later year's value in the run.

Usage: python scripts/audit_parameters.py 2017 40 > results/parameters_read_2017.csv
       (40 = households sampled per state)
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from huggingface_hub import hf_hub_download
from policyengine_core.parameters import ParameterNode
from policyengine_core.reforms import Reform
from policyengine_core.tracers import SimpleTracer

import policyengine_us
from policyengine_us import CountryTaxBenefitSystem, Microsimulation
from policyengine_us.data.dataset_schema import USSingleYearDataset

sys.path.insert(0, ".")
from cliffs2017.deflate import deflate  # noqa: E402


class ParameterRecorder(SimpleTracer):
    """A tracer that keeps only the names and instants of parameters read."""

    def __init__(self):
        super().__init__()
        self.reads = {}

    def record_parameter_access(self, parameter, period, branch_name, value):
        key = str(parameter)
        first = self.reads.get(key)
        period = str(period)
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
    reform = Reform.from_dict(
        {"gov.simulation.include_health_benefits_in_net_income": {"2000-01-01.2100-12-31": True}},
        country_id="us",
    )
    sim = Microsimulation(dataset=dataset, reform=reform, dataset_end_year=target)
    sim.trace = True
    recorder = ParameterRecorder()
    sim.tracer = recorder
    sim.calculate("is_on_cliff", target)
    raw_root = ParameterNode(directory_path=Path(policyengine_us.__file__).parent / "parameters")
    cutoff = f"{target}-01-01"
    rows = []
    for name, first_read in sorted(recorder.reads.items()):
        node = raw_lookup(raw_root, name)
        if node is None:
            rows.append(dict(parameter=name, first_read=first_read, status="not in raw files"))
            continue
        firsts = [leaf.values_list[-1].instant_str for leaf in leaves(node) if leaf.values_list]
        if not firsts:
            rows.append(dict(parameter=name, first_read=first_read, status="no values"))
            continue
        late = [f for f in firsts if f > cutoff]
        rows.append(
            dict(
                parameter=name,
                first_read=first_read,
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
        + ", ".join(f"{k}: {v}" for k, v in out.status.value_counts().items()),
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
