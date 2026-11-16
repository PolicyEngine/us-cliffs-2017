"""2017 hourly wages for the national job-entry test, read from the wage audit.

``research/minimum-wages-2017/wages.json`` records each jurisdiction's general
adult rate as of 1 January 2017, with dated, regional and employer-size variants.
This module turns it into one effective hourly rate per jurisdiction under the
conventions in EXPANDED_JOB_ENTRY.md ("National wage conventions"):

1. the statewide general rate, weighted by calendar day over 2017 where it changed
   within the year;
2. the large-employer rate where a state tiers by employer size or receipts;
3. the standard statewide rate where a state tiers by region;
4. no local ordinances (wages.json records none);
5. a floor at the federal $7.25, applied to each dated rate.

Nevada tiers by whether the employer offers qualifying health benefits. The
hypothetical job offers none, so its higher rate applies, as wages.json records.

The job's gross pay is the effective hourly rate times 2,080 hours. A
jurisdiction whose 2017 rate path wages.json cannot supply in full, or supplies
inconsistently, is reported as unresolved and gets no rate: there is no default.

Standard library only, so the Modal client's own Python can import it.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WAGES_JSON = ROOT / "research" / "minimum-wages-2017" / "wages.json"
YEAR = 2017
FIRST = dt.date(YEAR, 1, 1)
LAST = dt.date(YEAR, 12, 31)
DAYS = (LAST - FIRST).days + 1
HOURS_PER_YEAR = 40 * 52
FEDERAL_FLOOR = Fraction("7.25")

JURISDICTIONS = frozenset(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO "
    "MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split()
)

# Employer-size or receipts tiers: the large-employer category, named by the
# JSON's own label. The selected rate must also be the highest tier.
LARGE_EMPLOYER = {
    "AR": ("employer_size", "state-covered employer, generally4+ employees"),
    "CA": ("employer_size", "26or more employees"),
    "IL": ("employer_size", "state-covered employer, generally4+ employees"),
    "MI": ("employer_size", "state-covered employer, generally2+ employees"),
    "MN": ("employer_gross_annual_sales", "at least500000"),
    "MT": ("employer_gross_annual_sales", "over110000"),
    "NE": ("employer_size", "state-covered employer, generally4+ employees"),
    "OH": ("employer_gross_annual_sales", "299000or more"),
    "VT": ("employer_size", "state-covered employer, generally2+ employees"),
    "WV": ("employer_size", "state-covered employer, generally6+ employees"),
}
# Region tiers: the standard statewide rate. New York's standard rate is its
# rest-of-state rate; New York City and Long Island/Westchester are higher tiers.
STANDARD_REGION = {"NY": "rest of state", "OR": "standard"}
# Health-offer tier: the job offers no employer health coverage.
NO_HEALTH_OFFER = frozenset({"NV"})
# Jurisdictions whose 2017 rate changed after 1 January, as evidence.md
# ("Corrections and choices", "Readiness" item 5) and metadata.unresolved list
# them. Each needs dated rates covering every day of 2017.
WITHIN_YEAR = frozenset({"DC", "MD", "ME", "NY", "OR"})
# wages.json marks Maine unverified because the codified statute says 1 January
# while the contemporaneous Maine DOL release, its 2017 poster packet and DOL's
# dated table say 7 January. The brief names Maine as a mid-year change to
# weight by time, so its dated path (7 January) is used; the statute's date
# would give $9.00, $0.0247 an hour or $51 a year more.
ACCEPTED_UNVERIFIED = {
    "ME": "dated path with the 7 January effective date (Maine DOL release, 2017 "
    "poster packet, DOL dated table); the codified 1 January date gives $9.00"
}
TIER_KEYS = ("employer_size", "employer_gross_annual_sales", "employer_health_offer", "industry")


class UnresolvedWage(ValueError):
    """wages.json cannot supply this jurisdiction's 2017 rate under the conventions."""


def _date(text: str | None) -> dt.date | None:
    return None if text is None else dt.date.fromisoformat(text)


def _select(code: str, entry: dict) -> tuple[list[dict], str]:
    """The variants that form the jurisdiction's 2017 path, and the rule used."""
    variants = entry.get("variants") or []
    if code in LARGE_EMPLOYER:
        key, label = LARGE_EMPLOYER[code]
        chosen = [v for v in variants if v.get(key) == label]
        if len(chosen) != 1:
            raise UnresolvedWage(f"{code}: expected one large-employer variant {label!r}")
        if Fraction(str(chosen[0]["hourly"])) != max(Fraction(str(v["hourly"])) for v in variants):
            raise UnresolvedWage(f"{code}: the large-employer variant is not the highest tier")
        return chosen, "large-employer rate"
    if code in STANDARD_REGION:
        label = STANDARD_REGION[code]
        chosen = [v for v in variants if v.get("region") == label and "industry" not in v]
        if not chosen:
            raise UnresolvedWage(f"{code}: no standard-region variant {label!r}")
        return chosen, f"standard region ({label})"
    if code in NO_HEALTH_OFFER:
        chosen = [v for v in variants if v.get("employer_health_offer") is False]
        if len(chosen) != 1:
            raise UnresolvedWage(f"{code}: expected one no-health-offer variant")
        return chosen, "employer offers no health coverage"
    if any(key in v for v in variants for key in TIER_KEYS):
        raise UnresolvedWage(f"{code}: tiered variants with no convention")
    if any(v.get("region") != "statewide" for v in variants):
        raise UnresolvedWage(f"{code}: regional variants with no convention")
    return variants, "statewide"


