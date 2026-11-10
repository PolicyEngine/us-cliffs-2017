"""scripts/render_results.py labels each row from the CSFP setting its run recorded."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.render_results import csfp_label, csfp_section  # noqa: E402


def test_label_reads_the_recorded_setting():
    assert csfp_label({"leave_out_csfp": True}) == "leaving CSFP out"
    assert csfp_label({"leave_out_csfp": False}) == "counting CSFP"
    # Runs made before the option existed record nothing; they counted CSFP.
    assert csfp_label({}) == "counting CSFP"


def test_refuses_a_csfp_row_that_left_csfp_out(tmp_path):
    path = tmp_path / "final_2025_plain.json"
    path.write_text(json.dumps({"year": 2025, "health_benefits_in_net_income": False, "leave_out_csfp": True}))
    with pytest.raises(SystemExit, match="leave_out_csfp"):
        csfp_section([], [path])


def test_counted_once_section(tmp_path, capsys):
    from scripts.render_results import counted_once_section

    def headline(n):
        return dict(people_on_cliff=n, workers_on_cliff=n, households_with_person_on_cliff=n, people_in_those_households=n)

    for year, ptc in ((2017, 60_000.0), (2025, 0.0)):
        largest = dict(people=ptc, sample_people=int(ptc > 0) * 30)
        for key in ("lifted_past_400", "lose_income_test", "lose_whole_credit"):
            largest[key] = ptc
            largest[f"sample_{key}"] = largest["sample_people"]
        record = dict(
            year=year,
            health_benefits_in_net_income=True,
            counted_once=headline(2.0e6),
            medicaid_value_scaled_counted_once={"0.8": headline(1.9e6), "1.2": headline(2.1e6)},
            premium_tax_credit_largest_loss=largest,
        )
        (tmp_path / f"once_{year}.json").write_text(json.dumps(record))
    counted_once_section([], folder=tmp_path)
    out = capsys.readouterr().out
    assert "| x0.8 | x1 | x1.2 |" in out
    assert "| 2017 rules, counting health coverage, premium tax credit counted once | 1.90M | 2.00M | 2.10M |" in out
    assert "for 0.06M adults (30 in the sample)" in out
    assert "Under 2025 rules, counting health coverage, with the credit counted once, losing the credit lowers net income most for none of the adults facing a cliff." in out


def test_no_counted_once_section_without_files(tmp_path, capsys):
    from scripts.render_results import counted_once_section

    counted_once_section([], folder=tmp_path)
    assert capsys.readouterr().out == ""


def test_health_labels_say_how_they_count_the_credit():
    from scripts.render_results import name

    health = {"year": 2017, "health_benefits_in_net_income": True}
    plain = {"year": 2017, "health_benefits_in_net_income": False}
    assert name(health) == "2017 rules, counting health coverage"
    assert name(health, "twice") == "2017 rules, counting health coverage, premium tax credit counted twice"
    assert name(health, "once") == "2017 rules, counting health coverage, premium tax credit counted once"
    # Without health coverage there's no credit to count, so the label stays plain.
    assert name(plain, "twice") == "2017 rules, cash and near-cash only"


def test_take_up_section(tmp_path, capsys):
    from scripts.render_results import take_up_section

    def group(n, share):
        return {"columns": [], "cliffs_that_disappear": n, "share": share, "sample_rows": 1}

    plain = {"people_on_cliff": 700_000.0, "groups": {"school_meals": group(300_000.0, 0.43), "state_benefits": group(50_000.0, 0.071), "all_of_these": group(340_000.0, 0.486)}}
    health = {"people_on_cliff": 2.68e6, "groups": {"school_meals": group(300_000.0, 0.113), "state_benefits": group(35_000.0, 0.013), "chip": group(45_000.0, 0.017), "medicare_savings_programs": group(150_000.0, 0.055), "state_health_programs": group(0.0, 0.0), "all_of_these": group(500_000.0, 0.188)}}
    path = tmp_path / "take_up_bounds.json"
    path.write_text(json.dumps({"runs": {"2017_plain": {"as_modeled": plain}, "2017_health": {"as_modeled": health, "credit_counted_once": health}}}))
    take_up_section(path)
    out = capsys.readouterr().out
    assert "| Configuration | Adults facing a cliff | School meals | State benefits | CHIP | Medicare Savings Programs | State health programs | Any of these |" in out
    assert "| 2017 rules, cash and near-cash only | 0.70M | 0.30M (43%) | 0.05M (7%) | – | – | – | 0.34M (49%) |" in out
    assert "| 2017 rules, counting health coverage, premium tax credit counted once | 2.68M | 0.30M (11%) | 0.04M (1%) | 0.04M (2%) | 0.15M (6%) | 0.00M (0%) | 0.50M (19%) |" in out
    # WIC follows Microcosm's stored draw, so it has no column of its own
    assert "| WIC |" not in out and "We set WIC take-up from the draw Microcosm stores" in out


def test_share_text_never_shows_a_nonzero_share_as_zero():
    from scripts.render_results import share_text

    assert share_text(0.0) == "0%"
    assert share_text(0.0004) == "<0.1%"
    assert share_text(0.0049) == "0.5%"
    assert share_text(0.00949) == "0.9%"
    assert share_text(0.0096) == "1%"
    assert share_text(0.013) == "1%"
    assert share_text(0.486) == "49%"


def test_take_up_section_shows_small_shares_with_a_decimal(tmp_path, capsys):
    from scripts.render_results import take_up_section

    def group(n, share):
        return {"columns": [], "cliffs_that_disappear": n, "share": share, "sample_rows": 1}

    plain = {"people_on_cliff": 680_000.0, "groups": {"school_meals": group(3_300.0, 0.0049), "state_benefits": group(200.0, 0.0003), "all_of_these": group(3_500.0, 0.0051)}}
    path = tmp_path / "take_up_bounds.json"
    path.write_text(json.dumps({"runs": {"2025_plain": {"as_modeled": plain}}}))
    take_up_section(path)
    out = capsys.readouterr().out
    assert "(0.5%)" in out and "(<0.1%)" in out and "(0%)" not in out


def test_no_take_up_section_without_file(tmp_path, capsys):
    from scripts.render_results import take_up_section

    take_up_section(tmp_path / "missing.json")
    assert capsys.readouterr().out == ""


def interval_block(total, drivers):
    """A results/driver_intervals.json block: drivers maps a key to (count, interval, share interval, households, half)."""
    return {
        "people_on_cliff": total,
        "by_largest_loss": {
            k: {
                "people_on_cliff": n,
                "interval_95": list(ci),
                "share_interval_95": list(share_ci),
                "source_households": hh,
                "source_households_for_half": half,
            }
            for k, (n, ci, share_ci, hh, half) in drivers.items()
        },
    }


def plain_2017():
    return {
        "year": 2017,
        "health_benefits_in_net_income": False,
        "people_on_cliff": 700_000.0,
        "people_on_cliff_by_driver": {"snap": 400_000.0, "tanf": 300_000.0},
    }


def test_drivers_section_shows_intervals_and_households(capsys):
    from scripts.render_results import drivers_section

    block = interval_block(700_000.0, {
        "snap": (400_000.0, (200_000.0, 600_000.0), (0.3, 0.8), 40, 4),
        "tanf": (300_000.0, (90_000.0, 520_000.0), (0.2, 0.7), 12, 2),
    })
    drivers_section([plain_2017()], {("2017_plain", "twice"): block})
    out = capsys.readouterr().out
    assert "| Largest loss | Adults | 95% interval | Share | 95% interval | Survey households |" in out
    assert "| SNAP | 0.40M | 0.20M to 0.60M | 57% | 30% to 80% | 40 (4) |" in out
    assert "| TANF | 0.30M | 0.09M to 0.52M | 43% | 20% to 70% | 12 (2) |" in out
    assert "5,000 resamples of Microcosm's source households" in out


def test_drivers_section_without_intervals_keeps_the_plain_table(capsys):
    from scripts.render_results import drivers_section

    drivers_section([plain_2017()], {})
    out = capsys.readouterr().out
    assert "| Largest loss | Adults | Share |" in out
    assert "| SNAP | 0.40M | 57% |" in out
    assert "resamples" not in out


def test_load_intervals_refuses_counts_from_other_runs(tmp_path):
    from scripts.render_results import load_intervals

    assert load_intervals([plain_2017()], tmp_path / "missing.json") == {}
    good = interval_block(700_000.0, {
        "snap": (400_000.0, (0, 1), (0, 1), 1, 1),
        "tanf": (300_000.0, (0, 1), (0, 1), 1, 1),
    })
    path = tmp_path / "driver_intervals.json"
    path.write_text(json.dumps({"runs": {"2017_plain": {"as_modeled": good}}}))
    assert set(load_intervals([plain_2017()], path)) == {("2017_plain", "twice")}

    other_total = dict(good, people_on_cliff=690_000.0)
    path.write_text(json.dumps({"runs": {"2017_plain": {"as_modeled": other_total}}}))
    with pytest.raises(SystemExit, match="adults facing a cliff"):
        load_intervals([plain_2017()], path)

    other_driver = interval_block(700_000.0, {
        "snap": (400_000.0, (0, 1), (0, 1), 1, 1),
        "wic": (300_000.0, (0, 1), (0, 1), 1, 1),
    })
    path.write_text(json.dumps({"runs": {"2017_plain": {"as_modeled": other_driver}}}))
    with pytest.raises(SystemExit, match="tanf, wic"):
        load_intervals([plain_2017()], path)


def test_counted_once_section_gives_the_credit_count_its_interval(tmp_path, capsys):
    from scripts.render_results import counted_once_section

    def headline(n):
        return dict(people_on_cliff=n, workers_on_cliff=n, households_with_person_on_cliff=n, people_in_those_households=n)

    largest = dict(people=60_000.0, sample_people=28)
    for key in ("lifted_past_400", "lose_income_test", "lose_whole_credit"):
        largest[key], largest[f"sample_{key}"] = 60_000.0, 26
    record = dict(
        year=2017,
        health_benefits_in_net_income=True,
        counted_once=headline(2.0e6),
        medicaid_value_scaled_counted_once={"0.8": headline(1.9e6), "1.2": headline(2.1e6)},
        premium_tax_credit_largest_loss=largest,
    )
    (tmp_path / "once_2017.json").write_text(json.dumps(record))
    block = interval_block(2.0e6, {"assigned_aca_ptc": (60_000.0, (8_000.0, 128_000.0), (0.0, 0.1), 17, 2)})
    counted_once_section([], folder=tmp_path, intervals={("2017_health", "once"): block})
    out = capsys.readouterr().out
    assert "for 0.06M adults (28 in the sample, from 17 survey households, 2 of which supply half; 95% interval 0.01M to 0.13M)" in out

    off = interval_block(2.0e6, {"assigned_aca_ptc": (61_000.0, (8_000.0, 128_000.0), (0.0, 0.1), 17, 2)})
    with pytest.raises(SystemExit, match="credit count"):
        counted_once_section([], folder=tmp_path, intervals={("2017_health", "once"): off})
