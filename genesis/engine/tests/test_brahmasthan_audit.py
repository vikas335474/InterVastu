"""Unit tests for the Brahmasthan-obstruction bridge in vastu_audit.py.

Covers audit_brahmasthan() in isolation and its integration into
audit_layout() via the optional geometry_results parameter, plus a
backward-compatibility check that audit_layout() without geometry_results
is byte-for-byte identical to its pre-existing behaviour.
"""

import json
from pathlib import Path

import pytest

import vastu_audit as va

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "vastu_rule_schema.json"
SCHEMA = va.load_schema(SCHEMA_PATH)
FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def _geometry_room(room, contains=False, overlaps=False, fraction=0.0, room_type=None):
    r = {
        "room": room,
        "contains_centre_point": contains,
        "overlaps_brahmasthan_region": overlaps,
        "region_overlap_fraction": fraction,
    }
    if room_type is not None:
        r["room_type"] = room_type
    return r


# ---------------------------------------------------------------------------
# 1. Obstructing room above threshold -> scored major violation
# ---------------------------------------------------------------------------

def test_obstructing_room_above_threshold_is_scored_major():
    geometry_results = [_geometry_room("Toilet", overlaps=True, fraction=0.19)]
    scored, notes = va.audit_brahmasthan(geometry_results, SCHEMA)

    assert len(scored) == 1
    v = scored[0]
    assert v["room"] == "Toilet"
    assert v["rule_type"] == "brahmasthan_obstruction"
    assert v["severity"] == "major"
    assert "19%" in v["violation"]
    assert v["remedy"]  # non-empty
    assert notes == []


def test_obstructing_room_above_threshold_raises_major_count_by_one():
    input_data = {"plot": {}, "rooms": []}
    geometry_results = [_geometry_room("Toilet", overlaps=True, fraction=0.19)]

    baseline = va.audit_layout(input_data, SCHEMA)
    with_brahmasthan = va.audit_layout(input_data, SCHEMA, geometry_results=geometry_results)

    assert with_brahmasthan["major_count"] == baseline["major_count"] + 1
    assert with_brahmasthan["total_scored_violations"] == baseline["total_scored_violations"] + 1
    assert with_brahmasthan["compliance_score"] == baseline["compliance_score"] - va.SEVERITY_POINTS["major"]


def test_obstructing_room_containing_exact_centre_is_scored_major():
    geometry_results = [_geometry_room("Staircase", contains=True, overlaps=True, fraction=0.5)]
    scored, notes = va.audit_brahmasthan(geometry_results, SCHEMA)

    assert len(scored) == 1
    assert "contains the exact centre" in scored[0]["violation"]
    assert notes == []


# ---------------------------------------------------------------------------
# 2. Non-obstructing room overlapping the region -> informational only
# ---------------------------------------------------------------------------

def test_non_obstructing_room_overlap_is_informational_not_scored():
    geometry_results = [_geometry_room("LivingRoom", overlaps=True, fraction=0.72)]
    scored, notes = va.audit_brahmasthan(geometry_results, SCHEMA)

    assert scored == []
    assert len(notes) == 1
    note = notes[0]
    assert note["room"] == "LivingRoom"
    assert note["rule_type"] == "brahmasthan_info"
    assert note["severity"] is None
    assert "72%" in note["message"]


def test_non_obstructing_room_overlap_does_not_change_score():
    input_data = {"plot": {}, "rooms": []}
    geometry_results = [_geometry_room("LivingRoom", overlaps=True, fraction=0.72)]

    baseline = va.audit_layout(input_data, SCHEMA)
    with_brahmasthan = va.audit_layout(input_data, SCHEMA, geometry_results=geometry_results)

    assert with_brahmasthan["compliance_score"] == baseline["compliance_score"]
    assert with_brahmasthan["major_count"] == baseline["major_count"]
    assert with_brahmasthan["minor_count"] == baseline["minor_count"]
    assert with_brahmasthan["brahmasthan_violations"] == []
    assert len(with_brahmasthan["brahmasthan_notes"]) == 1


def test_non_obstructing_room_with_no_overlap_produces_nothing():
    geometry_results = [_geometry_room("LivingRoom", overlaps=False, fraction=0.0)]
    scored, notes = va.audit_brahmasthan(geometry_results, SCHEMA)
    assert scored == []
    assert notes == []


# ---------------------------------------------------------------------------
# 3. Obstructing room below threshold -> informational "minor_overlap" note
# ---------------------------------------------------------------------------

def test_obstructing_room_below_threshold_is_informational_not_scored():
    geometry_results = [_geometry_room("Toilet", overlaps=True, fraction=0.02)]
    scored, notes = va.audit_brahmasthan(geometry_results, SCHEMA, overlap_threshold=0.05)

    assert scored == []
    assert len(notes) == 1
    note = notes[0]
    assert note["room"] == "Toilet"
    assert note["rule_type"] == "brahmasthan_minor_overlap"
    assert note["severity"] is None
    assert "2%" in note["message"]


def test_obstructing_room_below_threshold_does_not_change_score():
    input_data = {"plot": {}, "rooms": []}
    geometry_results = [_geometry_room("Toilet", overlaps=True, fraction=0.02)]

    baseline = va.audit_layout(input_data, SCHEMA)
    with_brahmasthan = va.audit_layout(input_data, SCHEMA, geometry_results=geometry_results)

    assert with_brahmasthan["compliance_score"] == baseline["compliance_score"]
    assert with_brahmasthan["major_count"] == baseline["major_count"]
    assert with_brahmasthan["brahmasthan_violations"] == []
    assert len(with_brahmasthan["brahmasthan_notes"]) == 1


# ---------------------------------------------------------------------------
# room_type override (instance name != schema type key)
# ---------------------------------------------------------------------------

def test_room_type_override_is_used_for_obstructing_types_check():
    geometry_results = [
        _geometry_room("Toilet_central", overlaps=True, fraction=0.19, room_type="Toilet")
    ]
    scored, notes = va.audit_brahmasthan(geometry_results, SCHEMA)

    assert len(scored) == 1
    # Violation text uses the instance name, not the resolved type.
    assert scored[0]["room"] == "Toilet_central"
    assert notes == []


# ---------------------------------------------------------------------------
# 4. Backward compatibility: audit_layout() without geometry_results is
#    unchanged for an existing fixture.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "fixture_name,expected_major,expected_minor,expected_score",
    [
        ("compliant.json", 0, 0, 100),
        ("major_ne_toilet.json", 1, 0, 90),
    ],
)
def test_backward_compat_existing_fixture_counts_unchanged(
    fixture_name, expected_major, expected_minor, expected_score
):
    with open(FIXTURES_DIR / fixture_name, "r", encoding="utf-8") as f:
        data = json.load(f)

    result = va.audit_layout(data, SCHEMA)

    assert result["major_count"] == expected_major
    assert result["minor_count"] == expected_minor
    assert result["compliance_score"] == expected_score
    # No geometry_results passed -> no brahmasthan_* keys at all, exactly the
    # pre-existing return shape.
    assert "brahmasthan_violations" not in result
    assert "brahmasthan_notes" not in result


def test_backward_compat_audit_layout_with_objects_still_matches_audit_layout():
    """audit_layout_with_objects has no geometry_results param; the equality
    invariant the existing test suite relies on must still hold when neither
    is given geometry data."""
    with open(FIXTURES_DIR / "compliant.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    assert va.audit_layout_with_objects(data, SCHEMA) == va.audit_layout(data, SCHEMA)
