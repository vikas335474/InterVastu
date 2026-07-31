"""Unit tests for :mod:`zone_geometry`.

Covers three cases required for the deterministic zone layer:

1. A simple rectangular flat (sanity check on centroid + cardinal zones).
2. The L-shaped-flat regression fixture, where the bounding-box centre and the
   true occupied-area centroid differ by >2 ft, and a naive bounding-box
   Brahmasthan calculation produces a false-positive toilet violation that the
   correct centroid calculation avoids. This is a permanent regression test.
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
    ]
    result = zg.analyze_zones(boundary, rooms, facade_bearing=0.0)

    # Centroid of a rectangle is its geometric centre.
    assert result["brahmasthan"]["x"] == pytest.approx(15.0)
    assert result["brahmasthan"]["y"] == pytest.approx(15.0)

    assert _room(result, "north")["zone"] == "N"
    assert _room(result, "east")["zone"] == "E"
    assert _room(result, "south")["zone"] == "S"
    assert _room(result, "west")["zone"] == "W"
    assert _room(result, "northeast")["zone"] == "NE"

    # None of these off-centre rooms contain the exact centre.
    for r in result["rooms"]:
        assert r["contains_brahmasthan"] is False
        assert r["brahmasthan_distance_ft"] is None
        # Rooms sit dead-centre in their sectors -> high confidence.
        assert r["zone_confidence"] == "high"


def test_facade_bearing_rotates_zones():
    """Rotating the facade by 90 deg rotates every zone clockwise by 90 deg."""
    boundary = [(0, 0), (30, 0), (30, 30), (0, 30)]
    rooms = [{"name": "plan_up", "polygon": _square(15, 25)}]

    north_up = zg.analyze_zones(boundary, rooms, facade_bearing=0.0)
    east_up = zg.analyze_zones(boundary, rooms, facade_bearing=90.0)

    assert _room(north_up, "plan_up")["zone"] == "N"
    # With plan +y pointing East, the plan-up room now lies due East.
    assert _room(east_up, "plan_up")["zone"] == "E"


# ---------------------------------------------------------------------------
# 2. L-shaped flat regression fixture (bbox centre vs true centroid)
# ---------------------------------------------------------------------------

# 41 x 40 ft footprint with the NE corner cut out (25..41 x 25..40 removed),
# modelling the real apartment where the bug was caught by hand.
L_BOUNDARY = [(0, 0), (41, 0), (41, 25), (25, 25), (25, 40), (0, 40)]

# Toilet straddling the bounding-box centre (20.5, 20.0) but NOT the true
# area centroid (~18.36, 17.86).
L_TOILET = [(19.5, 18.5), (22.5, 18.5), (22.5, 21.5), (19.5, 21.5)]

# Living room covering the true centroid.
L_LIVING = [(3, 6), (19, 6), (19, 24), (3, 24)]


def test_lshape_bbox_center_would_false_positive():
    """Guard: the naive bounding-box centre really does fall inside the toilet.

    If this ever stops being true the regression below is meaningless, so we
    assert the bug precondition explicitly.
    """
    poly = Polygon(L_BOUNDARY)
    minx, miny, maxx, maxy = poly.bounds
    bbox_center = Point((minx + maxx) / 2.0, (miny + maxy) / 2.0)
    assert Polygon(L_TOILET).contains(bbox_center)  # naive method -> violation


def test_lshape_true_centroid_differs_from_bbox_center():
    result = zg.analyze_zones(
        L_BOUNDARY,
        [{"name": "toilet", "polygon": L_TOILET},
         {"name": "living", "polygon": L_LIVING}],
        facade_bearing=0.0,
    )
    bx = result["brahmasthan"]["x"]
    by = result["brahmasthan"]["y"]

    # True occupied-area centroid, computed independently.
    assert bx == pytest.approx(25700 / 1400, abs=1e-3)  # 18.3571
    assert by == pytest.approx(25000 / 1400, abs=1e-3)  # 17.8571

    # It must differ from the bounding-box centre (20.5, 20.0) by >= 2 ft.
    dist = math.hypot(bx - 20.5, by - 20.0)
    assert dist >= 2.0


def test_lshape_toilet_is_correct_negative_not_false_positive():
    """The core regression: toilet must NOT be flagged as containing the centre."""
    result = zg.analyze_zones(
        L_BOUNDARY,
        [{"name": "toilet", "polygon": L_TOILET},
         {"name": "living", "polygon": L_LIVING}],
        facade_bearing=0.0,
    )
    toilet = _room(result, "toilet")
    living = _room(result, "living")

    # Correct centroid: toilet does NOT contain the exact Brahmasthan point...
    assert toilet["contains_brahmasthan"] is False
    # ...but it is a near-miss (< 2 ft from a wall), surfaced for human review.
    assert toilet["brahmasthan_distance_ft"] is not None
    assert toilet["brahmasthan_distance_ft"] < zg.NEAR_MISS_FT
    assert toilet["brahmasthan_distance_ft"] == pytest.approx(1.3113, abs=1e-3)

    # The living room genuinely contains the true centre.
    assert living["contains_brahmasthan"] is True
    assert living["brahmasthan_distance_ft"] is None


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
    result = zg.analyze_zones(boundary, rooms, facade_bearing=0.0)

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
        boundary, [{"name": "r", "polygon": _square(7, 7, 0.5)}], facade_bearing=0.0
    )
    assert set(result) == {"brahmasthan", "facade_bearing", "rooms"}
    assert set(result["brahmasthan"]) == {"x", "y"}
    room = result["rooms"][0]
    for key in (
        "room", "zone", "zone_confidence", "boundary_margin_deg",
        "contains_brahmasthan", "brahmasthan_distance_ft",
    ):
        assert key in room
