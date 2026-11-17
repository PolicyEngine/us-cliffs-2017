"""Explicit source-backed declarations for a prepared native input packet.

This builds transport objects only. The caller still observes the real managed
source, preparation and native runtime; metadata equality is not qualification.
"""

from cliffs2017.managed_native import ENTITIES, InputSpec
from cliffs2017.native_currency import FieldSpec, InputContract
from cliffs2017.native_materializer import InputRule, MaterializationError


def build_managed_input_contract(declaration, *, actual_metadata):
    """Return existing contract/spec/rule objects; never infer omitted fields."""
    records = {row["name"]: row for row in actual_metadata["records"]}
    if (
        actual_metadata.get("status") != "ACTUAL_SAME_TBS_METADATA_ONLY"
        or actual_metadata.get("missing") != []
        or actual_metadata.get("requested_names") != 187
        or actual_metadata.get("exported_names") != 187
        or len(actual_metadata["records"]) != 187
        or len(records) != 187
        or declaration.get("law_year") != 2017
        or declaration.get("reference_year") != 2025
        or declaration.get("source_year") != 2024
        or set(declaration["entity_counts"]) != ENTITIES
    ):
        raise MaterializationError("Bind the complete actual source/metadata contract")
    rows = declaration["fields"]
    names = {row["name"] for row in rows}
    roles = {f"person_{entity}_role" for entity in ENTITIES - {"person"}}
    if len(rows) != 192 or len(names) != 192 or names != records.keys() | roles:
        raise MaterializationError(
            "Every variable and explicit structural role is required"
        )
    physical = declaration["source_column_dispositions"]
    if (
        len(physical) != 377
        or len({(row["source_entity"], row["source_name"]) for row in physical}) != 377
    ):
        raise MaterializationError(
            "Preserve the full physical source disposition ledger"
        )
    fields, specs, rules = [], {}, {}
    prepared = {
        "social_security_retirement",
        "social_security_disability",
        "social_security_survivors",
        "social_security_dependents",
        "is_spm_independent_minor_role",
    }
    identifiers = {f"{entity}_id" for entity in ENTITIES} | {
        f"person_{entity}_id" for entity in ENTITIES - {"person"}
    }
    for row in rows:
        name = row["name"]
        if row["role"] == "structural" and name not in identifiers | roles:
            raise MaterializationError("No additional structural input exception")
        if name in records:
            signature = row["metadata_signature"]
            actual = records[name]
            if any(actual.get(key) != value for key, value in signature.items()):
                raise MaterializationError(
                    "Actual variable metadata/source differs: " + name
                )
            if (row["entity"], row["period"]) != (
                actual["entity"],
                actual["definition_period"],
            ):
                raise MaterializationError(
                    "Use each variable's actual entity and period"
                )
            if row["role"] == "prepared_source":
                if name not in prepared:
                    raise MaterializationError("No additional formula-input exception")
            elif row["role"] != "structural" and not actual["is_input_variable"]:
                raise MaterializationError(
                    "Stored formula outputs cannot become raw inputs"
                )
        elif (
            row["role"] != "structural"
            or row["entity"] != "person"
            or row["period"] != "eternity"
            or row["dtype"] != "str"
            or row["unit"] != "category"
        ):
            raise MaterializationError("Retain the actual flattened structural roles")
        fields.append(
            FieldSpec(
                name,
                row["entity"],
                row["kind"],
                row["disposition"],
                row["unit"],
                row["period"],
            )
        )
        specs[name] = InputSpec(row["entity"], row["period"], row["dtype"], row["unit"])
        rules[name] = InputRule(
            row["role"], row["source_evidence_sha256"], row["source_dtype"]
        )
    return InputContract(tuple(fields), declaration["entity_counts"]), specs, rules
