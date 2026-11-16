"""Draw scientific figures from actual frozen-model outputs and aggregates.

This renderer computes no tax/benefit scenario. Household points must come from
paper_household_curves.py; population figures read verified aggregate snapshots.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from build_assets import GRAY, INK, SLATE, TEAL, plot_setup, read, verify
from matplotlib.ticker import FuncFormatter

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "figures"


def dollars_thousands(x, _):
    return f"{'−' if x < 0 else ''}${abs(x) / 1000:,.0f}k"


def save(fig, name):
    fig.savefig(OUT / f"{name}.png", dpi=300, bbox_inches="tight")
    fig.savefig(OUT / f"{name}.svg", bbox_inches="tight", metadata={"Date": None})
    plt.close(fig)


def common(ax):
    ax.grid(axis="y", color=GRAY, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.tick_params(length=3)


def aggregate_figures():
    """Plot counts at computed raise sizes and health valuations, with intervals."""
    experiments = read("results/earnings_changes.json")
    fig, ax = plt.subplots(figsize=(5.5, 3.5))
    axes = [ax]
    for ax, year in zip(axes, ("2025",)):
        for resource, color, marker, label in (
            ("without_health", SLATE, "s", "Cash and near-cash"),
            ("with_health", TEAL, "o", "With government-valued health"),
        ):
            items = [
                experiments["years"][year]["changes"][f"raise_{n}"][resource]
                for n in (1000, 2000, 5000)
            ]
            y = [item["people_on_cliff"] / 1e6 for item in items]
            low = [
                (item["people_on_cliff"] - item["interval_95"][0]) / 1e6
                for item in items
            ]
            high = [
                (item["interval_95"][1] - item["people_on_cliff"]) / 1e6
                for item in items
            ]
            ax.errorbar(
                [1, 2, 5],
                y,
                yerr=[low, high],
                fmt=marker,
                color=color,
                capsize=3,
                markersize=5,
                label=label,
            )
        ax.set(
            title="2017-oriented scenario" if year == "2017" else "2025 scenario",
            xticks=[1, 2, 5],
            xticklabels=["$1,000", "$2,000", "$5,000"],
            ylim=(0, 11),
        )
        ax.set_xlabel("Annual earnings increase")
        common(ax)
    axes[0].set_ylabel("Selected adults with a resource loss\n(millions)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2, frameon=False, fontsize=10)
    fig.tight_layout(rect=(0, 0.1, 1, 1))
    save(fig, "increment-exposure")

    result = json.loads(
        (ROOT / "inputs/robustness/ijm_saved_robustness.json").read_text()
    )
    fig, ax = plt.subplots(figsize=(5.5, 3.5))
    axes = [ax]
    alphas = [0, 0.3, 0.5, 1]
    for ax, year in zip(axes, ("2025",)):
        for size, color, marker, label in (
            (1000, SLATE, "s", "+$1,000"),
            (5000, TEAL, "o", "+$5,000"),
        ):
            keys = [
                f"{'full' if a == 1 else f'medicaid_chip_a{a:g}'}/all_selected_adults/raise_{size}/strict"
                for a in alphas
            ]
            yr = result["years"][year]
            y = [yr["points"][k]["adults"] / 1e6 for k in keys]
            low = [
                (yr["points"][k]["adults"] - yr["interval_95"][k]["adults"][0]) / 1e6
                for k in keys
            ]
            high = [
                (yr["interval_95"][k]["adults"][1] - yr["points"][k]["adults"]) / 1e6
                for k in keys
            ]
            # Separate points: no claim about untested intermediate valuations.
            ax.errorbar(
                alphas,
                y,
                yerr=[low, high],
                fmt=marker,
                color=color,
                capsize=3,
                markersize=5,
                label=label,
            )
        ax.set(
            title="2017-oriented scenario" if year == "2017" else "2025 scenario",
            xticks=alphas,
            xticklabels=["0%", "30%", "50%", "100%"],
            ylim=(0, 11),
        )
        ax.set_xlabel("Medicaid and CHIP value\n(as a share of government cost)")
        common(ax)
    axes[0].set_ylabel("Selected adults with a resource loss\n(millions)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2, frameon=False, fontsize=10)
    fig.tight_layout(rect=(0, 0.11, 1, 1))
    save(fig, "health-valuation-exposure")


def merged_case_points(case):
    """Use computed axis points and fresh scalar points, never interpolate values."""
    curve = case["curve"]
    rows = {
        float(x): (float(y), float(z))
        for x, y, z in zip(
            curve["earnings"],
            curve["resources_cash"],
            curve["resources_full_health"],
            strict=True,
        )
    }
    for point in case["independently_run_points"].values():
        key = float(point["earnings"][0])
        value = (
            float(point["resources_cash"][0]),
            float(point["resources_full_health"][0]),
        )
        if key in rows and not np.allclose(rows[key], value, atol=0.01, rtol=0):
            raise ValueError("Scalar/axis mismatch in figure inputs")
        rows[key] = value
    earnings = np.array(sorted(rows))
    cash = np.array([rows[x][0] for x in earnings])
    health = np.array([rows[x][1] for x in earnings])
    return earnings, cash, health


def household_figure(case, name, title, labels):
    earnings, cash, health = merged_case_points(case)
    fig, ax = plt.subplots(figsize=(5.5, 3.75))
    for event in case["annotations"]:
        start = event["sampled_bracket"][0]
        recovery = event["sampled_recovery_earnings_bracket"]
        end = recovery[1] if recovery is not None else earnings[-1]
        ax.axvspan(start, end, color=TEAL, alpha=0.11, linewidth=0)
    ax.plot(
        earnings,
        cash,
        color=SLATE,
        linestyle="--",
        linewidth=1.6,
        label="Cash and near-cash",
    )
    ax.plot(
        earnings,
        health,
        color=TEAL,
        linewidth=1.8,
        label="With government-valued health",
    )
    for i, (event, label) in enumerate(zip(case["annotations"], labels, strict=True)):
        point = event["sampled_change"]["before"]
        x, y = point["earnings"], point["resources_full_health"]
        ax.scatter([x], [y], color=TEAL, s=23, zorder=5)
        shift = (12, 18) if len(labels) == 1 else ((-58, 26), (-12, 40), (25, -28))[i]
        ax.annotate(
            label,
            (x, y),
            xytext=shift,
            textcoords="offset points",
            fontsize=9,
            ha="left",
            arrowprops={"arrowstyle": "-", "color": INK, "linewidth": 0.6},
        )
    ax.set(
        title=title,
        xlabel="Annual employment earnings",
        ylabel="Annual household resources",
        xlim=(0, earnings[-1]),
        ylim=(0, max(health.max(), cash.max()) * 1.07),
    )
    ax.xaxis.set_major_formatter(FuncFormatter(dollars_thousands))
    ax.yaxis.set_major_formatter(FuncFormatter(dollars_thousands))
    common(ax)
    handles, names = ax.get_legend_handles_labels()
    fig.legend(handles, names, loc="lower center", frameon=False, ncol=1, fontsize=9)
    fig.tight_layout(rect=(0, 0.14, 1, 1))
    save(fig, name)


def endpoint_figure(case):
    event = case["annotations"][0]
    baseline = event["sampled_change"]["before"]
    earnings, cash, health = merged_case_points(case)
    mask = (earnings >= baseline["earnings"]) & (
        earnings <= baseline["earnings"] + 6000
    )
    extra = earnings[mask] - baseline["earnings"]
    fig, ax = plt.subplots(figsize=(5.5, 3.55))
    ax.axhline(0, color=INK, linewidth=0.7)
    ax.plot(
        extra,
        cash[mask] - baseline["resources_cash"],
        color=SLATE,
        linestyle="--",
        linewidth=1.6,
        label="Cash and near-cash",
    )
    ax.plot(
        extra,
        health[mask] - baseline["resources_full_health"],
        color=TEAL,
        linewidth=1.8,
        label="With government-valued health",
    )
    for amount in (1000, 5000):
        value = event["raise_comparisons"][str(amount)]["full_resource_change"]
        ax.scatter([amount], [value], s=28, color=TEAL, zorder=5)
        label = f"+${amount:,} earnings\n{'−' if value < 0 else '+'}${abs(value):,.0f} resources"
        ax.annotate(
            label,
            (amount, value),
            xytext=(0, 18),
            ha="center",
            va="bottom",
            textcoords="offset points",
            fontsize=9,
            color=INK,
        )
    ax.set(
        title="The raise size changes the endpoint result",
        xlabel="Additional annual earnings",
        ylabel="Change in annual household resources",
        xlim=(0, 6000),
    )
    ax.xaxis.set_major_formatter(FuncFormatter(dollars_thousands))
    ax.yaxis.set_major_formatter(FuncFormatter(dollars_thousands))
    common(ax)
    handles, names = ax.get_legend_handles_labels()
    fig.legend(handles, names, loc="lower center", frameon=False, ncol=1, fontsize=9)
    fig.tight_layout(rect=(0, 0.15, 1, 1))
    save(fig, "household-endpoints-2025")


def build():
    verify()
    OUT.mkdir(exist_ok=True)
    plot_setup()
    plt.rcParams["svg.hashsalt"] = "benefit-cliffs-finite-earnings"
    aggregate_figures()
    path = ROOT / "inputs/household-curves/paper_household_curves.json"
    receipt = json.loads((path.parent / "manifest.json").read_text())
    if hashlib.sha256(path.read_bytes()).hexdigest() != receipt["sha256"]:
        raise ValueError("Hypothetical household snapshot changed")
    cases = json.loads(path.read_text())["cases"]
    household_figure(
        cases["single_2025"],
        "household-single-2025",
        "Single adult, age 50 · North Carolina · 2025",
        ["Medicaid to ACA"],
    )
    household_figure(
        cases["parent_2025"],
        "household-parent-2025",
        "Parent, age 35; children, ages 8 and 12 · NC · 2025",
        ["Adult Medicaid to ACA", "School meals", "Children Medicaid to ACA"],
    )
    household_figure(
        cases["aca_2017"],
        "household-aca-hybrid-2017",
        "Mixed 2017-oriented sensitivity · single adult, age 50",
        ["Modeled ACA cutoff"],
    )
    endpoint_figure(cases["single_2025"])
    stems = {
        "increment-exposure",
        "health-valuation-exposure",
        "household-single-2025",
        "household-parent-2025",
        "household-aca-hybrid-2017",
        "household-endpoints-2025",
    }
    outputs = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(OUT.glob("*"))
        if p.stem in stems
    }
    report = {
        "renderer": "Matplotlib",
        "source": "Model-calculated hypothetical points and verified aggregate snapshots",
        "files": outputs,
        "figure_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "household_source_sha256": receipt["sha256"],
        "input_sources": {
            name: hashlib.sha256((ROOT / "inputs" / name).read_bytes()).hexdigest()
            for name in (
                "household-curves/paper_household_curves.json",
                "results/earnings_changes.json",
                "robustness/ijm_saved_robustness.json",
            )
        },
        "primary_year": 2025,
        "historical_hybrid": "Appendix only",
        "curve_points": "All axis and merged scalar points were evaluated; straight connections are visual guides, not additional model runs",
    }
    (ROOT / "checks/figure-provenance.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )


if __name__ == "__main__":
    build()
