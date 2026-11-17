"""Calculate and draw a SNAP model-boundary illustration for one household.

Use the released household environment for compute-zoom and the figure hashlock
for render. Neither command uses a population dataset. Keep full API receipts
outside the repository. The figure distinguishes a model response from Texas's
published eligibility chart.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
TEAL = "#319795"  # PolicyEngine --chart-1
SLATE = "#475569"  # --muted-foreground
BORDER = "#E2E8F0"  # --border
ENTITY_KEYS = {
    "Person": "person",
    "MaritalUnit": "marital_unit",
    "Family": "family",
    "SPMUnit": "spm_unit",
    "TaxUnit": "tax_unit",
    "Household": "household",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def total(result: Mapping, variable: str, entity: str) -> list[float]:
    """Sum native members of this single household, without survey weights."""
    records = result[ENTITY_KEYS[entity]]
    records = [records] if isinstance(records, Mapping) else records
    vectors = [record[variable] for record in records]
    require(bool(vectors), f"Missing output: {variable}")
    for vector in vectors:
        require(isinstance(vector, list) and len(vector) == 201, variable)
        require(
            all(type(v) in (int, float) and math.isfinite(v) for v in vector),
            f"Nonfinite output: {variable}",
        )
    return [math.fsum(v[i] for v in vectors) for i in range(201)]


def identity(actual: list[float], expected: list[float], name: str) -> float:
    residual = max(abs(a - b) for a, b in zip(actual, expected, strict=True))
    require(residual <= 0.05, f"{name}: residual {residual}")
    return residual


def compute_zoom(args: argparse.Namespace) -> None:
    require(sys.flags.isolated == 1, "Use Python -I")
    require(sys.version_info[:3] == (3, 14, 7), "Use Python3.14.7")
    require(not args.receipt.exists() and not args.csv.exists(), "Existing output")
    require(
        "POLICYENGINE_US_DATA_MANIFEST_FILE" not in os.environ,
        "Custom manifests fall outside this illustration",
    )
    config = json.loads(args.config.read_text())
    versions = {name: metadata.version(name) for name in config["versions"]}
    require(versions == config["versions"], "Unexpected runtime versions")
    request = config["scenarios"]["single_parent"]["request"]
    require(request["year"] == 2025 and "reform" not in request, "2025 baseline")
    require(len(request["axes"]) == 1, "One paired axis group")
    axes = request["axes"][0]
    require(len(axes) == 2, "Exactly two paired axes")
    require([axis["count"] for axis in axes] == [201, 201], "201 paired points")
    require((axes[0]["min"], axes[0]["max"]) == (33650, 33850), "Zoom bounds")
    require(
        request["spm_unit"][0]["takes_up_tanf_if_eligible"] is False,
        "The parent does not participate in cash TANF",
    )

    import policyengine as pe

    # Exactly one genuine public API call. No tax/benefit formulas live here.
    result = pe.us.calculate_household(**request)
    columns = {
        name: total(result, name, entity)
        for name, entity in config["output_entities"].items()
    }
    require(len(result["person"]) == 2, "Expected parent and child")
    for i, person in enumerate(result["person"]):
        for j, actual in enumerate(person["employment_income"]):
            expected = 33650 + j if i == 0 else 0
            require(math.isclose(actual, expected, abs_tol=0.01), "Earnings axis")
    hours = result["person"][0]["weekly_hours_worked_before_lsr"]
    for i, actual in enumerate(hours):
        require(
            math.isclose(actual, (33650 + i) / (30 * 52), abs_tol=0.00001),
            "Hours/earnings axes did not zip201 points",
        )
    residuals = {}
    targets = {
        "market_income": "household_market_income",
        "benefits": "household_benefits",
        "tax_before_refundable_credits": "household_tax_before_refundable_credits",
        "refundable_tax_credits": "household_refundable_tax_credits",
    }
    for account, target in targets.items():
        expected = [
            math.fsum(columns[name][i] for name in config["accounts"][account])
            for i in range(201)
        ]
        residuals[account] = identity(columns[target], expected, account)
    residuals["net_tax"] = identity(
        columns["household_tax"],
        [
            columns[targets["tax_before_refundable_credits"]][i]
            - columns[targets["refundable_tax_credits"]][i]
            for i in range(201)
        ],
        "net tax",
    )
    expected = [
        columns["household_market_income"][i]
        + columns["household_benefits"][i]
        + columns["household_refundable_tax_credits"][i]
        - columns["household_tax_before_refundable_credits"][i]
        - columns["household_health_costs"][i]
        for i in range(201)
    ]
    residuals["net_resources"] = identity(
        columns["household_net_income"], expected, "net resources"
    )
    require(all(v == 0 for v in columns["tanf"]), "Cash TANF must remain zero")
    require(all(v == 0 for v in columns["household_health_costs"]), "Health scope")
    spm = result["provenance"]["spm"]
    require(set(spm["years"]) == {"2025"}, "SPM calculation year")
    require(spm["geography_kind"] == "national", "SPM geography")
    require(spm["scenario"] == "ce_trend", "SPM scenario")
    require(spm["forecast_sha256"] == config["spm_content_sha256"], "SPM hash")
    require(spm["runtime_versions"] == versions, "SPM runtime inventory")
    receipt = {
        "classification": "GENUINE_MODEL_ILLUSTRATION__LEGAL_BOUNDARY_UNQUALIFIED",
        "utc": datetime.now(UTC).isoformat(),
        "API_calls": 1,
        "rows": 201,
        "versions": versions,
        "config_sha256": sha(args.config),
        "script_sha256": sha(Path(__file__)),
        "identity_max_abs_residual_USD": residuals,
        "result": result,
    }
    with args.receipt.open("x") as handle:
        json.dump(receipt, handle, indent=2, allow_nan=False)
        handle.write("\n")
    names = sorted(columns)
    with args.csv.open("x", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["scenario", "year", *names])
        writer.writeheader()
        for i in range(201):
            writer.writerow(
                {
                    "scenario": "single_parent_tanf_nonparticipant_zoom",
                    "year": 2025,
                    **{name: columns[name][i] for name in names},
                }
            )
    print(json.dumps({"API_calls": 1, "rows": 201, "identities": residuals}))


def read_curve(path: Path) -> list[dict[str, float]]:
    with path.open() as handle:
        rows = list(csv.DictReader(handle))
    result = []
    for row in rows:
        require(int(row["year"]) == 2025, "Data year")
        result.append(
            {
                key: float(row[key])
                for key in (
                    "employment_income",
                    "household_net_income",
                    "snap",
                    "tanf",
                )
            }
        )
    require(all(row["tanf"] == 0 for row in result), "TANF participation changed")
    return result


def render(args: argparse.Namespace) -> None:
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import font_manager, pyplot as plt, ticker

    require(metadata.version("matplotlib") == "3.11.2", "Pinned plotting runtime")
    if args.font is not None:
        font_manager.fontManager.addfont(args.font)
        font_name = font_manager.FontProperties(fname=args.font).get_name()
    else:
        font_name = (
            "Inter"
            if any(f.name == "Inter" for f in font_manager.fontManager.ttflist)
            else "DejaVu Sans"
        )  # Match the existing journal-figure fallback when Inter is unavailable.
        font_manager.findfont(font_name, fallback_to_default=False)
    base = read_curve(args.base_csv)
    zoom = read_curve(args.zoom_csv)
    require(len(base) == 61 and len(zoom) == 201, "Actual61+201 data rows")
    require(
        [r["employment_income"] for r in zoom] == list(range(33650, 33851)),
        "The figure requires genuine1-dollar zoom observations",
    )
    drops = [
        (a, b)
        for a, b in zip(zoom, zoom[1:])
        if b["household_net_income"] - a["household_net_income"] < -50
    ]
    require(len(drops) == 1, "Expect one large observed drop within this zoom")
    before, after = drops[0]
    delta = after["household_net_income"] - before["household_net_income"]
    snap_delta = after["snap"] - before["snap"]
    combined = sorted(
        {row["employment_income"]: row for row in base + zoom}.values(),
        key=lambda row: row["employment_income"],
    )
    plt.rcParams.update(
        {
            "font.family": font_name,
            "font.size": 8.5,
            "text.color": SLATE,
            "axes.labelcolor": SLATE,
            "axes.edgecolor": BORDER,
            "xtick.color": SLATE,
            "ytick.color": SLATE,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "svg.fonttype": "path",
        }
    )
    fig, axes = plt.subplots(1, 2, figsize=(6.8, 5.4))
    fig.subplots_adjust(left=0.15, right=0.94, bottom=0.35, top=0.78, wspace=0.48)
    fig.text(0.15, 0.93, "Illustrative model outputs", fontsize=13, weight="bold")
    fig.text(
        0.15,
        0.872,
        "Single parent, age 40, and child, age 4, Harris County, Texas",
        fontsize=9,
    )
    fig.text(
        0.15,
        0.827,
        "2025 nominal annual dollars; resources exclude health benefits; TANF not claimed",
        fontsize=8,
    )

    def draw(ax, rows):
        segments = [[]]
        for row in rows:
            if segments[-1]:
                previous = segments[-1][-1]
                if (previous["employment_income"], row["employment_income"]) == (
                    before["employment_income"],
                    after["employment_income"],
                ):
                    segments.append([])
            segments[-1].append(row)
        for segment in segments:
            ax.plot(
                [r["employment_income"] for r in segment],
                [r["household_net_income"] for r in segment],
                color=TEAL,
                linewidth=1.15,
                marker="o",
                markersize=1.4,
            )
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", color=BORDER, linewidth=0.55)
        ax.set_axisbelow(True)
        ax.tick_params(length=3, width=0.6)
        ax.set_xlabel("Annual earnings ($)", labelpad=8)
        ax.xaxis.set_major_formatter(ticker.StrMethodFormatter("{x:,.0f}"))
        ax.yaxis.set_major_formatter(ticker.StrMethodFormatter("{x:,.0f}"))

    draw(axes[0], combined)
    draw(axes[1], zoom)
    axes[0].set(title="A  Earnings range", xlim=(0, 60000), ylim=(0, 60000))
    axes[0].set_xticks([0, 20000, 40000, 60000])
    axes[0].set_yticks([0, 15000, 30000, 45000, 60000])
    axes[0].set_ylabel("Annual household resources ($)", labelpad=8)
    axes[1].set_title("B  Annual resource drop")
    axes[1].set_xlim(33650, 33850)
    axes[1].set_ylim(
        min(r["household_net_income"] for r in zoom) - 65,
        max(r["household_net_income"] for r in zoom) + 110,
    )
    axes[1].set_xticks([33650, 33750, 33850])
    axes[1].yaxis.set_major_locator(ticker.MaxNLocator(4))
    axes[1].text(
        0.04,
        0.96,
        f"+$1 earnings\n−${-delta:,.2f} resources",
        transform=axes[1].transAxes,
        va="top",
        fontsize=8,
    )
    axes[1].scatter(
        [before["employment_income"], after["employment_income"]],
        [before["household_net_income"], after["household_net_income"]],
        s=16,
        color=TEAL,
        zorder=4,
    )
    figure_notes = [
        (0.235, "Calendar 2025 SNAP: Jan–Sep FY2025; Oct–Dec FY2026."),
        (0.195, "Fiscal-year attribution inferred from annual totals and dated rules."),
        (0.155, "At $33,727 earnings, annual SNAP falls from $597 to $183."),
        (
            0.115,
            "FY2025 categorical gross limit: Texas $2,811/month; PolicyEngine $2,810.50/month.",
        ),
        (
            0.075,
            "This model illustration does not establish the exact Texas legal cutoff.",
        ),
        (0.025, "Sources: PolicyEngine 6.19.0; Texas HHSC Bulletin 24-12, p. 5."),
    ]
    for y, note in figure_notes:
        fig.text(0.15, y, note, fontsize=8, parse_math=False)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    labels = list(fig.texts)
    for ax in axes:
        labels.extend([ax.xaxis.label, ax.yaxis.label, ax.title])
        for value, label in zip(ax.get_xticks(), ax.get_xticklabels()):
            if ax.get_xlim()[0] <= value <= ax.get_xlim()[1]:
                labels.append(label)
        for value, label in zip(ax.get_yticks(), ax.get_yticklabels()):
            if ax.get_ylim()[0] <= value <= ax.get_ylim()[1]:
                labels.append(label)
    for label in labels:
        if label.get_visible() and label.get_text():
            box = label.get_window_extent(renderer)
            require(
                box.x0 >= 0
                and box.y0 >= 0
                and box.x1 <= fig.bbox.width
                and box.y1 <= fig.bbox.height,
                f"Clipped figure label: {label.get_text()}",
            )
    stem = args.output_stem
    stem.parent.mkdir(parents=True, exist_ok=True)
    for fmt in ("png", "pdf", "svg"):
        require(not stem.with_suffix("." + fmt).exists(), "Existing figure output")
        fig.savefig(
            stem.with_suffix("." + fmt),
            dpi=300,
            facecolor="white",
            metadata={"Creator": "PolicyEngine model illustration"}
            if fmt == "pdf"
            else {},
        )
    plt.close(fig)
    caption = (
        "Illustrative model outputs. We calculate 2025 annual resources for a 40-year-old "
        "single parent and a 4-year-old dependent in Harris County, Texas. The parent earns "
        "$30 per hour over 52 weeks; hours rise with earnings. The parent does not claim cash "
        "Temporary Assistance for Needy Families (TANF). Resources exclude health benefits "
        "and include noncash food benefits through the Supplemental Nutrition Assistance "
        "Program (SNAP) and the Special Supplemental Nutrition Program for Women, Infants, "
        "and Children (WIC). The "
        "[configuration](../examples/snap_model_boundary_zoom_2025.json) records rent, "
        "utilities, assets, coverage and other claiming assumptions. We calculate 61 points "
        "over $0–$60,000 and 201 points over $33,650–$33,850; lines join calculated points and "
        "break across the observed drop. "
        f"Between ${before['employment_income']:,.0f} and ${after['employment_income']:,.0f} "
        f"of earnings, we calculate annual resources falling ${-delta:,.2f} and annual SNAP "
        "falling from $597 to $183. "
        "USDA's tables set FY2025 limits for January–September and FY2026 limits for "
        "October–December in calendar 2025. We infer from these dates and annual totals "
        "that the FY2025 months lose SNAP at this jump and the three FY2026 months retain it; "
        "we did not calculate monthly amounts. We calculate annual SNAP of $159 at $34,000 "
        "and zero at $35,000 on the coarse grid, without locating the later change at $1 resolution. "
        "Texas's Health and Human Services Commission publishes a $2,811 monthly categorical "
        "gross-income limit for a two-person household in FY2025; PolicyEngine applies "
        "$2,810.50. This model illustration does not establish the exact Texas legal cutoff. "
        "[Texas HHSC Bulletin 24-12](https://fhb.hhs.texas.gov/sites/default/files/documents/"
        "mepd-and-twh-Bulletin-24-12.pdf#page=5) supplies the published 165% categorical limit. "
        "PolicyEngine 6.19.0 uses US 2.2.1, Core 3.33.3 and spm-calculator 1.0.0 for these calculations.\n"
    )
    stem.with_suffix(".caption.md").write_text(caption)
    report = {
        "classification": "ILLUSTRATIVE_MODEL_OUTPUTS__LEGAL_QUALIFICATION_HOLD",
        "base_csv_sha256": sha(args.base_csv),
        "zoom_csv_sha256": sha(args.zoom_csv),
        "base_rows": 61,
        "zoom_rows": 201,
        "combined_distinct_rows": len(combined),
        "observed_before": before,
        "observed_after": after,
        "observed_resource_change": delta,
        "observed_SNAP_change": snap_delta,
        "gap_breaks_function_line": True,
        "analytic_limits_or_open_endpoints": False,
        "interpolated_output_rows": 0,
        "nominal_currency_year": 2025,
        "fiscal_year_attribution": "INFERRED from observed annual totals, dated fiscal-year rules and calendar arithmetic; monthly amounts not calculated.",
        "font": font_name,
        "figure_inches": [6.8, 5.4],
        "dpi": 300,
        "matplotlib": metadata.version("matplotlib"),
        "python": sys.version,
        "caption_sha256": sha(stem.with_suffix(".caption.md")),
    }
    stem.with_suffix(".provenance.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    compute = commands.add_parser("compute-zoom")
    compute.add_argument("--config", type=Path, required=True)
    compute.add_argument("--receipt", type=Path, required=True)
    compute.add_argument("--csv", type=Path, required=True)
    plot = commands.add_parser("render")
    plot.add_argument("--base-csv", type=Path, required=True)
    plot.add_argument("--zoom-csv", type=Path, required=True)
    plot.add_argument("--output-stem", type=Path, required=True)
    plot.add_argument("--font", type=Path)
    args = parser.parse_args()
    (compute_zoom if args.command == "compute-zoom" else render)(args)


if __name__ == "__main__":
    main()
