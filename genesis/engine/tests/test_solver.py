"""Unit tests for solver.py (Phase 1c furniture placement).

Two required cases per the task spec:
1. A rectangular MasterBedroom where a compliant bed placement exists —
   assert it's found, with no compromise.
2. An intentionally awkward room shape where NO wall satisfies the
   preferred sleeping direction — assert a compromise result is returned
   with a clear note, never a silent failure or an exception.

Plus supporting coverage for the stove and living-room solvers, and the
genuine-physical-failure (ValueError) path, which is explicitly NOT a
Vastu compromise.
"""

import pytest

import solver as sv


# ---------------------------------------------------------------------------
# 1. Bed placement — compliant rectangular MasterBedroom
# ---------------------------------------------------------------------------

def test_bed_placement_compliant_master_bedroom_no_compromise():
    """12x14 room: the south wall is long enough and faces the schema's
    preferred 'S' sleeping direction, so a fully compliant placement exists."""
    room = [(0, 0), (12, 0), (12, 14), (0, 14)]
    bed_dimensions = (6.0, 6.5)

    result = sv.solve_bed_placement(room, bed_dimensions, "MasterBedroom", facade_bearing=0.0)

    assert len(result) == 1
    placement = result[0]
    assert placement["room"] == "MasterBedroom"
    assert placement["object"] == "bed"
    assert placement["satisfies_rule"] is True
    assert placement["compromise"] is False
    assert placement["compromise_note"] is None
    assert placement["rotation_deg"] == pytest.approx(180.0)  # head points South
    x, y = placement["position"]
    assert 0.0 <= x <= 12.0
    assert 0.0 <= y <= 14.0


# ---------------------------------------------------------------------------
# 2. Bed placement — awkward room, no wall satisfies preferred direction
# ---------------------------------------------------------------------------

# A rectilinear "staircase" bedroom: the S/E boundary is broken into eight
# 3 ft segments (each too short for a 6 ft-wide bed), so no viable S- or
# E-facing wall remains. Only the N wall (12 ft) and W wall (12 ft) are
# long enough — N is the schema's explicitly forbidden head direction, W is
# merely non-preferred. This is a genuinely awkward (but valid, realistic)
# room shape, not a contrived geometry.
AWKWARD_STAIRCASE_BEDROOM = [
    (0, 0), (3, 0), (3, 3), (6, 3), (6, 6), (9, 6), (9, 9), (12, 9), (12, 12), (0, 12),
]


def test_bed_placement_awkward_room_returns_compromise_not_exception():
    bed_dimensions = (6.0, 6.5)

    result = sv.solve_bed_placement(
        AWKWARD_STAIRCASE_BEDROOM, bed_dimensions, "MasterBedroom", facade_bearing=0.0
    )

    assert len(result) == 1
    placement = result[0]
    assert placement["satisfies_rule"] is False
    assert placement["compromise"] is True
    assert placement["compromise_note"]  # non-empty, plain-language explanation
    assert "preferred sleeping direction" in placement["compromise_note"]
    # The solver must prefer the neutral option (W) over the forbidden one (N)
    # when neither preferred wall is available.
    assert placement["rotation_deg"] == pytest.approx(270.0)


def test_bed_placement_never_raises_for_a_merely_awkward_room():
    """Regression guard: an awkward-but-fittable room must never raise —
    only a genuine physical non-fit (tested below) should raise."""
    try:
        sv.solve_bed_placement(
            AWKWARD_STAIRCASE_BEDROOM, (6.0, 6.5), "MasterBedroom", facade_bearing=0.0
        )
    except Exception as exc:  # pragma: no cover - failure path under test
        pytest.fail(f"solve_bed_placement raised unexpectedly: {exc!r}")


# ---------------------------------------------------------------------------
# Genuine physical failure — bed does not fit anywhere (NOT a compromise)
# ---------------------------------------------------------------------------

def test_bed_placement_raises_when_bed_does_not_physically_fit():
    tiny_room = [(0, 0), (4, 0), (4, 4), (0, 4)]
    with pytest.raises(ValueError):
        sv.solve_bed_placement(tiny_room, (6.0, 6.5), "MasterBedroom", facade_bearing=0.0)


