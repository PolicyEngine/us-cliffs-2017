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
