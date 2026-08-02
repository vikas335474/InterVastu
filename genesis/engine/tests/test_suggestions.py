"""Unit tests for suggestions.py, the audit<->solver bridge.

Covers: a supported room type with a good placement (no compromise), a
room type outside solver.py's scope (silently skipped, not an error), a
missing polygon (silently skipped), a genuine physical-fit failure turned
into a structured suggestion_error instead of a raised exception, a
furniture_dimensions override taking priority over the module default, and
malformed/wire-garbage polygon input (wrong type, wrong arity, non-numeric
coordinates) -- these must never raise, and must be distinguishable
(error_type="invalid_geometry") from a genuine physical-fit failure
(error_type="solver_error"), since suggest_for_room has no schema-validated
caller and must assume arbitrary JSON can arrive here.
"""

import pytest

import suggestions as sug


MASTER_BEDROOM_ROOM = [(0, 0), (12, 0), (12, 14), (0, 14)]


def test_suggest_for_room_returns_placement_for_supported_type():
    result = sug.suggest_for_room("MasterBedroom", MASTER_BEDROOM_ROOM, facade_bearing_deg=0.0)
    assert result["room"] == "MasterBedroom"
    assert "placements" in result
    assert result["placements"][0]["object"] == "bed"
    assert result["placements"][0]["satisfies_rule"] is True


def test_suggest_for_room_kitchen_uses_default_stove_dimensions():
    kitchen = [(0, 0), (10, 0), (10, 8), (0, 8)]
    result = sug.suggest_for_room("Kitchen", kitchen, facade_bearing_deg=0.0)
    assert result["room"] == "Kitchen"
    assert result["placements"][0]["object"] == "stove"


def test_suggest_for_room_living_room_returns_wall_recommendation():
    living = [(0, 0), (10, 0), (10, 10), (0, 10)]
    result = sug.suggest_for_room("LivingRoom", living, facade_bearing_deg=0.0)
    assert result["room"] == "LivingRoom"
    assert result["placements"][0]["object"] == "heavy_furniture_zone"


def test_suggest_for_room_unsupported_type_returns_none():
    # e.g. Toilet has no solver at all -- not an error, just nothing to add.
    assert sug.suggest_for_room("Toilet", MASTER_BEDROOM_ROOM) is None
    assert sug.suggest_for_room("Staircase", MASTER_BEDROOM_ROOM) is None


def test_suggest_for_room_physical_impossibility_is_structured_error_not_exception():
    tiny_room = [(0, 0), (2, 0), (2, 2), (0, 2)]  # too small for any default bed
    result = sug.suggest_for_room("MasterBedroom", tiny_room)
    assert result["room"] == "MasterBedroom"
    assert "suggestion_error" in result
    assert result["error_type"] == "solver_error"
    assert "placements" not in result


# ---------------------------------------------------------------------------
# Malformed / wire-garbage polygon input -- must never raise, and must be
# distinguishable from a genuine physical-fit failure.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "bad_polygon",
    [
        None,
        123,
        "not a polygon",
        [],
        [(0, 0)],
        [(0, 0), (1, 1)],  # only 2 vertices
        [(0, 0), (1, 0), "not a coord"],
        [(0, 0), (1, 0), (1,)],  # wrong arity
        [(0, 0), (1, 0), ("x", "y")],  # non-numeric coordinates
        [(0, 0), (1, 0), (1, 1), (0, 1), None],
    ],
)
def test_suggest_for_room_malformed_polygon_never_raises(bad_polygon):
    result = sug.suggest_for_room("MasterBedroom", bad_polygon)
    assert result["room"] == "MasterBedroom"
    assert "suggestion_error" in result
    assert result["error_type"] == "invalid_geometry"
    assert "placements" not in result


def test_suggest_for_room_malformed_polygon_is_distinguishable_from_solver_error():
    """invalid_geometry (structurally bad input) and solver_error (a
    well-formed room that's genuinely too small) must not be conflated --
    a caller needs to tell "you sent garbage" apart from "this room design
    won't fit a bed"."""
    garbage = sug.suggest_for_room("MasterBedroom", "garbage")
    too_small = sug.suggest_for_room("MasterBedroom", [(0, 0), (2, 0), (2, 2), (0, 2)])
    assert garbage["error_type"] == "invalid_geometry"
    assert too_small["error_type"] == "solver_error"
    assert garbage["error_type"] != too_small["error_type"]


def test_suggest_for_layout_one_malformed_room_does_not_break_other_rooms():
    """The core regression this fix targets: one bad polygon must not take
    down suggestions (or the whole audit response) for every other room."""
    rooms = [
        {"name": "MasterBedroom", "polygon": "not a valid polygon"},
        {"name": "Kitchen", "polygon": [(0, 0), (10, 0), (10, 8), (0, 8)]},
    ]
    results = sug.suggest_for_layout(rooms)
    assert len(results) == 2

    bad = next(r for r in results if r["room"] == "MasterBedroom")
    good = next(r for r in results if r["room"] == "Kitchen")
    assert bad["error_type"] == "invalid_geometry"
    assert "placements" in good
    assert good["placements"][0]["object"] == "stove"


def test_suggest_for_room_furniture_dimensions_override_takes_priority():
    # A room too small for the DEFAULT queen bed, but big enough for a
    # smaller bed supplied via override -- proves the override is actually
    # used, not just accepted and ignored.
    small_room = [(0, 0), (4, 0), (4, 5), (0, 5)]
    default_result = sug.suggest_for_room("MasterBedroom", small_room)
    assert "suggestion_error" in default_result

    override_result = sug.suggest_for_room(
        "MasterBedroom", small_room,
        furniture_dimensions={"MasterBedroom": (3.0, 4.0)},
    )
    assert "placements" in override_result


def test_suggest_for_layout_skips_rooms_without_polygon():
    rooms = [
        {"name": "MasterBedroom", "zone": "SW"},  # no polygon -> skipped
        {"name": "Kitchen", "zone": "SE", "polygon": [(0, 0), (10, 0), (10, 8), (0, 8)]},
    ]
    results = sug.suggest_for_layout(rooms)
    assert len(results) == 1
    assert results[0]["room"] == "Kitchen"


def test_suggest_for_layout_skips_unsupported_room_types():
    rooms = [
        {"name": "Toilet", "zone": "NW", "polygon": [(0, 0), (5, 0), (5, 5), (0, 5)]},
        {"name": "MasterBedroom", "zone": "SW", "polygon": MASTER_BEDROOM_ROOM},
    ]
    results = sug.suggest_for_layout(rooms)
    assert len(results) == 1
    assert results[0]["room"] == "MasterBedroom"


def test_suggest_for_layout_passes_through_facade_bearing():
    """Rotating facade_bearing_deg rotates which physical wall is chosen
    (both orientations can satisfy the same preferred compass direction on
    a rectangular room, so compare the chosen wall's position, not the
    resulting compass label)."""
    rooms = [{"name": "MasterBedroom", "polygon": MASTER_BEDROOM_ROOM}]
    north_up = sug.suggest_for_layout(rooms, facade_bearing_deg=0.0)
    east_up = sug.suggest_for_layout(rooms, facade_bearing_deg=90.0)
    assert north_up[0]["placements"][0]["position"] != east_up[0]["placements"][0]["position"]


def test_suggest_for_layout_empty_when_no_rooms_have_polygons():
    rooms = [{"name": "MasterBedroom", "zone": "SW"}, {"name": "Kitchen", "zone": "SE"}]
    assert sug.suggest_for_layout(rooms) == []
