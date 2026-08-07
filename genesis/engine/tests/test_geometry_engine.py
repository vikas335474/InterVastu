"""Unit tests for :mod:`geometry_engine`.

Covers:
1. ``rotate_point`` / ``rotate_polygon`` — pure rotation math sanity checks.
2. ``align_to_true_north`` — the compass-vs-math sign equivalence with
   ``zone_geometry.bearing_deg`` (this is the property the module docstring
   claims is *verified*, not just derived by hand).
3. ``pada_grid`` — cell count, full-occupancy sanity on a simple square
   flat, and that a room outside a cell contributes zero occupancy there.
"""

import math

import pytest

import geometry_engine as ge
import zone_geometry as zg


# ---------------------------------------------------------------------------
# rotate_point / rotate_polygon
# ---------------------------------------------------------------------------

def test_rotate_point_identity_at_zero_degrees():
    p = (3.0, 4.0)
    assert ge.rotate_point(p, 0.0, origin=(1.0, 1.0)) == pytest.approx(p)


def test_rotate_point_90deg_about_origin():
    # Standard CCW rotation: (1, 0) rotated 90 deg CCW about origin -> (0, 1).
    x, y = ge.rotate_point((1.0, 0.0), 90.0, origin=(0.0, 0.0))
    assert x == pytest.approx(0.0, abs=1e-9)
    assert y == pytest.approx(1.0, abs=1e-9)


def test_rotate_point_about_nonzero_origin_preserves_distance():
    origin = (5.0, -2.0)
    p = (8.0, 3.0)
    rotated = ge.rotate_point(p, 37.0, origin=origin)
    d_before = math.hypot(p[0] - origin[0], p[1] - origin[1])
    d_after = math.hypot(rotated[0] - origin[0], rotated[1] - origin[1])
    assert d_after == pytest.approx(d_before)


def test_rotate_polygon_rotates_every_vertex():
    square = [(0, 0), (2, 0), (2, 2), (0, 2)]
    rotated = ge.rotate_polygon(square, 90.0, origin=(1.0, 1.0))
    assert len(rotated) == len(square)
    # A square rotated 90 deg about its own centre maps back onto itself
    # (as a set of vertices, in some order).
    assert set(round(x, 6) for x, y in rotated) <= {0.0, 2.0}
    assert set(round(y, 6) for x, y in rotated) <= {0.0, 2.0}


# ---------------------------------------------------------------------------
# align_to_true_north: compass/math sign equivalence
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("north_offset_deg", [0.0, 30.0, 90.0, 145.0, 200.0, 315.0])
def test_align_to_true_north_preserves_bearing(north_offset_deg):
    centre = (0.0, 0.0)
    target = (3.0, 4.0)

    original_bearing = zg.bearing_deg(centre, target, north_offset_deg)

    (rotated_target,) = ge.align_to_true_north([target], north_offset_deg, centre)
    rotated_bearing = zg.bearing_deg(centre, rotated_target, 0.0)

    assert rotated_bearing == pytest.approx(original_bearing, abs=1e-6)


def test_align_to_true_north_preserves_distance_from_origin():
    centre = (10.0, -5.0)
    target = (13.0, -1.0)
    (rotated,) = ge.align_to_true_north([target], 77.0, centre)
    d_before = math.hypot(target[0] - centre[0], target[1] - centre[1])
    d_after = math.hypot(rotated[0] - centre[0], rotated[1] - centre[1])
    assert d_after == pytest.approx(d_before)


# ---------------------------------------------------------------------------
# pada_grid
# ---------------------------------------------------------------------------

def test_pada_grid_cell_count_and_full_occupancy_for_square_flat():
    boundary = [(0, 0), (9, 0), (9, 9), (0, 9)]
    result = ge.pada_grid(boundary, rooms=[], north_offset_deg=0.0, order=9)

    assert result["order"] == 9
    assert len(result["cells"]) == 81
    # A 9x9 boundary aligned to a 9-cell grid with no rotation: every cell
    # is fully inside the boundary.
    for cell in result["cells"]:
        assert cell["boundary_occupancy_fraction"] == pytest.approx(1.0)