def _segments(code: str, entry: dict) -> tuple[list[tuple[dt.date, dt.date, Fraction]], str]:
    """Dated rates clipped to 2017, which must cover every day exactly once."""
    if not entry.get("variants"):
        if code in WITHIN_YEAR:
            raise UnresolvedWage(
                f"{code}: wages.json records only the 1 January rate, but the 2017 rate "
                "changed within the year (evidence.md) and the later rate is absent"
            )
        reference = entry.get("reference_hourly")
        if reference is None:
            raise UnresolvedWage(f"{code}: no reference_hourly and no variants")
        return [(FIRST, LAST, Fraction(str(reference)))], "statewide"
    chosen, rule = _select(code, entry)
    pieces = []
    for v in chosen:
        start = max(_date(v.get("starts")) or FIRST, FIRST)
        end = min(_date(v.get("ends")) or LAST, LAST)
        if start <= end:
            pieces.append((start, end, Fraction(str(v["hourly"]))))
    pieces.sort()
    day = FIRST
    for start, end, _ in pieces:
        if start > day:
            raise UnresolvedWage(f"{code}: no rate for {day}..{start - dt.timedelta(days=1)}")
        if start < day:
            raise UnresolvedWage(f"{code}: overlapping dated rates from {start}")
        day = end + dt.timedelta(days=1)
    if day <= LAST:
        raise UnresolvedWage(f"{code}: no rate for {day}..{LAST}")
    if len(pieces) > 1 and code not in WITHIN_YEAR:
        raise UnresolvedWage(f"{code}: a within-year change the evidence file doesn't list")
    if code in WITHIN_YEAR and len(pieces) == 1:
        raise UnresolvedWage(f"{code}: the evidence lists a within-year change the JSON lacks")
    return pieces, rule


def jurisdiction_rate(code: str, entry: dict) -> dict:
    """One jurisdiction's effective 2017 hourly rate, or UnresolvedWage."""
    if not entry.get("verified") and code not in ACCEPTED_UNVERIFIED:
        raise UnresolvedWage(f"{code}: wages.json marks the rate unverified")
    pieces, rule = _segments(code, entry)
    january = pieces[0][2]
    headline = entry.get("amount")
    if headline is None or Fraction(str(headline)) != january:
        raise UnresolvedWage(f"{code}: the 1 January rate {january} contradicts amount {headline}")
    if entry.get("reference_hourly") is not None and Fraction(str(entry["reference_hourly"])) != january:
        raise UnresolvedWage(f"{code}: reference_hourly contradicts the selected 1 January rate")
    weighted = sum(
        (max(rate, FEDERAL_FLOOR) * ((end - start).days + 1) for start, end, rate in pieces),
        Fraction(0),
    ) / DAYS
    return {
        "state": code,
        "name": entry.get("name"),
        "rule": rule if len(pieces) == 1 else f"{rule}, weighted by day over 2017",
        "path": [
            {"from": str(start), "to": str(end), "hourly": float(rate), "days": (end - start).days + 1}
            for start, end, rate in pieces
        ],
        "hourly": float(weighted),
        "hourly_exact": f"{weighted.numerator}/{weighted.denominator}",
        "gross_pay": float(weighted * HOURS_PER_YEAR),
        "federal_floor_binds": any(rate < FEDERAL_FLOOR for _, _, rate in pieces)
        or any("absent or below federal floor" in n for n in entry.get("notes", [])),
        "accepted_unverified": ACCEPTED_UNVERIFIED.get(code),
        "sources": sorted(
            (
                {entry.get("source_url"), entry.get("corroborating_source_url")}
                | {v.get("source_url") for v in entry.get("variants") or []}
            )
            - {None}
        ),
    }


def load_wages(path: Path = WAGES_JSON) -> tuple[dict, str]:
    raw = Path(path).read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def national_wage_table(data: dict | None = None, sha256: str | None = None) -> dict:
    """Every jurisdiction's effective rate, and the ones wages.json leaves unresolved."""
    if data is None:
        data, sha256 = load_wages()
    states = data["states"]
    if set(states) != JURISDICTIONS:
        raise ValueError(f"wages.json lists {sorted(set(states) ^ JURISDICTIONS)} unexpectedly")
    if Fraction(str(data["metadata"]["federal_floor"])) != FEDERAL_FLOOR:
        raise ValueError("wages.json states a different federal floor")
    rows, unresolved = {}, {}
    for code in sorted(states):
        try:
            rows[code] = jurisdiction_rate(code, states[code])
        except UnresolvedWage as error:
            unresolved[code] = str(error)
    return {
        "year": YEAR,
        "hours_per_year": HOURS_PER_YEAR,
        "wages_json_sha256": sha256,
        "rates": {code: row["hourly"] for code, row in rows.items()},
        "rows": rows,
        "unresolved": unresolved,
    }


def require_complete(table: dict) -> dict:
    """The rates, only when every jurisdiction is resolved."""
    if table["unresolved"]:
        raise UnresolvedWage("unresolved 2017 wages: " + "; ".join(table["unresolved"].values()))
    return table["rates"]


if __name__ == "__main__":
    table = national_wage_table()
    for code, row in table["rows"].items():
        print(f"{code}  {row['hourly']:.4f}  {row['gross_pay']:>10,.2f}  {row['rule']}")
    for code, reason in table["unresolved"].items():
        print(f"{code}  UNRESOLVED  {reason}")
