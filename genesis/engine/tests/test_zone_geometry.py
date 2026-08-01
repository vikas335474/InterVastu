"""Unit tests for :mod:`zone_geometry`.

Covers the cases required for the Phase 1b deterministic zone-geometry layer:

1. A simple rectangular flat: centroid at the obvious middle, cardinal zones,
   a dead-centre room that both contains the centre point and overlaps the
   Brahmasthan region, and a corner room that does neither.
2. The L-shaped-flat regression fixture (permanent): the bounding-box centre
   and the true occupied-area centroid differ by >= 2 ft. A toilet placed
   near the true centre must NOT contain the exact centroid point but MUST
   overlap the central-1/9 Brahmasthan region -- this is the real bug found
   by hand on an actual L-shaped flat, plus the corrected region-based
   reading, both encoded together.
3. A boundary-uncertainty case, where a room's bearing sits within 3 deg of a
   sector edge and must be flagged ``"low"`` confidence.
"""

import math

import pytest
from shapely.geometry import Point, Polygon

import zone_geometry as zg


def _square(cx, cy, half=1.0):
    """A small axis-aligned square room polygon centred on (cx, cy)."""
    return [
        (cx - half, cy - half),
        (cx + half, cy - half),
        (cx + half, cy + half),
        (cx - half, cy + half),
    ]


def _room(result, name):
    for r in result["rooms"]:
        if r["room"] == name:
            return r
    raise AssertionError(f"room {name!r} not in result")


# ---------------------------------------------------------------------------
# 1. Sanity: simple rectangular flat
# ---------------------------------------------------------------------------

def test_rectangular_flat_centroid_and_cardinal_zones():
    boundary = [(0, 0), (30, 0), (30, 30), (0, 30)]
    rooms = [
        {"name": "north", "polygon": _square(15, 25)},
        {"name": "east", "polygon": _square(25, 15)},
        {"name": "south", "polygon": _square(15, 5)},
        {"name": "west", "polygon": _square(5, 15)},
        {"name": "northeast", "polygon": _square(25, 25)},
        {"name": "centre_room", "polygon": _square(15, 15, half=2.0)},
        {"name": "corner_room", "polygon": _square(28, 28, half=1.0)},
    ]
    result = zg.analyze_zones(boundary, rooms, north_offset_deg=0.0)

    # Centroid of a rectangle is its geometric centre.
    assert result["centre"]["x"] == pytest.approx(15.0)
    assert result["centre"]["y"] == pytest.approx(15.0)

    assert _room(result, "north")["zone"] == "N"
    assert _room(result, "east")["zone"] == "E"
    assert _room(result, "south")["zone"] == "S"
    assert _room(result, "west")["zone"] == "W"
    assert _room(result, "northeast")["zone"] == "NE"

    # A room placed dead-centre both contains the exact centre point AND
    # overlaps the central Brahmasthan region.
    centre_room = _room(result, "centre_room")
    assert centre_room["contains_centre_point"] is True
    assert centre_room["overlaps_brahmasthan_region"] is True
    assert centre_room["region_overlap_fraction"] > 0.0

    # A corner room does neither, and isn't even a near-miss.
    corner_room = _room(result, "corner_room")
    assert corner_room["contains_centre_point"] is False
    assert corner_room["overlaps_brahmasthan_region"] is False
    assert corner_room["region_overlap_fraction"] == 0.0
    assert corner_room["nearest_distance_ft"] is None

    # None of the off-centre perimeter rooms contain the exact centre.
    for name in ("north", "east", "south", "west", "northeast"):
        r = _room(result, name)
        assert r["contains_centre_point"] is False
        # Rooms sit dead-centre in their sectors -> high confidence.
        assert r["zone_confidence"] == "high"


def test_north_offset_rotates_zones():
    """Rotating north_offset_deg by 90 rotates every zone clockwise by 90."""
    boundary = [(0, 0), (30, 0), (30, 30), (0, 30)]
    rooms = [{"name": "plan_up", "polygon": _square(15, 25)}]

    north_up = zg.analyze_zones(boundary, rooms, north_offset_deg=0.0)
    east_up = zg.analyze_zones(boundary, rooms, north_offset_deg=90.0)

    assert _room(north_up, "plan_up")["zone"] == "N"
    # With plan +y rotated to point East (true north offset 90), the
    # plan-up room now reads as due East.
    assert _room(east_up, "plan_up")["zone"] == "E"