def test_pada_grid_room_occupancy_localised_to_its_own_cells():
    boundary = [(0, 0), (9, 0), (9, 9), (0, 9)]
    # A 1x1 room sitting exactly in the (row=0, col=0) south-west cell.
    room = ("closet", [(0, 0), (1, 0), (1, 1), (0, 1)])
    result = ge.pada_grid(boundary, rooms=[room], north_offset_deg=0.0, order=9)

    sw_cell = next(c for c in result["cells"] if c["row"] == 0 and c["col"] == 0)
    assert sw_cell["room_occupancy"]["closet"] == pytest.approx(1.0)

    far_cell = next(c for c in result["cells"] if c["row"] == 8 and c["col"] == 8)
    assert "closet" not in far_cell["room_occupancy"]


def test_pada_grid_default_order_is_paramasayika():
    boundary = [(0, 0), (10, 0), (10, 10), (0, 10)]
    result = ge.pada_grid(boundary, rooms=[], north_offset_deg=0.0)
    assert result["order"] == ge.PARAMASAYIKA_ORDER == 9


def test_pada_grid_rejects_nonpositive_order():
    boundary = [(0, 0), (1, 0), (1, 1), (0, 1)]
    with pytest.raises(ValueError):
        ge.pada_grid(boundary, rooms=[], north_offset_deg=0.0, order=0)


# ---------------------------------------------------------------------------
# pada_devata_45 — second, experimental method; must coexist with pada_grid
# ---------------------------------------------------------------------------

def _cell(result, row, col):
    return next(c for c in result["cells"] if c["row"] == row and c["col"] == col)


def test_pada_devata_45_does_not_change_pada_grid_output():
    boundary = [(0, 0), (9, 0), (9, 9), (0, 9)]
    room = ("closet", [(0, 0), (1, 0), (1, 1), (0, 1)])

    before = ge.pada_grid(boundary, rooms=[room], north_offset_deg=15.0)
    ge.pada_devata_45(boundary, rooms=[room], north_offset_deg=15.0)
    after = ge.pada_grid(boundary, rooms=[room], north_offset_deg=15.0)

    assert before == after


def test_pada_devata_45_places_corner_and_midpoint_anchors():
    boundary = [(0, 0), (9, 0), (9, 9), (0, 9)]
    result = ge.pada_devata_45(boundary, rooms=[], north_offset_deg=0.0)

    assert _cell(result, 8, 8)["devata"] == "Ishana (a form of Shiva)"  # NE corner
    assert _cell(result, 0, 8)["devata"] == "Agni"  # SE corner
    assert _cell(result, 0, 0)["devata"] == "Nirriti"  # SW corner
    assert _cell(result, 8, 0)["devata"] == "Vayu"  # NW corner
    assert _cell(result, 4, 4)["devata"] == "Brahma (Vastu Purusha at the Brahmasthan)"


def test_pada_devata_45_leaves_unsourced_cells_unpopulated_and_flagged():
    boundary = [(0, 0), (9, 0), (9, 9), (0, 9)]
    result = ge.pada_devata_45(boundary, rooms=[], north_offset_deg=0.0)

    # (1, 1) is a border cell but not one of the 8 named anchors.
    cell = _cell(result, 1, 1)
    assert cell["devata"] is None
    assert cell["needs_verification"] is True

    # A named anchor must NOT be flagged as needing verification.
    corner = _cell(result, 8, 8)
    assert corner["needs_verification"] is False

    assert "disclaimer" in result
    assert result["disclaimer"] == ge.DEVATA_45_DISCLAIMER


def test_pada_devata_45_overrides_apply_and_clear_verification_flag():
    boundary = [(0, 0), (9, 0), (9, 9), (0, 9)]
    result = ge.pada_devata_45(
        boundary, rooms=[], north_offset_deg=0.0,
        overrides={(1, 1): "Parjanya"},
    )
    cell = _cell(result, 1, 1)
    assert cell["devata"] == "Parjanya"
    assert cell["needs_verification"] is False


# ---------------------------------------------------------------------------
# entrance_pada — 32-cell perimeter ring location
# ---------------------------------------------------------------------------

SQUARE_9 = [(0, 0), (9, 0), (9, 9), (0, 9)]


def test_perimeter_ring_has_exactly_32_cells_for_9x9():
    ring = ge._perimeter_ring_cells(9)
    assert len(ring) == 32
    assert len(set(ring)) == 32, "ring must not repeat a cell (corners once each)"
    # Every ring cell is genuinely on the border.
    assert all(r in (0, 8) or c in (0, 8) for r, c in ring)