def test_bed_placement_rejects_out_of_scope_room_type():
    room = [(0, 0), (12, 0), (12, 12), (0, 12)]
    with pytest.raises(ValueError):
        sv.solve_bed_placement(room, (6.0, 6.5), "StudyRoom", facade_bearing=0.0)


# ---------------------------------------------------------------------------
# GuestBedroom / ChildrenBedroom share the same head-direction rule as
# MasterBedroom, but WITHOUT the NE-corner-avoidance constraint.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("room_name", ["GuestBedroom", "ChildrenBedroom"])
def test_bed_placement_supports_guest_and_children_bedrooms(room_name):
    room = [(0, 0), (12, 0), (12, 14), (0, 14)]
    result = sv.solve_bed_placement(room, (6.0, 6.5), room_name, facade_bearing=0.0)
    assert result[0]["room"] == room_name
    assert result[0]["satisfies_rule"] is True
    assert result[0]["compromise"] is False


def test_only_master_bedroom_has_ne_corner_avoidance():
    assert sv.BED_HEAD_DIRECTION_RULES["MasterBedroom"]["avoid_corner"] == "NE"
    assert sv.BED_HEAD_DIRECTION_RULES["GuestBedroom"]["avoid_corner"] is None
    assert sv.BED_HEAD_DIRECTION_RULES["ChildrenBedroom"]["avoid_corner"] is None


# ---------------------------------------------------------------------------
# 3. Stove placement (Kitchen)
# ---------------------------------------------------------------------------

def test_stove_placement_compliant_when_east_wall_available():
    kitchen = [(0, 0), (10, 0), (10, 8), (0, 8)]
    result = sv.solve_stove_placement(kitchen, (2.5, 2.5), facade_bearing=0.0)

    assert len(result) == 1
    placement = result[0]
    assert placement["room"] == "Kitchen"
    assert placement["object"] == "stove"
    assert placement["satisfies_rule"] is True
    assert placement["compromise"] is False
    assert placement["rotation_deg"] == pytest.approx(90.0)  # cook faces East


def test_stove_placement_compromise_when_no_east_wall_available():
    """Same staircase shape as the bed test, but with a stove footprint
    (3.5 ft wide) too wide for the 3 ft staircase segments -- only the N
    and W walls (12 ft) remain long enough, so the stove cannot face the
    preferred East direction."""
    result = sv.solve_stove_placement(AWKWARD_STAIRCASE_BEDROOM, (3.5, 2.5), facade_bearing=0.0)

    assert len(result) == 1
    placement = result[0]
    assert placement["satisfies_rule"] is False
    assert placement["compromise"] is True
    assert placement["compromise_note"]


def test_stove_placement_raises_when_it_does_not_physically_fit():
    tiny_room = [(0, 0), (2, 0), (2, 2), (0, 2)]
    with pytest.raises(ValueError):
        sv.solve_stove_placement(tiny_room, (2.5, 2.5), facade_bearing=0.0)


# ---------------------------------------------------------------------------
# Heavy-furniture wall assignment (LivingRoom)
# ---------------------------------------------------------------------------

def test_living_room_layout_recommends_south_and_west_walls():
    living_room = [(0, 0), (10, 0), (10, 12), (0, 12)]
    result = sv.solve_living_room_layout(living_room, facade_bearing=0.0)

    assert len(result) == 2
    quadrants = {round(p["rotation_deg"]) for p in result}
    assert quadrants == {180, 270}  # S and W wall bearings
    for placement in result:
        assert placement["room"] == "LivingRoom"
        assert placement["object"] == "heavy_furniture_zone"
        assert placement["satisfies_rule"] is True
        assert placement["compromise"] is False


def test_living_room_layout_only_returns_preferred_walls_not_all_four():
    """A rectangle has 4 walls; only the 2 facing S/W should be returned as
    recommendations -- the N/E walls are implicitly 'keep open' (see
    solve_living_room_layout's docstring), not emitted as placements."""
    living_room = [(0, 0), (10, 0), (10, 12), (0, 12)]
    result = sv.solve_living_room_layout(living_room, facade_bearing=0.0)
    assert len(result) == 2