def test_brahmasthan_region_is_scaled_boundary_about_centre():
    boundary = [(0, 0), (30, 0), (30, 30), (0, 30)]
    result = zg.analyze_zones(boundary, [], north_offset_deg=0.0)

    region_poly = Polygon(result["brahmasthan_region"])
    boundary_poly = Polygon(boundary)

    # Default area fraction is 1/9 (linear factor 1/3).
    assert region_poly.area == pytest.approx(boundary_poly.area / 9.0, rel=1e-6)
    assert result["params"]["brahmasthan_area_fraction"] == pytest.approx(1.0 / 9.0)
    # The region is centred on the same point as the boundary centroid.
    assert region_poly.centroid.x == pytest.approx(result["centre"]["x"])
    assert region_poly.centroid.y == pytest.approx(result["centre"]["y"])


def test_brahmasthan_area_fraction_is_configurable():
    boundary = [(0, 0), (30, 0), (30, 30), (0, 30)]
    result = zg.analyze_zones(
        boundary, [], north_offset_deg=0.0, brahmasthan_area_fraction=1.0 / 81.0
    )
    region_poly = Polygon(result["brahmasthan_region"])
    boundary_poly = Polygon(boundary)
    assert region_poly.area == pytest.approx(boundary_poly.area / 81.0, rel=1e-6)


# ---------------------------------------------------------------------------
# 2. L-shaped flat regression fixture (bbox centre vs true centroid;
#    point-containment vs region-overlap)
# ---------------------------------------------------------------------------

# 41 x 40 ft footprint with the NE corner cut out (25..41 x 25..40 removed),
# modelling the real apartment where the bug was caught by hand.
L_BOUNDARY = [(0, 0), (41, 0), (41, 25), (25, 25), (25, 40), (0, 40)]

# Toilet near the true centroid. It does NOT straddle the exact centroid
# point, but it DOES overlap the central-1/9 Brahmasthan region.
L_TOILET = [(19.0, 16.0), (22.0, 16.0), (22.0, 20.0), (19.0, 20.0)]

# Living room covering the true centroid.
L_LIVING = [(3, 6), (19, 6), (19, 24), (3, 24)]


def test_lshape_bbox_center_differs_from_true_centroid():
    poly = Polygon(L_BOUNDARY)
    minx, miny, maxx, maxy = poly.bounds
    bbox_center = (( minx + maxx) / 2.0, (miny + maxy) / 2.0)

    result = zg.analyze_zones(
        L_BOUNDARY,
        [{"name": "toilet", "polygon": L_TOILET}, {"name": "living", "polygon": L_LIVING}],
        north_offset_deg=0.0,
    )
    cx, cy = result["centre"]["x"], result["centre"]["y"]

    # True occupied-area centroid, computed independently.
    assert cx == pytest.approx(25700 / 1400, abs=1e-3)  # 18.3571
    assert cy == pytest.approx(25000 / 1400, abs=1e-3)  # 17.8571

    # (i) computed centre must differ from the bounding-box centre by >= 2 ft.
    dist = math.hypot(cx - bbox_center[0], cy - bbox_center[1])
    assert dist >= 2.0


def test_lshape_toilet_overlaps_region_but_not_exact_point():
    result = zg.analyze_zones(
        L_BOUNDARY,
        [{"name": "toilet", "polygon": L_TOILET}, {"name": "living", "polygon": L_LIVING}],
        north_offset_deg=0.0,
    )
    toilet = _room(result, "toilet")
    living = _room(result, "living")

    # (ii) contains_centre_point is False for the toilet: it does not
    # straddle the exact centroid.
    assert toilet["contains_centre_point"] is False

    # (iii) overlaps_brahmasthan_region is True for the toilet: the
    # traditionally-correct region-based reading still catches it.
    assert toilet["overlaps_brahmasthan_region"] is True
    assert toilet["region_overlap_fraction"] > 0.0
    # A room that overlaps the region is not a "near miss" -- it's a direct hit.
    assert toilet["nearest_distance_ft"] is None

    # The living room genuinely contains the true centre point too.
    assert living["contains_centre_point"] is True
    assert living["overlaps_brahmasthan_region"] is True