def test_perimeter_ring_starts_nw_and_runs_clockwise():
    ring = ge._perimeter_ring_cells(9)
    # row 8 = north edge, col 0 = west edge -> NW corner is the origin.
    assert ring[0] == (8, 0)
    # Clockwise from NW along the north edge means col increases first.
    assert ring[1] == (8, 1)
    # ...and the north edge ends at the NE corner.
    assert ring[8] == (8, 8)


def test_entrance_pada_locates_opening_on_north_edge():
    # A 1 ft opening centred on the north wall, well inside one pada.
    opening = [(4.2, 9), (4.8, 9)]
    result = ge.entrance_pada(SQUARE_9, opening, north_offset_deg=0.0)

    assert result["ring_size"] == 32
    assert result["primary"]["side"] == "N"
    assert result["primary"]["row"] == 8  # north edge
    assert result["primary"]["col"] == 4  # middle column
    assert result["primary"]["overlap_fraction"] == pytest.approx(1.0)
    assert result["straddles_multiple_padas"] is False


def test_entrance_pada_reports_straddle_rather_than_rounding():
    # Opening deliberately centred on the boundary between col 3 and col 4.
    opening = [(3.5, 9), (4.5, 9)]
    result = ge.entrance_pada(SQUARE_9, opening, north_offset_deg=0.0)

    assert result["straddles_multiple_padas"] is True
    assert len(result["padas"]) == 2
    assert {p["col"] for p in result["padas"]} == {3, 4}
    # Shares are reported, and sum to the whole opening.
    assert sum(p["overlap_fraction"] for p in result["padas"]) == pytest.approx(1.0)


def test_entrance_pada_accepts_a_marker_rectangle():
    # The Unit 12 fixture models its entrance as a small rectangle, not a
    # segment — the longest axis is taken as the opening line.
    marker = [(3.9, 9), (4.1, 9), (4.1, 8.6), (3.9, 8.6)]
    result = ge.entrance_pada(SQUARE_9, marker, north_offset_deg=0.0)
    assert result["primary"]["side"] in ("N", "NW", "NE")


def test_entrance_pada_ratings_are_injected_never_invented():
    opening = [(4.2, 9), (4.8, 9)]

    unrated = ge.entrance_pada(SQUARE_9, opening, north_offset_deg=0.0)
    assert unrated["primary"]["rating"] is None
    assert unrated["primary"]["needs_verification"] is True

    idx = unrated["primary"]["ring_index"]
    rated = ge.entrance_pada(
        SQUARE_9, opening, north_offset_deg=0.0, ratings={idx: "auspicious"}
    )
    assert rated["primary"]["rating"] == "auspicious"
    assert rated["primary"]["needs_verification"] is False


def test_entrance_pada_result_always_carries_the_disclaimer():
    result = ge.entrance_pada(SQUARE_9, [(4.2, 9), (4.8, 9)], north_offset_deg=0.0)
    assert result["disclaimer"] == ge.ENTRANCE_PADA_DISCLAIMER


def test_entrance_pada_rotates_with_north_offset():
    """The same physical opening lands on a different compass side once the
    plan's own north offset is applied — the whole point of the rotation."""
    opening = [(4.2, 9), (4.8, 9)]
    facing_north = ge.entrance_pada(SQUARE_9, opening, north_offset_deg=0.0)
    # Rotate the plan 90 deg: plan-up now points East, so a plan-up wall
    # becomes an east-facing wall.
    rotated = ge.entrance_pada(SQUARE_9, opening, north_offset_deg=90.0)
    assert facing_north["primary"]["side"] == "N"
    assert rotated["primary"]["side"] == "E"


def test_entrance_pada_rejects_interior_door():
    # An opening in the middle of the plot touches no perimeter pada.
    with pytest.raises(ValueError, match="perimeter pada ring"):
        ge.entrance_pada(SQUARE_9, [(4.0, 4.5), (5.0, 4.5)], north_offset_deg=0.0)


def test_entrance_pada_rejects_degenerate_opening():
    with pytest.raises(ValueError, match="at least 2 distinct points"):
        ge.entrance_pada(SQUARE_9, [(4.0, 9.0), (4.0, 9.0)], north_offset_deg=0.0)


def test_pada_devata_45_override_can_replace_a_builtin_anchor():
    boundary = [(0, 0), (9, 0), (9, 9), (0, 9)]
    result = ge.pada_devata_45(
        boundary, rooms=[], north_offset_deg=0.0,
        overrides={(8, 8): "Custom Ishana Spelling"},
    )
    assert _cell(result, 8, 8)["devata"] == "Custom Ishana Spelling"
