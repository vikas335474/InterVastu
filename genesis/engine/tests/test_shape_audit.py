"""Unit tests for the shape-defect bridge in vastu_audit.py.

Covers audit_shape_defects() in isolation and its integration into
audit_layout() via the optional shape_diagnosis parameter, plus a
backward-compatibility check that audit_layout() without shape_diagnosis is
byte-for-byte identical to its pre-existing behaviour.
"""

from pathlib import Path

import vastu_audit as va
import zone_geometry as zg

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "vastu_rule_schema.json"
SCHEMA = va.load_schema(SCHEMA_PATH)


# ---------------------------------------------------------------------------
# 1. Hollow centre -> scored major violation.
# ---------------------------------------------------------------------------

def test_hollow_center_is_scored_major():
    diag = {"hollow_center": True, "centroid": {"x": 15.0, "y": 13.5},
            "high_center_offset": False, "missing_zones": []}
    scored, notes = va.audit_shape_defects(diag)

    assert len(scored) == 1
    v = scored[0]
    assert v["rule_type"] == "hollow_center"
    assert v["severity"] == "major"
    assert v["remedy"]
    assert notes == []


# ---------------------------------------------------------------------------
# 2. High offset (but NOT hollow) -> informational note only, never scored.
# ---------------------------------------------------------------------------

def test_high_center_offset_is_informational_only():
    diag = {"hollow_center": False, "high_center_offset": True,
            "center_offset_fraction": 0.31, "centroid": {"x": 1, "y": 2},
            "missing_zones": []}
    scored, notes = va.audit_shape_defects(diag)

    assert scored == []
    assert len(notes) == 1
    assert notes[0]["rule_type"] == "center_offset_info"
    assert notes[0]["severity"] is None


def test_hollow_center_suppresses_the_offset_note():
    # A hollow centre outranks a large offset; we must not emit both.
    diag = {"hollow_center": True, "high_center_offset": True,
            "center_offset_fraction": 0.4, "centroid": {"x": 1, "y": 2},
            "missing_zones": []}
    scored, notes = va.audit_shape_defects(diag)
    assert [v["rule_type"] for v in scored] == ["hollow_center"]
    assert notes == []  # no center_offset_info


# ---------------------------------------------------------------------------
# 3. Missing ordinal zones are scored per the severity map; cardinals aren't.
# ---------------------------------------------------------------------------

def test_missing_ne_is_scored_major_with_remedy():
    diag = {"hollow_center": False, "high_center_offset": False, "centroid": {},
            "missing_zones": [{"octant": "NE", "zones": ["NE"],
                               "area_ft2": 400.0, "area_fraction": 0.25}]}
    scored, notes = va.audit_shape_defects(diag)

    assert len(scored) == 1
    v = scored[0]
    assert v["rule_type"] == "missing_zone"
    assert v["severity"] == "major"
    assert "NE" in v["violation"]
    assert "NE" in v["remedy"] or "head" in v["remedy"]
    assert notes == []


def test_missing_cardinal_zone_is_informational_only():
    diag = {"hollow_center": False, "high_center_offset": False, "centroid": {},
            "missing_zones": [{"octant": "N", "zones": ["N"],
                               "area_ft2": 200.0, "area_fraction": 0.22}]}
    scored, notes = va.audit_shape_defects(diag)

    assert scored == []
    assert len(notes) == 1
    assert notes[0]["rule_type"] == "missing_zone_info"
    assert notes[0]["severity"] is None


def test_missing_zone_severity_override():
    diag = {"hollow_center": False, "high_center_offset": False, "centroid": {},
            "missing_zones": [{"octant": "SE", "zones": ["SE"],
                               "area_ft2": 100.0, "area_fraction": 0.1}]}
    # Override so SE is not scored at all.
    scored, notes = va.audit_shape_defects(diag, missing_zone_severity={})
    assert scored == []
    assert [n["rule_type"] for n in notes] == ["missing_zone_info"]


# ---------------------------------------------------------------------------
# 4. Integration through audit_layout + backward compatibility.
# ---------------------------------------------------------------------------

def _minimal_input():
    return {"plot": {}, "rooms": [{"name": "LivingRoom", "zone": "N"}]}


def test_audit_layout_without_shape_diagnosis_is_unchanged():
    result = va.audit_layout(_minimal_input(), SCHEMA)
    assert "shape_defect_violations" not in result
    assert "shape_defect_notes" not in result


def test_audit_layout_merges_shape_defects_and_deducts_score():
    boundary = [
        (0, 0), (30, 0), (30, 30), (20, 30),
        (20, 10), (10, 10), (10, 30), (0, 30),
    ]
    diag = zg.diagnose_shape(boundary, north_offset_deg=0.0)
    assert diag["hollow_center"] is True  # precondition

    baseline = va.audit_layout(_minimal_input(), SCHEMA)["compliance_score"]
    result = va.audit_layout(_minimal_input(), SCHEMA, shape_diagnosis=diag)

    assert "shape_defect_violations" in result
    kinds = {v["rule_type"] for v in result["shape_defect_violations"]}
    assert "hollow_center" in kinds
    # A scored major defect must lower the compliance score.
    assert result["compliance_score"] < baseline
    assert result["major_count"] >= 1
