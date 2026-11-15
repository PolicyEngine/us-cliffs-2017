"""Draw three explicitly constructed earnings/net-income functions.

All parameters below are hypothetical exposition choices. This script does not
import PolicyEngine, read microdata or reproduce any actual tax-benefit schedule.
Run --check-only with standard-library Python to verify the mathematical contract.
The default command additionally requires an existing Matplotlib environment.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import platform
import sys
from itertools import pairwise
from pathlib import Path

CONSTRUCTED_BENEFIT_USD = 5_000.0
CONSTRUCTED_THRESHOLD_USD = 30_000.0
CONSTRUCTED_TAX_RATE = 0.2
CONSTRUCTED_WITHDRAWAL_RATE = 0.5
EARNINGS_MAX_USD = 60_000.0
FIGURE_SIZE_INCHES = (6.8, 4.2)
DPI = 300

# PolicyEngine design tokens; Python charts reference the token values directly.
TEAL = "#319795"  # --chart-1
SLATE = "#475569"  # --muted-foreground
BORDER = "#E2E8F0"  # --border
INK = "#101828"  # --color-gray-900

CAPTION = (
    "Constructed illustration. The hypothetical benefit and refundable tax credit "
    "give identical net income, with a $5,000 drop immediately above $30,000 of "
    "annual earnings. The continuous benefit taper changes slope at $30,000 and "
    "$40,000 without a downward jump. Filled circles mark included endpoints; "
    "open circles mark excluded branch limits. "
    "For notch terminology, see Kleven and Waseem (2013), Quarterly Journal of "
    "Economics 128(2), 669-723: https://doi.org/10.1093/qje/qjt004."
)


def constructed_step_benefit(earnings: float) -> float:
    return CONSTRUCTED_BENEFIT_USD if earnings <= CONSTRUCTED_THRESHOLD_USD else 0.0


def constructed_base_tax(earnings: float) -> float:
    return CONSTRUCTED_TAX_RATE * earnings


def constructed_refundable_tax(earnings: float) -> float:
    return constructed_base_tax(earnings) - constructed_step_benefit(earnings)


def constructed_continuous_benefit(earnings: float) -> float:
    excess = max(earnings - CONSTRUCTED_THRESHOLD_USD, 0.0)
    return max(CONSTRUCTED_BENEFIT_USD - CONSTRUCTED_WITHDRAWAL_RATE * excess, 0.0)


def constructed_net_a(earnings: float) -> float:
    return (
        earnings - constructed_base_tax(earnings) + constructed_step_benefit(earnings)
    )


def constructed_net_b(earnings: float) -> float:
    return earnings - constructed_refundable_tax(earnings)


def constructed_net_c(earnings: float) -> float:
    return (
        earnings
        - constructed_base_tax(earnings)
        + constructed_continuous_benefit(earnings)
    )


def verify_constructed_functions() -> dict:
    """Check identities, one-sided limits, inclusivity, slopes and continuity."""
    threshold = CONSTRUCTED_THRESHOLD_USD
    taper_end = threshold + (CONSTRUCTED_BENEFIT_USD / CONSTRUCTED_WITHDRAWAL_RATE)
    grid = sorted(
        {float(y) for y in range(0, int(EARNINGS_MAX_USD) + 1, 10)}
        | {
            math.nextafter(threshold, -math.inf),
            threshold,
            math.nextafter(threshold, math.inf),
            math.nextafter(taper_end, -math.inf),
            taper_end,
            math.nextafter(taper_end, math.inf),
        }
    )
    differences = [abs(constructed_net_a(y) - constructed_net_b(y)) for y in grid]
    tolerance_usd = 1e-9
    assert max(differences) <= tolerance_usd
    left = (1 - CONSTRUCTED_TAX_RATE) * threshold + CONSTRUCTED_BENEFIT_USD
    right = (1 - CONSTRUCTED_TAX_RATE) * threshold
    assert left - right == CONSTRUCTED_BENEFIT_USD == 5_000
    assert constructed_net_a(threshold) == constructed_net_b(threshold) == left
    for function in (constructed_net_a, constructed_net_b):
        assert math.isclose(
            function(math.nextafter(threshold, math.inf)),
            right,
            rel_tol=0,
            abs_tol=tolerance_usd,
        )
    # Each analytic branch reaches the same endpoint at each kink.
    left_at_start = threshold - constructed_base_tax(threshold) + 5_000
    middle_at_start = (
        threshold
        - constructed_base_tax(threshold)
        + max(5_000 - 0.5 * (threshold - 30_000), 0)
    )
    middle_at_end = (
        taper_end
        - constructed_base_tax(taper_end)
        + max(5_000 - 0.5 * (taper_end - 30_000), 0)
    )
    right_at_end = taper_end - constructed_base_tax(taper_end)
    assert left_at_start == middle_at_start == constructed_net_c(threshold)
    assert middle_at_end == right_at_end == constructed_net_c(taper_end)
    for kink in (threshold, taper_end):
        for direction in (-math.inf, math.inf):
            assert math.isclose(
                constructed_net_c(math.nextafter(kink, direction)),
                constructed_net_c(kink),
                rel_tol=0,
                abs_tol=tolerance_usd,
            )
    c_values = [constructed_net_c(y) for y in grid]
    assert all(b >= a for a, b in pairwise(c_values))
    measured_slopes = [
        (constructed_net_c(b) - constructed_net_c(a)) / (b - a)
        for a, b in ((10_000, 20_000), (32_000, 38_000), (45_000, 55_000))
    ]
    for actual, expected in zip(measured_slopes, (0.8, 0.3, 0.8)):
        assert math.isclose(actual, expected, rel_tol=0, abs_tol=1e-12)
    return {
        "status": "PASS_CONSTRUCTED_MATH_ONLY",
        "grid_points": len(grid),
        "grid_domain_annual_earnings_usd": [0, 60_000],
        "max_a_b_difference_usd": max(differences),
        "floating_comparison_tolerance_usd": tolerance_usd,
        "a_b_left_limit_usd": left,
        "a_b_value_at_threshold_usd": constructed_net_a(threshold),
        "a_b_right_limit_usd": right,
        "a_b_downward_jump_usd": left - right,
        "c_continuous_kinks_earnings_usd": [threshold, taper_end],
        "c_net_income_at_kinks_usd": [left_at_start, right_at_end],
        "c_segment_slopes": measured_slopes,
        "c_monotone_on_grid": True,
        "threshold_membership": "upper branch includes y=30000; lower excludes it",
        "real_policy_household_chart_qualification": False,
    }


def render_figure(output_dir: Path) -> dict:
    # This import happens only after the dependency-free mathematical checks.
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import font_manager
    from matplotlib import pyplot as plt
    from matplotlib.ticker import FuncFormatter

    inter_fonts = [
        f.fname for f in font_manager.fontManager.ttflist if f.name == "Inter"
    ]
    font_name = "Inter" if inter_fonts else "DejaVu Sans"
    plt.rcParams.update(
        {
            "font.family": font_name,  # --font-sans; journal fallback if unavailable
            "font.size": 8.5,
            "text.color": INK,
            "axes.labelcolor": INK,
            "xtick.color": SLATE,
            "ytick.color": SLATE,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "svg.fonttype": "none",
            "svg.hashsalt": "constructed-cliffs-v1",
            "savefig.facecolor": "white",
        }
    )
    fig, axes = plt.subplots(1, 3, figsize=FIGURE_SIZE_INCHES, sharex=True, sharey=True)
    fig.subplots_adjust(left=0.092, right=0.985, bottom=0.265, top=0.665, wspace=0.18)
    fig.text(
        0.092, 0.973, "Constructed illustration", fontsize=11.5, weight="bold", va="top"
    )
    fig.text(
        0.092,
        0.914,
        r"$N(y)=y-T(y)+B(y)$; functions and axes use \$1,000 per year.",
        fontsize=8.3,
        va="top",
        color=SLATE,
    )
    titles = ("A  Benefit cliff", "B  Tax credit notch", "C  Continuous taper")
    rules = (
        (r"$B=5$ for $y\leq30$", r"$B=0$ otherwise", r"$T=0.2y$"),
        (r"$T=0.2y-5$ for $y\leq30$", r"$T=0.2y$ otherwise", r"$B=0$"),
        (
            r"$B=5$ for $y\leq30$; otherwise",
            r"$B=\max(5-0.5(y-30),0)$",
            r"$T=0.2y$",
        ),
    )
    threshold = CONSTRUCTED_THRESHOLD_USD
    left_x = [float(y) for y in range(0, 30_001, 100)]
    right_x = [float(y) for y in range(30_000, 60_001, 100)]
    for index, (ax, title, panel_rules) in enumerate(zip(axes, titles, rules)):
        ax.set_xlim(0, EARNINGS_MAX_USD)
        ax.set_ylim(0, 50_000)
        ax.set_xticks((0, 15_000, 30_000, 45_000, 60_000))
        ax.set_yticks((0, 10_000, 20_000, 30_000, 40_000, 50_000))
        ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x / 1_000:g}"))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"{y / 1_000:g}"))
        ax.tick_params(labelsize=8.0, width=0.6, length=3)
        ax.spines[["top", "right"]].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(SLATE)
            ax.spines[side].set_linewidth(0.6)
        ax.grid(axis="y", color=BORDER, linewidth=0.6)
        ax.set_axisbelow(True)
        ax.text(
            0,
            1.46,
            title,
            transform=ax.transAxes,
            fontsize=9.1,
            weight="bold",
            va="top",
        )
        for y_position, rule in zip((1.32, 1.21, 1.10), panel_rules):
            ax.text(0, y_position, rule, transform=ax.transAxes, fontsize=8.0, va="top")
        if index < 2:
            # Draw branches separately: there is no vertical function segment.
            left_values = [(1 - CONSTRUCTED_TAX_RATE) * x + 5_000 for x in left_x]
            right_values = [(1 - CONSTRUCTED_TAX_RATE) * x for x in right_x]
            ax.plot(left_x, left_values, color=TEAL, linewidth=1.8)
            ax.plot(right_x, right_values, color=TEAL, linewidth=1.8)
            ax.plot(threshold, 29_000, "o", color=TEAL, markersize=4.4, zorder=4)
            ax.plot(
                threshold,
                24_000,
                "o",
                markerfacecolor="white",
                markeredgecolor=TEAL,
                markeredgewidth=1.1,
                markersize=4.4,
                zorder=4,
            )
        else:
            x_values = [float(y) for y in range(0, 60_001, 100)]
            ax.plot(
                x_values,
                [constructed_net_c(x) for x in x_values],
                color=TEAL,
                linewidth=1.8,
            )
            for x in (30_000, 40_000):
                ax.plot(
                    x, constructed_net_c(x), "o", color=TEAL, markersize=3.4, zorder=4
                )
    fig.text(0.54, 0.173, "Annual earnings", ha="center", fontsize=8.5)
    fig.text(0.012, 0.465, "Annual net income", rotation=90, va="center", fontsize=8.5)
    fig.text(
        0.092,
        0.099,
        "These hypothetical functions give the same $5,000 drop in A and B; C stays continuous.",
        fontsize=8.0,
        color=SLATE,
    )
    fig.text(
        0.092,
        0.047,
        "Filled circles mark included endpoints; open circles mark excluded branch limits.",
        fontsize=8.0,
        color=SLATE,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    basename = output_dir / "constructed_cliffs"
    metadata = {
        "Title": "Constructed illustration: benefit and tax cliffs versus continuous withdrawal",
        "Creator": "scripts/plot_constructed_cliffs.py",
        "Subject": "Hypothetical functions only; no legislation, PolicyEngine or population estimates",
        "CreationDate": None,
        "ModDate": None,
    }
    for extension in ("png", "pdf", "svg"):
        extra = {"metadata": metadata} if extension == "pdf" else {}
        if extension == "svg":
            extra = {"metadata": {"Date": None}}
        fig.savefig(basename.with_suffix(f".{extension}"), dpi=DPI, **extra)
    plt.close(fig)
    output_paths = [basename.with_suffix(f".{ext}") for ext in ("png", "pdf", "svg")]
    return {
        "matplotlib": importlib.metadata.version("matplotlib"),
        "font_family": font_name,
        "font_file": Path(
            font_manager.findfont(font_name, fallback_to_default=False)
        ).name,
        "font_file_sha256": hashlib.sha256(
            Path(
                font_manager.findfont(font_name, fallback_to_default=False)
            ).read_bytes()
        ).hexdigest(),
        "figure_size_inches": list(FIGURE_SIZE_INCHES),
        "png_dpi": DPI,
        "outputs": [
            {
                "path": str(p.relative_to(Path(__file__).resolve().parents[1])),
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                "bytes": p.stat().st_size,
            }
            for p in output_paths
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Check constructed functions without plotting",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "figures",
    )
    args = parser.parse_args()
    checks = verify_constructed_functions()
    if args.check_only:
        print(json.dumps(checks, indent=2))
        return
    plotted = render_figure(args.output_dir)
    root = Path(__file__).resolve().parents[1]
    provenance = {
        "classification": "CONSTRUCTED_ILLUSTRATION_NOT_REAL_POLICY_RESULTS",
        "caption": CAPTION,
        "data_source": "Explicitly chosen hypothetical functions; no external data",
        "terminology_reference": {
            "authors": ["Henrik Kleven", "Mazen Waseem"],
            "year": 2013,
            "journal": "Quarterly Journal of Economics",
            "volume": 128,
            "issue": 2,
            "pages": "669-723",
            "doi": "10.1093/qje/qjt004",
            "url": "https://doi.org/10.1093/qje/qjt004",
            "author_pdf": "https://www.henrikkleven.com/uploads/3/7/3/1/37310663/kleven-waseem_qje2013.pdf",
            "scope": "Tax and transfer notch terminology; no behavioral claim",
        },
        "chosen_parameters": {
            "benefit_or_refundable_credit_usd": CONSTRUCTED_BENEFIT_USD,
            "earnings_cutoff_usd": CONSTRUCTED_THRESHOLD_USD,
            "tax_rate": CONSTRUCTED_TAX_RATE,
            "continuous_benefit_withdrawal_rate": CONSTRUCTED_WITHDRAWAL_RATE,
        },
        "functions_annual_usd": {
            "net_income": "N(y)=y-T(y)+B(y)",
            "A": "T(y)=0.2*y; B(y)=5000 if y<=30000 else 0",
            "B": "T(y)=0.2*y-(5000 if y<=30000 else 0); B(y)=0",
            "C": "T(y)=0.2*y; B(y)=max(5000-0.5*max(y-30000,0),0)",
        },
        "invariants": checks,
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "resolved_packages": {
                d.metadata["Name"]: d.version
                for d in importlib.metadata.distributions()
            },
        },
        "requirements_lock": {
            "path": "figures/constructed_cliffs.requirements.txt",
            "sha256": hashlib.sha256(
                (root / "figures/constructed_cliffs.requirements.txt").read_bytes()
            ).hexdigest(),
        },
        "reproduce": [
            "uv venv --no-project --python 3.14 .venv-constructed",
            "uv pip install --python .venv-constructed/bin/python --require-hashes --only-binary :all: -r figures/constructed_cliffs.requirements.txt",
            "uv run --no-project --python .venv-constructed/bin/python python scripts/plot_constructed_cliffs.py",
        ],
        "actual_argv": [Path(sys.executable).name, *sys.argv],
        "script": {
            "path": str(Path(__file__).resolve().relative_to(root)),
            "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
        "figure": plotted,
        "limits": [
            "These exposition choices represent no actual legislation or PolicyEngine estimate.",
            "No health, SPM, population or counterfactual result follows from this figure.",
            "This figure does not qualify or replace real-policy hypothetical-household charts.",
        ],
    }
    forbidden_loaded = [
        name
        for name in sys.modules
        if name.startswith(("policyengine", "microcosm", "h5py", "tables"))
    ]
    assert not forbidden_loaded, forbidden_loaded
    provenance["loaded_model_or_h5_modules"] = forbidden_loaded
    (args.output_dir / "constructed_cliffs.provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )
    (args.output_dir / "constructed_cliffs.caption.md").write_text(CAPTION + "\n")
    print(json.dumps({"invariants": checks, "figure": plotted}, indent=2))


if __name__ == "__main__":
    main()
