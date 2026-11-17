"""Source and raw-input witnesses for one prepared native raise pilot.

No model, data or statistics imports run here. The caller supplies the actual
managed tools and Core input methods after authenticating their sources.
"""

from dataclasses import fields
from fractions import Fraction
import hashlib
import importlib.metadata as metadata
import inspect
import json
import math
from pathlib import Path
import sys

from .commissioned import CANDIDATE, PERSON_FLAG
from .managed_native import ENTITIES, RuntimeBinding, role_transport_from_entities
from .native_materializer import input_digest, topology_inputs


class ObservationError(ValueError):
    """Current source, supplied facts or the exact pilot shock differs."""


TAKEUP_INPUTS = frozenset(
    {
        "takes_up_medicare_if_eligible",
        "takes_up_wic_if_eligible",
        "takes_up_head_start_if_eligible",
        "takes_up_ssi_if_eligible",
        "takes_up_medicaid_if_eligible",
        "takes_up_housing_assistance_if_eligible",
        "takes_up_tanf_if_eligible",
        "takes_up_snap_if_eligible",
        "takes_up_eitc",
        "takes_up_aca_if_eligible",
    }
)
CORE_NAMES = frozenset({"_get_set_input_periods", "_get_recorded_input_array"})
STRUCTURAL_ROLES = frozenset(
    f"person_{entity}_role" for entity in ENTITIES - {"person"}
)
SOCIAL_SECURITY_SOURCES = frozenset(
    {
        "social_security_retirement",
        "social_security_disability",
        "social_security_survivors",
        "social_security_dependents",
    }
)


