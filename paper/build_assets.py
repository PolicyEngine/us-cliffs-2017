"""Build paper exhibits from committed aggregates of completed model runs.

This script runs no tax-benefit simulation and reads no microdata or survey
weights. All arithmetic combines aggregates from the same completed scenario.
Refresh takes byte-for-byte snapshots from the recorded Git commit; later builds
need only those snapshots, this script, and the locked plotting environment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parent
COMMIT = "ff0672e5f7f0728208599d988e9bd3cc2e195391"
GITHUB = "https://github.com/PolicyEngine/us-cliffs-2017"
MAIN = "results/earnings_changes.json"
FILES = [
    MAIN,
    "results/health_only.json",
    "results/take_up_bounds.json",
    "results/driver_intervals.json",
    "results/counted_once/once_2017.json",
    "results/counted_once/once_2025.json",
    "april2025/precision_summary.json",
    "METHODOLOGY.md",
    "CORRECTION.md",
    "pyproject.toml",
]
TEAL = "#319795"  # PolicyEngine --chart-1
SLATE = "#64748B"  # PolicyEngine --chart-5
BLUE = "#0EA5E9"  # PolicyEngine --chart-2
DARK_TEAL = "#285E61"  # PolicyEngine --chart-3
GRAY = "#E2E8F0"  # PolicyEngine --border
INK = "#101828"  # PolicyEngine --color-gray-900
CLAIMS: dict[str, dict] = {}


def git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), *args])


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def refresh(repo: Path) -> None:
    tree = git(repo, "ls-tree", "-r", "--name-only", COMMIT).decode().splitlines()
    parts = [
        n
        for n in tree
        if n.startswith("results/earnings_changes/parts/") and n.endswith(".json")
    ]
    if len(parts) != 80:
        raise ValueError(f"Expected 80 completed part/change files, got {len(parts)}")
    records = []
    for name in [*FILES, *parts]:
        data = git(repo, "show", f"{COMMIT}:{name}")
        dest = ROOT / "inputs" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        records.append({"path": name, "sha256": sha(data), "bytes": len(data)})
    manifest = {
        "source_repository": GITHUB,
        "source_commit": COMMIT,
        "source_date": "2026-11-11",
        "description": "Byte-for-byte committed aggregates of completed simulations; no record-level data",
        "files": records,
    }
    (ROOT / "inputs" / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )


def verify() -> dict:
    manifest = json.loads((ROOT / "inputs" / "manifest.json").read_text())
    for item in manifest["files"]:
        if sha((ROOT / "inputs" / item["path"]).read_bytes()) != item["sha256"]:
            raise ValueError(f"Snapshot hash mismatch: {item['path']}")
    parts = list((ROOT / "inputs/results/earnings_changes/parts").glob("*/*.json"))
    if len(parts) != 80:
        raise ValueError("Incomplete experiment snapshots")
    codes = set()
    bases = 0
    for path in parts:
        part = json.loads(path.read_text())
        if part.get("problems"):
            raise ValueError(f"Recorded run problems: {path.name}")
        codes.add((part["code"]["cliffs2017_sha256"], part["code"]["script_sha256"]))
        if path.name == "raise_1000.json":
            if part.get("reproduces_committed_part") is not True:
                raise ValueError("Failed original-part replication")
            bases += 1
    if len(codes) != 1 or bases != 8:
        raise ValueError("Inconsistent run code or missing replication checks")
    supplement = json.loads((ROOT / "inputs/robustness/manifest.json").read_text())
    for item in supplement["files"]:
        file = ROOT / "inputs/robustness" / item["path"]
        if (
            file.stat().st_size != item["bytes"]
            or sha(file.read_bytes()) != item["sha256"]
        ):
            raise ValueError("Robustness snapshot hash/size mismatch")
    household_dir = ROOT / "inputs/household-curves"
    household = json.loads((household_dir / "manifest.json").read_text())
    household_file = household_dir / household["file"]
    if (
        household_file.stat().st_size != household["bytes"]
        or sha(household_file.read_bytes()) != household["sha256"]
    ):
        raise ValueError("Household curve snapshot hash/size mismatch")
    policy_dir = ROOT / "inputs/policy-date-audit"
    policy = json.loads((policy_dir / "manifest.json").read_text())
    for name, item in policy["files"].items():
        path = policy_dir / name
        if (
            path.stat().st_size != item["bytes"]
            or sha(path.read_bytes()) != item["sha256"]
        ):
            raise ValueError(f"Policy-date audit snapshot changed: {name}")
    return {
        "supplementary_files_verified": len(supplement["files"]),
        "files_verified": len(manifest["files"]),
        "part_changes": len(parts),
        "baseline_replications": bases,
        "household_curve_files_verified": 1,
        "policy_date_files_verified": len(policy["files"]),
        "code_hashes": list(codes),
    }


def read(name: str) -> dict:
    return json.loads((ROOT / "inputs" / name).read_text())


def record_numeric_leaves(value, source: str, pointer: str = "") -> None:
    """Make the provenance index cover every archived numeric exhibit input."""
    if isinstance(value, dict):
        for key, item in value.items():
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            record_numeric_leaves(item, source, f"{pointer}/{escaped}".lstrip("/"))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            record_numeric_leaves(item, source, f"{pointer}/{i}".lstrip("/"))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        claim(f"archive:{source}#{pointer}", value, source, pointer)


def claim(key: str, value, source: str, pointer: str, operation: str = "read"):
    CLAIMS[key] = {
        "value": value,
        "source": source,
        "json_pointer": pointer,
        "operation": operation,
    }
    return value


def number(key: str, d: dict, pointer: str):
    value = d
    for part in pointer.split("/"):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return claim(key, value, MAIN, pointer)


def m(value: float, digits: int = 2) -> str:
    return f"{value / 1e6:.{digits}f}"


def ci(value: list) -> str:
    return f"{m(value[0])}-{m(value[1])}"


def table(name: str, headers: list[str], rows: list[list[str]], note: str = "") -> str:
    text = "| " + " | ".join(headers) + " |\n"
    text += "|" + "|".join(["---"] + ["---:"] * (len(headers) - 1)) + "|\n"
    text += "\n".join("| " + " | ".join(row) + " |" for row in rows) + "\n"
    if note:
        text += "\n" + note + "\n"
    (ROOT / "tables" / f"{name}.md").write_text(text)
    return text


def plot_setup() -> None:
    fonts = ROOT / "assets" / "fonts"
    for font in fonts.glob("Inter*.ttf"):
        font_manager.fontManager.addfont(str(font))
    plt.rcParams.update(
        {
            "font.family": "Inter",
            "font.size": 10,
            "axes.titlesize": 11,
            "axes.labelsize": 10,
            "text.color": INK,
            "axes.labelcolor": INK,
            "xtick.color": INK,
            "ytick.color": INK,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.edgecolor": GRAY,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "svg.fonttype": "none",
            "savefig.dpi": 220,
        }
    )


def save(fig, name: str):
    fig.savefig(ROOT / "figures" / f"{name}.png", bbox_inches="tight")
    fig.savefig(ROOT / "figures" / f"{name}.svg", bbox_inches="tight")
    svg = ROOT / "figures" / f"{name}.svg"
    svg.write_text(
        "\n".join(line.rstrip() for line in svg.read_text().splitlines()) + "\n"
    )
    plt.close(fig)


def build(include_figures: bool = False) -> None:
    for folder in ("tables", "figures", "checks"):
        (ROOT / folder).mkdir(exist_ok=True)
    checked = verify()
    d = read(MAIN)
    for source in FILES:
        if source.endswith(".json"):
            record_numeric_leaves(read(source), source)
    assert d["partial"] is False and d["draws"] == 5000 and d["seed"] == 0
    values: dict[str, str] = {}
    policy_source = "policy-date-audit/summary.json"
    record_numeric_leaves(read(policy_source), policy_source)
    household_source = "household-curves/paper_household_curves.json"
    households = read(household_source)
    for case_key, case in households["cases"].items():
        prefix = f"cases/{case_key}"
        for field in ("earnings", "resources_cash", "resources_full_health"):
            record_numeric_leaves(
                case["curve"][field], household_source, f"{prefix}/curve/{field}"
            )
        record_numeric_leaves(
            case["annotations"], household_source, f"{prefix}/annotations"
        )
        record_numeric_leaves(
            case["specification"], household_source, f"{prefix}/specification"
        )
        for point_key, point in case["independently_run_points"].items():
            for field in ("earnings", "resources_cash", "resources_full_health"):
                record_numeric_leaves(
                    point[field],
                    household_source,
                    f"{prefix}/independently_run_points/{point_key}/{field}",
                )
        event = case["annotations"][0]
        for amount in (1000, 5000):
            delta = event["raise_comparisons"][str(amount)]["full_resource_change"]
            values[f"hh_{case_key}_{amount}_absolute_change"] = f"{abs(delta):,.0f}"
        values[f"hh_{case_key}_baseline"] = (
            f"{event['sampled_change']['before']['earnings']:,.0f}"
        )
    rows = []
    worker_rows = []
    full_rows = []
    directions = []
    small_rows = []
    for year in ("2017", "2025"):
        base = d["years"][year]
        for size in (1000, 2000, 5000):
            key = f"raise_{size}"
            c = base["changes"][key]
            prefix = f"years/{year}/changes/{key}"
            n = number(f"selected_adults_{year}", d, prefix + "/adults_reached/adults")
            wr = number(f"tested_workers_{year}", d, prefix + "/workers_reached")
            cash, health = c["without_health"], c["with_health"]
            for measure, item in (("cash", cash), ("health", health)):
                path_measure = "without_health" if measure == "cash" else "with_health"
                for field in (
                    "people_on_cliff",
                    "workers_on_cliff",
                    "households_with_person_on_cliff",
                    "people_in_those_households",
                    "interval_95",
                    "share_of_adults_reached",
                ):
                    v = number(
                        f"{year}_{size}_{measure}_{field}",
                        d,
                        prefix + f"/{path_measure}/{field}",
                    )
                    if isinstance(v, (int, float)):
                        values[f"n{year}_{size}_{measure}_{field}"] = m(v)
                rate = claim(
                    f"worker_rate_{year}_{size}_{measure}",
                    item["workers_on_cliff"] / wr,
                    MAIN,
                    prefix
                    + f"/{path_measure}/workers_on_cliff ; {prefix}/workers_reached",
                    "divide two aggregates from the same completed scenario",
                )
                values[f"worker_rate_{year}_{size}_{measure}"] = f"{rate * 100:.2f}"
                values[f"adult_rate_{year}_{size}_{measure}"] = (
                    f"{item['share_of_adults_reached'] * 100:.2f}"
                )
                full_rows.append(
                    [
                        year,
                        f"+${size:,}",
                        "Cash" if measure == "cash" else "Health",
                        m(item["people_on_cliff"]),
                        ci(item["interval_95"]),
                        m(item["households_with_person_on_cliff"]),
                        m(item["people_in_those_households"]),
                    ]
                )
            rows.append(
                [
                    year,
                    f"+${size:,}",
                    m(cash["people_on_cliff"]),
                    ci(cash["interval_95"]),
                    m(health["people_on_cliff"]),
                    ci(health["interval_95"]),
                ]
            )
            worker_rows.append(
                [
                    year,
                    f"+${size:,}",
                    m(wr),
                    values[f"worker_rate_{year}_{size}_cash"],
                    values[f"worker_rate_{year}_{size}_health"],
                ]
            )
            assert (
                abs(health["share_of_adults_reached"] - health["people_on_cliff"] / n)
                < 1e-10
            )
        values[f"adults_{year}"] = m(
            base["changes"]["raise_1000"]["adults_reached"]["adults"]
        )
        values[f"workers_{year}"] = m(base["changes"]["raise_1000"]["workers_reached"])
        excluded = base["workers"] - base["changes"]["raise_1000"]["workers_reached"]
        values[f"untested_workers_{year}"] = m(
            claim(
                f"untested_workers_{year}",
                excluded,
                MAIN,
                f"years/{year}/workers ; years/{year}/changes/raise_1000/workers_reached",
                "difference of same-scenario aggregate populations",
            )
        )
        for size in ("1000", "2000", "5000", "1pct", "10pct"):
            up, down = base["changes"][f"raise_{size}"], base["changes"][f"cut_{size}"]
            union = base["either_side"][f"raise_{size}|cut_{size}"]["with_health"]
            label = f"${int(size):,}" if "pct" not in size else size.replace("pct", "%")
            directions.append(
                [
                    year,
                    label,
                    m(up["with_health"]["people_on_cliff"]),
                    m(down["with_health"]["people_on_cliff"]),
                    m(union["adults"]),
                    ci(union["interval_95"]),
                ]
            )
            for measure, title in (
                ("without_health", "Cash"),
                ("with_health", "Health"),
            ):
                item = up[measure]
                tiny = item["net_income_moves_12_or_less"]["adults"]
                tiny_share = claim(
                    f"small_share_{year}_{size}_{measure}",
                    100 * tiny / item["people_on_cliff"],
                    MAIN,
                    f"years/{year}/changes/raise_{size}/{measure}/net_income_moves_12_or_less/adults ; years/{year}/changes/raise_{size}/{measure}/people_on_cliff",
                    "divide same-experiment archived small-loss and total counts, multiply by 100",
                )
                small_rows.append(
                    [
                        year,
                        "+" + label,
                        title,
                        m(item["people_on_cliff"]),
                        f"{tiny / 1000:.1f}",
                        f"{tiny_share:.1f}",
                    ]
                )
        paired = base["changes"]["raise_5000"]["with_health"]["versus_raise_1000"]
        values[f"paired_{year}"] = m(
            number(
                f"paired_{year}",
                d,
                f"years/{year}/changes/raise_5000/with_health/versus_raise_1000/difference",
            )
        )
        values[f"paired_ci_{year}"] = ci(paired["interval_95"])

    values["table_fixed"] = table(
        "fixed-raises",
        [
            "Scenario",
            "Annual raise",
            "Cash adults (m)",
            "95% interval",
            "Health adults (m)",
            "95% interval",
        ],
        rows,
    )
    values["table_workers"] = table(
        "tested-workers",
        ["Scenario", "Raise", "Tested workers (m)", "Cash rate (%)", "Health rate (%)"],
        worker_rows,
    )
    values["table_full"] = table(
        "full-fixed-results",
        [
            "Scenario",
            "Raise",
            "Measure",
            "Adults (m)",
            "Households (m)",
            "Members (m)",
        ],
        [row[:4] + row[5:] for row in full_rows],
    )
    values["table_directions"] = table(
        "directions",
        [
            "Scenario",
            "Size",
            "Raise (m)",
            "Cut (m)",
            "Either side (m)",
            "95% union interval",
        ],
        directions,
    )
    values["table_small"] = table(
        "small-losses",
        [
            "Scenario",
            "Raise",
            "Measure",
            "Flagged (m)",
            "Loss <=$12 (000s)",
            "Share of flags (%)",
        ],
        small_rows,
    )

    overlap = read("results/health_only.json")
    valuation_rows = []
    takeup = read("results/take_up_bounds.json")
    takeup_rows = []
    for year in ("2017", "2025"):
        o = overlap["years"][year]["only_with_health_coverage"]
        values[f"health_only_{year}"] = m(
            claim(
                f"health_only_{year}",
                o["people"],
                "results/health_only.json",
                f"years/{year}/only_with_health_coverage/people",
            )
        )
        values[f"health_only_pct_{year}"] = (
            f"{o['share_of_count_with_health_coverage'] * 100:.1f}"
        )
        counted = read(f"results/counted_once/once_{year}.json")
        for scale in ("0.8", "0.9", "1.0", "1.1", "1.2"):
            item = (
                counted["counted_once"]
                if scale == "1.0"
                else counted["medicaid_value_scaled_counted_once"][scale]
            )
            valuation_rows.append([year, scale, m(item["people_on_cliff"], 3)])
        for measure, suffix, obj in (
            ("Cash", "plain", "as_modeled"),
            ("Health", "health", "credit_counted_once"),
        ):
            item = takeup["runs"][f"{year}_{suffix}"][obj]["groups"]["all_of_these"]
            pct = claim(
                f"takeup_pct_{year}_{suffix}",
                100 * item["share"],
                "results/take_up_bounds.json",
                f"runs/{year}_{suffix}/{obj}/groups/all_of_these/share",
                "multiply by 100",
            )
            values[f"takeup_pct_{year}_{suffix}"] = f"{pct:.1f}"
            takeup_rows.append([year, measure, f"{pct:.1f}"])
    values["table_valuation"] = table(
        "medicaid-valuation",
        ["Scenario", "Medicaid multiplier", "Health-inclusive adults (m)"],
        valuation_rows,
    )
    values["table_takeup"] = table(
        "takeup-diagnostic",
        ["Scenario", "Resource measure", "Existing flags removed (%)"],
        takeup_rows,
    )

    component_rows = []
    categories = ["medicaid_cost", "msp_cost", "chip", "assigned_aca_ptc"]
    for year in ("2017", "2025"):
        for size in (1000, 2000, 5000):
            pointer = (
                f"years/{year}/changes/raise_{size}/with_health/by_part_moving_most"
            )
            shares = d["years"][year]["changes"][f"raise_{size}"]["with_health"][
                "by_part_moving_most"
            ]
            for category in categories:
                claim(
                    f"component_share_{year}_{size}_{category}",
                    shares.get(category, 0),
                    MAIN,
                    f"{pointer}/{category}",
                )
            other = claim(
                f"component_share_{year}_{size}_other",
                1 - sum(shares.get(k, 0) for k in categories),
                MAIN,
                pointer,
                "one minus sum of four named component shares",
            )
            component_rows.append(
                [
                    year,
                    f"+${size:,}",
                    *[f"{100 * shares.get(k, 0):.1f}" for k in categories],
                    f"{100 * other:.1f}",
                ]
            )
    values["table_components"] = table(
        "largest-components",
        ["Scenario", "Raise", "Medicaid", "MSP", "CHIP", "ACA PTC", "Other"],
        component_rows,
    )

    supplementary = json.loads(
        (ROOT / "inputs/robustness/ijm_saved_robustness.json").read_text()
    )
    if supplementary["draws"] != 5000 or supplementary["seed"] != 0:
        raise ValueError("Unexpected robustness resampling settings")
    supplementary_source = "robustness/ijm_saved_robustness.json"
    record_numeric_leaves(supplementary, supplementary_source)

    def supplementary_cell(year, key, field):
        result = supplementary["years"][year]
        estimate = result["points"][key][field]
        bounds = result["interval_95"][key][field]
        return f"{m(estimate)} ({ci(bounds)})"

    union_rows = []
    valuation_rows = []
    for year in ("2017", "2025"):
        results = supplementary["years"][year]
        for config, label in (("cash", "Cash"), ("full", "Health")):
            prefix = f"{config}/current_workers/"
            strict = prefix + "union/retains_lt_0pct"
            broad = prefix + "union/retains_lt_50pct"
            extra = prefix + "additional_below_half"
            union_rows.append(
                [
                    year,
                    label,
                    *[
                        supplementary_cell(year, key, "household_members")
                        for key in (strict, broad, extra)
                    ],
                ]
            )
            for label_key, key in (
                ("strict", strict),
                ("broad", broad),
                ("additional", extra),
            ):
                values[f"union_{year}_{config}_{label_key}"] = m(
                    results["points"][key]["household_members"]
                )
                values[f"union_ci_{year}_{config}_{label_key}"] = ci(
                    results["interval_95"][key]["household_members"]
                )
        for alpha in (0, 0.3, 0.5, 1):
            config = "full" if alpha == 1 else f"medicaid_chip_a{alpha:g}"
            valuation_rows.append(
                [
                    year,
                    f"{alpha:g}",
                    *[
                        supplementary_cell(
                            year,
                            f"{config}/all_selected_adults/raise_{size}/strict",
                            "adults",
                        )
                        for size in (1000, 5000)
                    ],
                ]
            )
            for size in (1000, 5000):
                key = f"{config}/all_selected_adults/raise_{size}/strict"
                values[f"valuation_{year}_a{alpha:g}_{size}".replace(".", "_")] = m(
                    results["points"][key]["adults"]
                )
        contrast = results["paired_increment_resource_interaction"]
        values[f"interaction_{year}"] = m(contrast["adult_count_difference"])
        values[f"interaction_ci_{year}"] = ci(contrast["interval_95"])
    values["table_positive_union"] = table(
        "positive-raise-union",
        ["Scenario", "Account", "Strict loss", "Below half", "Additional"],
        union_rows,
    )
    values["table_broad_valuation"] = table(
        "broad-health-valuation",
        ["Scenario", "Multiplier α", "+$1,000 adults", "+$5,000 adults"],
        valuation_rows,
    )

    old = read("april2025/precision_summary.json")
    values["old_flagged"] = m(old["as_published"]["estimate"]["adults_on_cliff"])
    values["old_fixed"] = m(old["draws_held"]["estimate"]["adults_on_cliff"])
    values["old_fixed_ci"] = ci(old["draws_held"]["interval_95"]["adults_on_cliff"])
    values["old_ratio"] = (
        f"{old['as_published']['estimate']['adults_on_cliff'] / old['draws_held']['estimate']['adults_on_cliff']:.2f}"
    )

    if include_figures:
        plot_setup()
        fig, axes = plt.subplots(1, 2, figsize=(7.3, 3.1), sharey=True)
        for ax, year in zip(axes, ("2017", "2025")):
            for measure, color, label in (
                ("without_health", SLATE, "Cash and near-cash"),
                ("with_health", TEAL, "Including health"),
            ):
                x = [1, 2, 5]
                items = [
                    d["years"][year]["changes"][f"raise_{i * 1000}"][measure] for i in x
                ]
                y = [a["people_on_cliff"] / 1e6 for a in items]
                lo = [(a["people_on_cliff"] - a["interval_95"][0]) / 1e6 for a in items]
                hi = [(a["interval_95"][1] - a["people_on_cliff"]) / 1e6 for a in items]
                offset = -0.06 if measure == "without_health" else 0.06
                ax.errorbar(
                    [v + offset for v in x],
                    y,
                    yerr=[lo, hi],
                    fmt="o",
                    color=color,
                    capsize=3,
                    markersize=5,
                    label=label,
                )
            ax.set(
                title=f"{year} policy scenario",
                xlabel="Annual earnings increase ($000s)",
                xticks=[1, 2, 5],
                ylim=(0, 11.3),
            )
            ax.yaxis.grid(True, color=GRAY, linewidth=0.6)
            ax.set_axisbelow(True)
        axes[0].set_ylabel("Selected adults with an endpoint loss (millions)")
        axes[1].legend(frameon=False, fontsize=9, loc="upper left")
        fig.tight_layout()
        save(fig, "fixed-raises")

        fig, axes = plt.subplots(1, 2, figsize=(7.3, 3.5), sharey=True)
        categories = ["medicaid_cost", "msp_cost", "chip", "assigned_aca_ptc"]
        labels = [
            "Medicaid",
            "Medicare Savings Programs",
            "CHIP",
            "ACA premium tax credit",
            "Other",
        ]
        colors = [TEAL, DARK_TEAL, BLUE, "#026AA2", SLATE]  # --chart-1,3,2,4,5
        for ax, year in zip(axes, ("2017", "2025")):
            bottom = [0.0, 0.0, 0.0]
            shares = [
                d["years"][year]["changes"][f"raise_{n}"]["with_health"][
                    "by_part_moving_most"
                ]
                for n in (1000, 2000, 5000)
            ]
            for key, label, color in zip([*categories, "other"], labels, colors):
                heights = [
                    100
                    * (
                        1 - sum(s.get(k, 0) for k in categories)
                        if key == "other"
                        else s.get(key, 0)
                    )
                    for s in shares
                ]
                ax.bar(
                    [0, 1, 2],
                    heights,
                    bottom=bottom,
                    color=color,
                    label=label,
                    width=0.55,
                )
                bottom = [a + b for a, b in zip(bottom, heights)]
            ax.set(
                title=f"{year} policy scenario",
                xticks=[0, 1, 2],
                xticklabels=["+$1,000", "+$2,000", "+$5,000"],
                ylim=(0, 100),
                xlabel="Annual earnings increase",
            )
        axes[0].set_ylabel("Share by largest adverse component (%)")
        handles, labels = axes[1].get_legend_handles_labels()
        fig.legend(
            handles,
            labels,
            loc="lower center",
            ncol=3,
            frameon=False,
            fontsize=8.5,
            bbox_to_anchor=(0.5, -0.06),
        )
        fig.tight_layout(rect=(0, 0.12, 1, 1))
        save(fig, "largest-loss")

        fig, axes = plt.subplots(1, 2, figsize=(7.3, 3.1), sharey=True)
        for ax, year in zip(axes, ("2017", "2025")):
            for measure, color, label in (
                ("without_health", SLATE, "Cash and near-cash"),
                ("with_health", TEAL, "Including health"),
            ):
                heights = []
                for size in ("1000", "2000", "5000", "1pct", "10pct"):
                    item = d["years"][year]["changes"][f"raise_{size}"][measure]
                    heights.append(
                        100
                        * item["net_income_moves_12_or_less"]["adults"]
                        / item["people_on_cliff"]
                    )
                offset = -0.18 if measure == "without_health" else 0.18
                ax.bar(
                    [i + offset for i in range(5)],
                    heights,
                    width=0.33,
                    color=color,
                    label=label,
                )
            ax.set(
                title=f"{year} policy scenario",
                xticks=range(5),
                xticklabels=["$1,000", "$2,000", "$5,000", "1%", "10%"],
                xlabel="Annual raise",
                ylim=(0, 30),
            )
            ax.yaxis.grid(True, color=GRAY, linewidth=0.6)
            ax.set_axisbelow(True)
        axes[0].set_ylabel("Flagged adults with a loss of $12 or less (%)")
        axes[1].legend(frameon=False, fontsize=9)
        fig.tight_layout()
        save(fig, "small-losses")

    for key in (
        "table_fixed",
        "table_workers",
        "table_components",
        "table_positive_union",
        "table_broad_valuation",
    ):
        lines = values[key].splitlines()
        selected = lines[:2] + [
            line for line in lines[2:] if line.startswith("| 2025 |")
        ]
        values[f"{key}_main"] = "\n".join(selected) + "\n"
        (ROOT / "tables" / f"{key.removeprefix('table_')}-2025.md").write_text(
            values[f"{key}_main"]
        )

    (ROOT / "paper_metrics.json").write_text(json.dumps(CLAIMS, indent=2) + "\n")
    (ROOT / "template_values.json").write_text(json.dumps(values, indent=2) + "\n")
    (ROOT / "checks" / "assets.json").write_text(
        json.dumps(
            checked
            | {
                "summary_draws": d["draws"],
                "claims_recorded": len(CLAIMS),
                "figures": 3 if include_figures else 0,
                "tables": sum(key.startswith("table_") for key in values),
            },
            indent=2,
        )
        + "\n"
    )
    print(
        json.dumps(
            checked
            | {
                "claims_recorded": len(CLAIMS),
                "figures": 3 if include_figures else 0,
                "tables": sum(key.startswith("table_") for key in values),
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--refresh-from",
        type=Path,
        help="Read snapshots at the fixed commit from this Git repository",
    )
    parser.add_argument(
        "--include-figures",
        action="store_true",
        help="Also regenerate the archived two-scenario working-paper plots",
    )
    args = parser.parse_args()
    if args.refresh_from:
        refresh(args.refresh_from)
    build(include_figures=args.include_figures)
