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