def _source_chain(method):
    result = []
    while method is not None:
        source = inspect.getsourcefile(method)
        if source is None:
            raise ObservationError("A loaded source method has no authenticated file")
        result.append(_sha(source))
        method = getattr(method, "__wrapped__", None)
    return result


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _document(value):
    if isinstance(value, Fraction):
        return ["fraction", value.numerator, value.denominator]
    if isinstance(value, dict):
        return {key: _document(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_document(item) for item in value]
    return value


def _digest(value):
    return hashlib.sha256(
        json.dumps(
            _document(value), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _signature(array):
    if array is None or hasattr(array, "weights"):
        raise ObservationError("Use surviving raw Core inputs, not weighted series")
    shape = tuple(array.shape)
    if len(shape) != 1:
        raise ObservationError("Raw supplied inputs require one-dimensional vectors")
    payload = (
        input_digest(array.tolist())
        if array.dtype.kind == "O"
        else hashlib.sha256(array.tobytes(order="C")).hexdigest()
    )
    return str(array.dtype.str), shape, payload


class NativeObservers:
    def __init__(
        self,
        config,
        *,
        contract,
        specs,
        registry,
        tools,
        core_methods,
        holder_to_array,
        mode="native",
        metadata_api=None,
    ):
        if set(core_methods) != CORE_NAMES or mode not in {"native", "synthetic_test"}:
            raise ObservationError("Use the two authenticated Core3.36 input methods")
        if metadata_api is not None and mode != "synthetic_test":
            raise ObservationError(
                "Native identity reads the actual installed metadata"
            )
        self.config, self.contract, self.specs, self.registry = (
            config,
            contract,
            specs,
            registry,
        )
        self.tools, self.core_methods, self.holder_to_array = (
            tools,
            dict(core_methods),
            holder_to_array,
        )
        self.mode, self.metadata = (
            mode,
            metadata if metadata_api is None else metadata_api,
        )
        self.plan = self._baseline = self._snap = None
        self._precision = {"status": "UNRUN", "zero_tolerance": True}
        self.role_keys = None
        self._runtime_receipt = None
        self._reference_receipt = None
        self._binding_receipt = None
        self._helper_globals = tools.create_branch.__globals__
        self._pre_response = dict(self._helper_globals["PRE_RESPONSE_INPUTS"])
        self._held = set(self._helper_globals["HELD_BEHAVIORAL_RESPONSE_VARIABLES"])
        self._supplied = self._helper_globals["user_set_variables"]
        if mode == "native":
            expected_sources = config["source_hashes"]
            objects = [
                (
                    tools.create_branch,
                    "policyengine_us/variables/household/marginal_tax_rate_helpers.py",
                ),
                (
                    tools.split_raise,
                    "policyengine_us/variables/household/marginal_tax_rate_helpers.py",
                ),
                (holder_to_array, "policyengine_core/holders/holder.py"),
            ]
            for method, relative in objects:
                source = inspect.getsourcefile(method)
                if source is None or _sha(source) != expected_sources[relative]:
                    raise ObservationError(
                        "Actual native helper/input-method source differs"
                    )
            expected_chain = [
                expected_sources["policyengine_us/tools/social_security_inputs.py"],
                expected_sources["policyengine_core/simulations/simulation.py"],
            ]
            if any(
                _source_chain(method) != expected_chain
                for method in core_methods.values()
            ):
                raise ObservationError(
                    "Use actual CountrySSA wrappers over authenticated Core originals"
                )

    def observe_runtime(self):
        expected = self.config["runtime_identity"]
        packages = []
        for dist in self.metadata.distributions():
            root = Path(dist._path)
            item = {
                "name": dist.metadata["Name"],
                "version": dist.version,
                "metadata_sha256": _sha(root / "METADATA"),
            }
            if (root / "direct_url.json").is_file():
                item["direct_url"] = json.loads((root / "direct_url.json").read_text())
            packages.append(item)
        packages.sort(key=lambda item: item["name"].lower())
        if packages != expected["packages"]:
            raise ObservationError("Installed package versions/metadata/origins differ")
        site = Path(self.metadata.distribution("policyengine").locate_file(""))
        actual = {
            relative: _sha(site / relative) for relative in self.config["source_hashes"]
        }
        if actual != self.config["source_hashes"]:
            raise ObservationError("Actual installed source bytes differ")
        direct = json.loads(
            (
                Path(self.metadata.distribution("policyengine-us")._path)
                / "direct_url.json"
            ).read_text()
        )
        commit = direct["vcs_info"]["commit_id"]
        if commit != expected["pins"]["country_commit"]:
            raise ObservationError("Actual country commit differs")
        executable = _sha(Path(sys.executable).resolve())
        if (
            executable != expected["executable_sha256"]
            or sys.version != expected["python"]
        ):
            raise ObservationError("Actual interpreter differs")
        self._runtime_receipt = {
            "packages": packages,
            "source_hashes": actual,
            "country_commit": commit,
            "python": sys.version,
            "executable_sha256": executable,
        }
        return RuntimeBinding(
            commit,
            {
                name: self.metadata.version(name)
                for name in (
                    "policyengine",
                    "policyengine-us",
                    "policyengine-core",
                    "spm-calculator",
                )
            },
            _digest(self._runtime_receipt),
        )

    def observe_source(self, path):
        path = Path(path)
        if (
            path.resolve() != Path(self.config["source_path"]).resolve()
            or _sha(path) != self.config["source_sha256"]
        ):
            raise ObservationError("Actual selected raw reference artifact differs")
        return {"source_year": 2024, "sha256": self.config["source_sha256"]}

    @property
    def expected_runtime(self):
        return self.observe_runtime()

    def _inventory(self):
        return [
            (
                name,
                spec.entity,
                spec.period,
                spec.unit,
                self.registry[name].role,
                self.registry[name].source_evidence_sha256,
            )
            for name, spec in sorted(self.specs.items())
            if name not in STRUCTURAL_ROLES
        ]

    @property
    def expected_reference_context(self):
        return {
            "source_sha256": self.config["source_sha256"],
            "runtime_identity_sha256": self.observe_runtime().source_receipt_sha256,
            "source_inventory_sha256": _digest(self._inventory()),
        }

    def _methods(self, sim):
        for name, expected in self.core_methods.items():
            actual = getattr(sim, name)
            if (
                getattr(actual, "__self__", None) is not sim
                or getattr(actual, "__func__", None) is not expected
            ):
                raise ObservationError("Core surviving-input method changed")

    def _raw(self, sim, name, period):
        self._methods(sim)
        read_name = name + "_reported" if name in SOCIAL_SECURITY_SOURCES else name
        found = [p for p in sim._get_set_input_periods(read_name) if str(p) == period]
        if len(found) != 1:
            raise ObservationError(
                "A required surviving supplied input is missing: " + name
            )
        return sim._get_recorded_input_array(read_name, found[0])

    def observe_reference(self, sim):
        self._methods(sim)
        if list(sim.dataset.years) != [2024, 2025]:
            raise ObservationError(
                "Use exactly one source2024/reference2025 preparation"
            )
        topology, counts = topology_inputs(sim)
        if counts != dict(self.contract.entity_counts):
            raise ObservationError("The actual full reference cohort changed")
        for name, spec in self.specs.items():
            if name in STRUCTURAL_ROLES:
                continue
            variable = sim.tax_benefit_system.variables.get(name)
            if variable is None or (
                variable.entity.key,
                str(variable.definition_period).lower(),
            ) != (spec.entity, spec.period):
                raise ObservationError("Actual reference variable schema differs")
            rule = self.registry[name]
            if self.mode == "native":
                source = inspect.getsourcefile(type(variable))
                if source is None or _sha(source) != rule.source_evidence_sha256:
                    raise ObservationError("Actual reference variable source differs")
            if rule.role == "raw" and (
                not variable.is_input_variable()
                or name not in sim.input_variables
                or not sim._get_set_input_periods(name)
            ):
                raise ObservationError("A declared raw field is not actually supplied")
            if rule.role == "prepared_source":
                single = sim.dataset.get_year(2025)
                table = getattr(single, spec.entity)
                if (
                    str(single.time_period) != "2025"
                    or name not in table.columns
                    or str(table[name].dtype) != rule.source_dtype
                ):
                    raise ObservationError("The named prepared source ingress differs")
        self.role_transport = role_transport_from_entities(
            sim.tax_benefit_system.group_entities
        )
        self.role_keys = {
            entity: {row["key"] for row in rows}
            for entity, rows in self.role_transport["entities"].items()
        }
        self._reference_receipt = {
            "entity_counts": counts,
            "topology_sha256": input_digest(topology),
            "inventory_sha256": _digest(self._inventory()),
            "dataset_time_period": str(getattr(sim.dataset, "time_period", None)),
            "default_calculation_period": str(
                getattr(sim, "default_calculation_period", None)
            ),
            "default_input_period": str(getattr(sim, "default_input_period", None)),
            "reference_reads_use_explicit_period": "2025",
        }
        return self.expected_reference_context

    @property
    def serializer_source_sha256(self):
        return self.config["source_hashes"]["policyengine_core/data/dataset.py"]

    def observe_serializer(self, dataset_type):
        source = inspect.getsourcefile(dataset_type)
        if (
            dataset_type.__module__ != "policyengine_core.data.dataset"
            or source is None
            or _sha(source) != self.serializer_source_sha256
        ):
            raise ObservationError("Actual maintained Core serializer source differs")
        return self.serializer_source_sha256

    def bind_native(self, plan):
        if dict(plan.specs) != self.specs or dict(plan.entity_counts) != dict(
            self.contract.entity_counts
        ):
            raise ObservationError("Actual compiled inputs differ from the contract")
        if (plan.law_year, plan.reference_year) != (
            2017,
            2025,
        ) or plan.source_sha256 != self.config["source_sha256"]:
            raise ObservationError("Compiled source/year identity differs")
        self.plan = plan

    def _holder(self, sim, name):
        read_name = name + "_reported" if name in SOCIAL_SECURITY_SOURCES else name
        holder = sim.get_holder(read_name)
        if getattr(holder._to_array, "__func__", None) is not self.holder_to_array:
            raise ObservationError("Actual Core input cast changed")
        return holder

    def _cast(self, sim, name, values):
        try:
            return self._holder(sim, name)._to_array(values, validate_nan=True)
        except (ValueError, TypeError, OverflowError, RuntimeError):
            raise ObservationError("Actual Core input cast refused") from None

    def _topology(self, sim):
        topology, counts = topology_inputs(sim)
        expected = {
            name: self.plan.arrays[name][
                "2017" if self.specs[name].period == "year" else "eternity"
            ]
            for name in topology
        }
        if counts != dict(self.plan.entity_counts) or input_digest(
            topology
        ) != input_digest(expected):
            raise ObservationError("IDs/order/membership/roles changed")

    def snapshot_pilot(self, base, selected):
        if self.plan is None or self._snap is not None:
            raise ObservationError("Bind one compiled packet before the pilot snapshot")
        self._topology(base)
        snapshots = {}
        for name, periods in self.plan.arrays.items():
            if name in STRUCTURAL_ROLES:
                continue
            for period, values in periods.items():
                expected = self._cast(base, name, values)
                if expected.dtype.kind in "f" and not all(
                    math.isfinite(v) for v in expected
                ):
                    raise ObservationError("Actual input cast is nonfinite")
                actual = self._raw(base, name, period)
                if _signature(actual) != _signature(expected):
                    raise ObservationError(
                        "Native baseline differs from materialized input"
                    )
                snapshots[(name, period)] = _signature(actual)
        raw_selected = self._raw(base, PERSON_FLAG, "2017")
        if (
            raw_selected.dtype.kind != "b"
            or len(selected) != len(raw_selected)
            or getattr(selected.dtype, "kind", None) != "b"
            or not (selected == raw_selected).all()
            or not raw_selected.any()
        ):
            raise ObservationError("Selected raw person mask differs")
        self._baseline, self._snap = base, snapshots
        self._selected = raw_selected.copy()
        self._baseline_topology_sha = input_digest(topology_inputs(base)[0])
        self._extras = self._extra_inputs(base)

    def _extra_inputs(self, sim):
        result = {}
        names = {
            name for name, _branch, _period in getattr(sim, "_user_input_keys", ())
        }
        for name in names - set(self.plan.arrays) - {CANDIDATE, PERSON_FLAG}:
            for period in sim._get_set_input_periods(name):
                result[(name, str(period))] = _signature(
                    sim._get_recorded_input_array(name, period)
                )
        return result

    def audit_facts(self, base, branch, selected):
        if self._snap is None or base is not self._baseline:
            raise ObservationError(
                "Snapshot the actual installed baseline before branching"
            )
        if (
            len(selected) != len(self._selected)
            or getattr(selected.dtype, "kind", None) != "b"
            or not (selected == self._selected).all()
        ):
            raise ObservationError("Pilot selection changed")
        self._topology(base)
        for (name, period), signature in self._snap.items():
            if _signature(self._raw(base, name, period)) != signature:
                raise ObservationError("Baseline supplied facts changed")
        if branch is None:
            return True
        self._topology(branch)
        helper_globals = self.tools.create_branch.__globals__
        if (
            helper_globals["user_set_variables"] is not self._supplied
            or helper_globals["PRE_RESPONSE_INPUTS"] != self._pre_response
            or set(helper_globals["HELD_BEHAVIORAL_RESPONSE_VARIABLES"]) != self._held
        ):
            raise ObservationError(
                "Maintained branching input/behavior contract changed"
            )
        if self._extra_inputs(base) != self._extras:
            raise ObservationError("Baseline additional supplied inputs changed")
        extras = self._extra_inputs(branch)
        for key, signature in self._extras.items():
            if extras.get(key) != signature:
                raise ObservationError("A baseline additional supplied input changed")
        for (name, period), signature in extras.items():
            if (name, period) in self._extras:
                continue
            if (
                name not in self._held
                or period != "2017"
                or _signature(base.get_array(name, 2017)) != signature
            ):
                raise ObservationError("Unexpected branch formula/input override")
        supplied = self._supplied(base, 2017)
        pre_response = self._pre_response
        increments = self.tools.split_raise(
            base.person, 2017, self._selected * self.config["native_raise"]
        )
        if set(increments) != {
            "employment_income",
            "self_employment_income",
            "sstb_self_employment_income",
        }:
            raise ObservationError(
                "Only the three maintained earnings components may change"
            )
        changed = {}
        residuals, bounds, split = [], [], []
        for aggregate, increment in increments.items():
            target = (
                aggregate
                if aggregate in supplied
                else pre_response.get(aggregate, aggregate)
            )
            if target not in self.specs or self.specs[target].entity != "person":
                raise ObservationError("Unbound maintained earnings input target")
            before = self._raw(base, target, "2017")
            expected = self._cast(branch, target, before + increment)
            actual = self._raw(branch, target, "2017")
            if _signature(actual) != _signature(expected):
                raise ObservationError(
                    "Branch differs from the actual Core raw target cast"
                )
            if not (actual[~self._selected] == before[~self._selected]).all():
                raise ObservationError("An unselected person's earnings changed")
            changed[(target, "2017")] = _signature(actual)
            residuals.append(actual.astype("float64") - before.astype("float64"))
            split.append(increment)
            np = self.tools.split_raise.__globals__["np"]
            bounds.append(abs(np.spacing(expected)) * 0.5 * (increment != 0))
        for key, signature in self._snap.items():
            if key not in changed and _signature(self._raw(branch, *key)) != signature:
                raise ObservationError("A fixed weight/age/draw/input changed")
        selected = self._selected
        error = abs(sum(residuals)[selected] - self.config["native_raise"])
        split_error = abs(sum(split)[selected] - self.config["native_raise"])
        bound = sum(bounds)[selected] + split_error
        maximum = float(error.max()) if len(error) else 0.0
        self._precision = {
            "status": "EXACT" if maximum == 0 else "precision_refused",
            "zero_tolerance": True,
            "raw_targets_exact": True,
            "max_native_earnings_error": maximum,
            "max_derived_cast_ulp_bound_native": float(bound.max())
            if len(bound)
            else 0.0,
            "selected_person_count": int(selected.sum()),
            "bound_applied_to_cutoffs_or_tolerance": False,
        }
        # This is not permission to use a nonzero tolerance. The pilot emits
        # diagnostic receipts and stops with precision_refused before results;
        # commissioned.run also retains its separate zero-tolerance identity gate.
        return True

    def bindings(self, reference_receipt, account_spec, written, controls):
        if self.plan is None or not TAKEUP_INPUTS.issubset(self.plan.arrays):
            raise ObservationError("Actual materialized take-up decisions are missing")
        if (
            written.receipt.get("source_sha256") != self.plan.source_sha256
            or written.receipt.get("contract_sha256") != self.plan.contract_sha256
            or written.receipt.get("decoded_input_sha256")
            != input_digest(self.plan.arrays)
        ):
            raise ObservationError(
                "Actual serialized source/input correspondence differs"
            )
        account = {
            item.name: getattr(account_spec, item.name) for item in fields(account_spec)
        }
        decision_arrays = {
            name: dict(self.plan.arrays[name]) for name in sorted(TAKEUP_INPUTS)
        }
        self._binding_receipt = {
            "preparation_sha256": reference_receipt["receipt_sha256"],
            "account_sha256": _digest(account),
            "price_anchor_sha256": account_spec.health_price_anchor_sha256,
            "full_sample_households_sha256": input_digest(
                self.plan.arrays["household_id"]
            ),
            "native_controls_sha256": _digest(controls),
            "baseline_sha256": written.receipt["sha256"],
            "takeup_draws_sha256": input_digest(decision_arrays),
        }
        return dict(self._binding_receipt)

    @property
    def precision_report(self):
        return dict(self._precision)

    def aggregate_receipt(self):
        return {
            "scope": "ONE_NATIVE_RAISE_PILOT_NO_POPULATION_ESTIMATE",
            "runtime_identity_sha256": None
            if self._runtime_receipt is None
            else _digest(self._runtime_receipt),
            "reference": self._reference_receipt,
            "bindings": self._binding_receipt,
            "precision": self.precision_report,
            "takeup_binding_meaning": "actual stored participation decisions, not invented random variates",
            "mode": self.mode,
            "raw_records_or_IDs_returned": False,
        }


def load_native_observers(
    config,
    *,
    contract,
    specs,
    registry,
    tools,
    core_methods,
    holder_to_array,
    mode="native",
    metadata_api=None,
):
    return NativeObservers(
        config,
        contract=contract,
        specs=specs,
        registry=registry,
        tools=tools,
        core_methods=core_methods,
        holder_to_array=holder_to_array,
        mode=mode,
        metadata_api=metadata_api,
    )