def test_lshape_near_miss_room_reports_nearest_distance():
    """A room close to, but not touching, the Brahmasthan region is surfaced."""
    result = zg.analyze_zones(
        L_BOUNDARY,
        [{"name": "toilet", "polygon": L_TOILET}],
        north_offset_deg=0.0,
    )
    region_poly = Polygon(result["brahmasthan_region"])

    # Build a small room just outside the region on its west edge.
    minx = region_poly.bounds[0]
    near_miss_room = [
        (minx - 1.5, 15.0), (minx - 0.5, 15.0), (minx - 0.5, 17.0), (minx - 1.5, 17.0),
    ]
    result2 = zg.analyze_zones(
        L_BOUNDARY,
        [{"name": "near_miss", "polygon": near_miss_room}],
        north_offset_deg=0.0,
    )
    near_miss = _room(result2, "near_miss")
    assert near_miss["contains_centre_point"] is False
    assert near_miss["overlaps_brahmasthan_region"] is False
    assert near_miss["nearest_distance_ft"] is not None
    assert near_miss["nearest_distance_ft"] < zg.NEAR_MISS_FT


# ---------------------------------------------------------------------------
# 3. Boundary-uncertainty case (bearing within 3 deg of a sector edge)
# ---------------------------------------------------------------------------

def test_bearing_near_sector_edge_flagged_low_confidence():
    boundary = [(0, 0), (30, 0), (30, 30), (0, 30)]  # centroid (15, 15)

    # Target a true bearing of ~32 deg: 1.75 deg shy of the NNE/NE edge at
    # 33.75 deg. dx = 10*tan(32), dy = 10.
    dx = 10.0 * math.tan(math.radians(32.0))
    edge_room_centroid = (15.0 + dx, 15.0 + 10.0)

    # A control room sitting dead-centre in the NE sector (bearing 45 deg).
    center_room_centroid = (15.0 + 10.0, 15.0 + 10.0)

    rooms = [
        {"name": "edge", "polygon": _square(*edge_room_centroid, half=0.25)},
        {"name": "center", "polygon": _square(*center_room_centroid, half=0.25)},
    ]
    result = zg.analyze_zones(boundary, rooms, north_offset_deg=0.0)

    edge = _room(result, "edge")
    center = _room(result, "center")

    # Edge room: within 3 deg of the sector edge -> low confidence, NNE.
    assert edge["zone"] == "NNE"
    assert edge["zone_confidence"] == "low"
    assert edge["boundary_margin_deg"] < 3.0
    assert edge["boundary_margin_deg"] == pytest.approx(1.75, abs=1e-2)

    # Control room: dead-centre of NE -> high confidence, full 11.25 margin.
    assert center["zone"] == "NE"
    assert center["zone_confidence"] == "high"
    assert center["boundary_margin_deg"] == pytest.approx(11.25, abs=1e-2)


def test_low_confidence_margin_threshold_constant():
    """The low-confidence threshold is the documented 5 deg."""
    assert zg.LOW_CONFIDENCE_MARGIN_DEG == 5.0


# ---------------------------------------------------------------------------
# Sector-math unit checks
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "bearing,expected",
    [
        (0.0, "N"), (11.24, "N"), (11.25, "NNE"), (22.5, "NNE"),
        (45.0, "NE"), (90.0, "E"), (180.0, "S"), (270.0, "W"),
        (337.5, "NNW"), (348.75, "N"), (359.9, "N"),
    ],
)
def test_sector_name_boundaries(bearing, expected):
    assert zg.sector_name(bearing) == expected


def test_output_schema_shape():
    boundary = [(0, 0), (10, 0), (10, 10), (0, 10)]
    result = zg.analyze_zones(
        boundary, [{"name": "r", "polygon": _square(7, 7, 0.5)}], north_offset_deg=0.0
    )
    assert set(result) == {"centre", "brahmasthan_region", "params", "rooms"}
    assert set(result["centre"]) == {"x", "y"}
    assert set(result["params"]) == {"north_offset_deg", "brahmasthan_area_fraction"}
    room = result["rooms"][0]
    for key in (
        "room", "zone", "zone_confidence", "boundary_margin_deg",
        "contains_centre_point", "overlaps_brahmasthan_region",
        "region_overlap_fraction", "nearest_distance_ft",
    ):
        assert key in room
