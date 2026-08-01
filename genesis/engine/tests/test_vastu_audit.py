"""Unit tests for vastu_audit's object-placement extension.

Covers: audit_object_placement() in isolation, and audit_layout_with_objects()
as the integration entry point, without touching or breaking the existing
audit_room/audit_layout behavior (verified explicitly below).
"""

from pathlib import Path

import pytest

import vastu_audit as va

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "vastu_rule_schema.json"
SCHEMA = va.load_schema(SCHEMA_PATH)


def _violation_types(violations):
    return {v["violation"] for v in violations}


# ---------------------------------------------------------------------------
# 1. Master bedroom bed-head direction
# ---------------------------------------------------------------------------

def test_master_bedroom_bed_head_north_is_major_violation():
    room = {"name": "MasterBedroom", "zone": "SW", "objects": {"bed_head_direction": "N"}}
    violations = va.audit_object_placement(room, SCHEMA)

    assert len(violations) == 1
    v = violations[0]
    assert v["room"] == "MasterBedroom"
    assert v["rule_type"] == "object_placement"
    assert v["violation"] == "bed_head_direction=N"
    assert v["severity"] == "major"
    assert v["remedy"]  # non-empty remedy text


def test_master_bedroom_bed_head_south_passes():
    room = {"name": "MasterBedroom", "zone": "SW", "objects": {"bed_head_direction": "S"}}
    assert va.audit_object_placement(room, SCHEMA) == []


def test_master_bedroom_bed_head_east_also_passes():
    """East is explicitly preferred alongside South."""
    room = {"name": "MasterBedroom", "zone": "SW", "objects": {"bed_head_direction": "E"}}
    assert va.audit_object_placement(room, SCHEMA) == []


# ---------------------------------------------------------------------------
# 2. Living-room heavy-furniture-wall rule
# ---------------------------------------------------------------------------

def test_living_room_heavy_furniture_on_north_wall_is_minor_violation():
    room = {"name": "LivingRoom", "zone": "N", "objects": {"heavy_furniture_wall": "N"}}
    violations = va.audit_object_placement(room, SCHEMA)

    assert len(violations) == 1
    v = violations[0]
    assert v["rule_type"] == "object_placement"
    assert v["violation"] == "heavy_furniture_wall=N"
    assert v["severity"] == "minor"


def test_living_room_heavy_furniture_on_south_wall_passes():
    room = {"name": "LivingRoom", "zone": "N", "objects": {"heavy_furniture_wall": "S"}}
    assert va.audit_object_placement(room, SCHEMA) == []


# ---------------------------------------------------------------------------
# 3. Other object-placement rules (toilet seat, kitchen stove, study desk,
#    dining seating) — sanity checks that each rule in the table fires
#    correctly in both directions.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "room_name,field,bad_direction,good_direction,expected_severity",
    [
        ("Toilet", "seat_direction", "E", "N", "minor"),
        ("Toilet", "seat_direction", "W", "S", "minor"),
        ("Kitchen", "stove_facing_direction", "W", "E", "minor"),
        ("StudyRoom", "desk_facing_direction", "S", "E", "minor"),
        ("DiningRoom", "seating_facing_direction", "N", "E", "minor"),
    ],
)
def test_object_rule_flags_bad_direction_and_passes_good_direction(
    room_name, field, bad_direction, good_direction, expected_severity
):
    bad_room = {"name": room_name, "zone": "N", "objects": {field: bad_direction}}
    good_room = {"name": room_name, "zone": "N", "objects": {field: good_direction}}

    bad_violations = va.audit_object_placement(bad_room, SCHEMA)
    assert len(bad_violations) == 1
    assert bad_violations[0]["severity"] == expected_severity
    assert bad_violations[0]["violation"] == f"{field}={bad_direction}"

    assert va.audit_object_placement(good_room, SCHEMA) == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_room_with_no_objects_key_produces_no_violations():
    room = {"name": "MasterBedroom", "zone": "SW"}
    assert va.audit_object_placement(room, SCHEMA) == []


def test_unrecognised_room_is_silently_ignored_not_flagged():
    room = {"name": "Balcony", "zone": "N", "objects": {"something": "N"}}
    assert va.audit_object_placement(room, SCHEMA) == []


def test_unrecognised_field_on_known_room_is_silently_ignored():
    room = {"name": "MasterBedroom", "zone": "SW", "objects": {"wardrobe_direction": "N"}}
    assert va.audit_object_placement(room, SCHEMA) == []


# ---------------------------------------------------------------------------
# Integration: audit_layout_with_objects merges zone + object violations
# ---------------------------------------------------------------------------

def test_audit_layout_with_objects_merges_zone_and_object_violations():
    input_data = {
        "plot": {
            "shape": "rectangle",
            "floor_slope": {"high_corner": "SW", "low_corner": "NE"},
            "brahmasthan_obstructed": False,
        },
        "rooms": [
            # Zone violation (Toilet in NE is major) AND object violation
            # (seat facing East is minor) on the same room.
            {
                "name": "Toilet",
                "zone": "NE",
                "objects": {"seat_direction": "E"},
            },
            # Object-only violation, zone itself is compliant.
            {
                "name": "MasterBedroom",
                "zone": "SW",
                "objects": {"bed_head_direction": "N"},
            },
        ],
    }
    result = va.audit_layout_with_objects(input_data, SCHEMA)

    toilet = next(r for r in result["rooms"] if r["room"] == "Toilet")
    bedroom = next(r for r in result["rooms"] if r["room"] == "MasterBedroom")

    assert _violation_types(toilet["violations"]) == {"NE", "seat_direction=E"}
    assert _violation_types(bedroom["violations"]) == {"bed_head_direction=N"}

    # 1 major zone (Toilet/NE) + 1 minor object (seat_direction) + 1 major
    # object (bed_head_direction) = 2 major, 1 minor.
    assert result["major_count"] == 2
    assert result["minor_count"] == 1
    assert result["compliance_score"] == 100 - 10 - 10 - 3


def test_audit_layout_with_objects_matches_audit_layout_when_no_objects_given():
    """Without 'objects' on any room, the two functions must agree exactly."""
    input_data = {
        "plot": {
            "shape": "rectangle",
            "floor_slope": {"high_corner": "SW", "low_corner": "NE"},
            "brahmasthan_obstructed": False,
        },
        "rooms": [
            {"name": "Toilet", "zone": "NE"},
            {"name": "Kitchen", "zone": "N"},
        ],
    }
    assert va.audit_layout_with_objects(input_data, SCHEMA) == va.audit_layout(input_data, SCHEMA)


def test_audit_layout_is_unaffected_by_objects_key_it_does_not_understand():
    """Regression guard: the ORIGINAL audit_layout must ignore 'objects'
    entirely and keep behaving exactly as before this change."""
    input_data = {
        "plot": {
            "shape": "rectangle",
            "floor_slope": {"high_corner": "SW", "low_corner": "NE"},
            "brahmasthan_obstructed": False,
        },
        "rooms": [
            {"name": "MasterBedroom", "zone": "SW", "objects": {"bed_head_direction": "N"}},
        ],
    }
    result = va.audit_layout(input_data, SCHEMA)
    assert result["rooms"] == []
    assert result["compliance_score"] == 100
