"""A dated hypothetical-job input; no tax, benefit or population estimates."""

import hashlib
import json
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path
from types import MappingProxyType

STATE_CODES = frozenset(
    [
        "AL",
        "AK",
        "AZ",
        "AR",
        "CA",
        "CO",
        "CT",
        "DE",
        "FL",
        "GA",
        "HI",
        "ID",
        "IL",
        "IN",
        "IA",
        "KS",
        "KY",
        "LA",
        "ME",
        "MD",
        "MA",
        "MI",
        "MN",
        "MS",
        "MO",
        "MT",
        "NE",
        "NV",
        "NH",
        "NJ",
        "NM",
        "NY",
        "NC",
        "ND",
        "OH",
        "OK",
        "OR",
        "PA",
        "RI",
        "SC",
        "SD",
        "TN",
        "TX",
        "UT",
        "VT",
        "VA",
        "WA",
        "WV",
        "WI",
        "WY",
        "DC",
    ]
)
NATIVE_PER_REFERENCE_DOLLAR = Fraction(245120, 321943)


class WageBenchmark:
    """January 7, 2017 state/regional rates for a covered, non-tipped adult job.

    The experiment assumes a large covered employer, residence equals workplace,
    no special industry or training rate, and no new employer health coverage.
    It excludes local ordinances and within-year changes. It supplies benchmark
    wages, rather than the legally applicable minimum for every possible job.
    """

    def __init__(self, path: Path | None = None):
        path = (
            path or Path(__file__).with_name("data") / "wage_benchmark_2017-01-07.json"
        )
        payload = Path(path).read_bytes()
        data = json.loads(payload)
        if data["reference_date"] != "2017-01-07" or data["law_currency_year"] != 2017:
            raise ValueError(
                "This benchmark requires the explicit January 7, 2017 convention"
            )
        if set(data["base_hourly_by_state"]) != STATE_CODES:
            raise ValueError("Declare all 50 states and DC exactly once")
        rates = {
            state: Fraction(value)
            for state, value in data["base_hourly_by_state"].items()
        }
        if any(value <= 0 for value in rates.values()):
            raise ValueError("Benchmark wages must be positive")
        if set(data["valid_counties"]) != {"NY", "OR"}:
            raise ValueError("Bind both regional county inventories")
        counties = {
            state: frozenset(records)
            for state, records in data["valid_counties"].items()
        }
        if len(counties["NY"]) != 62 or len(counties["OR"]) != 36:
            raise ValueError("The source county inventory changed")
        for state, prefix in (("NY", "36"), ("OR", "41")):
            if any(
                not isinstance(code, str)
                or len(code) != 5
                or not code.isascii()
                or not code.isdigit()
                or not code.startswith(prefix)
                for code in counties[state]
            ):
                raise ValueError(
                    "County identifiers must retain the declared state and FIPS format"
                )
        overrides = data["county_overrides"]
        if set(overrides) != {"NY_city_large", "NY_downstate", "OR_nonurban"}:
            raise ValueError("Declare the three regional benchmark groups")
        groups, used = [], set()
        for name in ("NY_city_large", "NY_downstate", "OR_nonurban"):
            row = overrides[name]
            state, codes = row["state"], frozenset(row["county_fips"])
            rate = Fraction(row["hourly"])
            if (
                state not in counties
                or not codes
                or not codes <= counties[state]
                or used & codes
                or rate <= 0
            ):
                raise ValueError(
                    "Regional benchmarks must cover valid, disjoint counties"
                )
            used.update(codes)
            groups.append((state, codes, rate))
        self.source_sha256 = hashlib.sha256(payload).hexdigest()
        self.rates = MappingProxyType(rates)
        self.counties = MappingProxyType(counties)
        self.groups = tuple(groups)

    def hourly_wages_real(self, simulation, *, is_weighted: Callable, period=2017):
        """Return weighted 2025 dollars/hour through the managed person mapping."""
        if type(period) is not int or period != 2017 or not callable(is_weighted):
            raise ValueError(
                "Use the native 2017 clock and a weighted-series validator"
            )
        state = simulation.calc("state_code", period=period, map_to="person")
        county = simulation.calc("county_fips", period=period, map_to="person")
        if not all(is_weighted(series) for series in (state, county)):
            raise TypeError("Managed geography must preserve MicroSeries weights")
        if state.isna().any() or county.isna().any():
            raise ValueError("Missing job geography cannot select a wage")
        covered = (state == "AL") & False
        wage = (state == "AL") * 0.0
        for code, rate in self.rates.items():
            mask = state == code
            covered = covered | mask
            wage = wage + mask * float(rate)
        if (~covered).any():
            raise ValueError("No declared benchmark for a person's state")
        for code, valid in self.counties.items():
            known = covered & False
            for fips in sorted(valid):
                known = known | (county == fips)
            if ((state == code) & ~known).any():
                raise ValueError("Unknown NY/OR county cannot select a regional wage")
        for code, counties, rate in self.groups:
            member = covered & False
            for fips in sorted(counties):
                member = member | (county == fips)
            wage = wage + ((state == code) & member) * float(rate - self.rates[code])
        # The input source uses 2017 nominal dollars. One inverse conversion
        # supplies the orchestrator's common 2025-dollar hourly input.
        result = wage / float(NATIVE_PER_REFERENCE_DOLLAR)
        if not is_weighted(result):
            raise TypeError("Wage arithmetic lost its managed weights")
        return result
