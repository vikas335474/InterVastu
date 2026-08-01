"""Unit tests for :mod:`orientation`.

No test in this file hits a real network API — the footprint lookup
functions accept an injected ``query_fn``/``ms_query_fn``/``osm_query_fn``
callable, and every test here supplies a canned in-memory stand-in.
"""

import math

import pytest
from shapely.geometry import Polygon

import orientation as ori


# ---------------------------------------------------------------------------
# Synthetic footprints with known expected bearings
# ---------------------------------------------------------------------------

# Axis-aligned rectangle: long edge (30 ft) runs east-west -> bearing 90.
RECT_EW = [(0, 0), (30, 0), (30, 10), (0, 10)]

# Axis-aligned rectangle: long edge (30 ft) runs north-south -> bearing 0.
RECT_NS = [(0, 0), (10, 0), (10, 30), (0, 30)]


def _rotated_rectangle(theta_deg, length=40.0, width=10.0):
    theta = math.radians(theta_deg)
    ux, uy = math.cos(theta), math.sin(theta)
    vx, vy = -uy, ux
    return [
        (0.0, 0.0),
        (length * ux, length * uy),
        (length * ux + width * vx, length * uy + width * vy),
        (width * vx, width * vy),
    ]


# L-shaped footprint (mirrors the zone_geometry L-shaped fixture): its
# minimum rotated bounding rectangle is the full 41x40 axis-aligned box, so
# the long edge (41 ft) runs east-west -> bearing 90.
L_FOOTPRINT = [(0, 0), (41, 0), (41, 25), (25, 25), (25, 40), (0, 40)]


# ---------------------------------------------------------------------------
# 2. Facade bearing estimation
# ---------------------------------------------------------------------------

def test_rectangle_long_edge_east_west_gives_bearing_90():
    result = ori.estimate_facade_bearing_from_footprint(RECT_EW)
    assert result["facade_bearing_deg"] == pytest.approx(90.0)
    assert result["north_offset_deg"] == pytest.approx(90.0)
    assert result["source"] == "footprint_estimate"
    assert "ESTIMATE" in result["reliability_note"]
    assert result["footprint_polygon"] == [
        (0.0, 0.0), (30.0, 0.0), (30.0, 10.0), (0.0, 10.0)
    ]


def test_rectangle_long_edge_north_south_gives_bearing_0():
    result = ori.estimate_facade_bearing_from_footprint(RECT_NS)
    assert result["facade_bearing_deg"] == pytest.approx(0.0, abs=1e-6)


def test_rotated_rectangle_bearing_matches_rotation():
    footprint = _rotated_rectangle(30.0)
    result = ori.estimate_facade_bearing_from_footprint(footprint)
    # Long axis at 30 deg from +x (East) == 60 deg from North, clockwise.
    assert result["facade_bearing_deg"] == pytest.approx(60.0, abs=1e-6)


def test_lshape_footprint_bearing_from_bounding_rectangle():
    result = ori.estimate_facade_bearing_from_footprint(L_FOOTPRINT)
    assert result["facade_bearing_deg"] == pytest.approx(90.0, abs=1e-6)
    assert result["source"] == "footprint_estimate"
    # The caveat about irregular footprints must be present for callers to
    # surface to a human, since the L-shape's true facade may not align with
    # the bounding rectangle's long edge.
    assert "irregular" in result["reliability_note"]


def test_degenerate_footprint_raises():
    with pytest.raises(ValueError):
        ori.estimate_facade_bearing_from_footprint([(0, 0), (0, 0), (0, 0)])


# ---------------------------------------------------------------------------
# 1. Footprint lookup (mocked data sources, no network)
# ---------------------------------------------------------------------------

def test_lookup_prefers_ms_buildings_over_osm():
    calls = []

    def ms_query(lat, lon, data_source):
        calls.append("ms")
        return RECT_EW

    def osm_query(lat, lon, radius_m):
        calls.append("osm")
        return RECT_NS

    footprint = ori.lookup_footprint(
        12.9, 77.6,
        ms_data_source="s3://fake-bucket/india.geojson",
        ms_query_fn=ms_query,
        osm_query_fn=osm_query,
    )
    assert footprint == RECT_EW
    assert calls == ["ms"]  # OSM fallback never invoked


def test_lookup_falls_back_to_osm_when_ms_misses():
    def ms_query(lat, lon, data_source):
        return None

    def osm_query(lat, lon, radius_m):
        return RECT_NS

    footprint = ori.lookup_footprint(
        12.9, 77.6,
        ms_data_source="s3://fake-bucket/india.geojson",
        ms_query_fn=ms_query,
        osm_query_fn=osm_query,
    )
    assert footprint == RECT_NS


def test_lookup_returns_none_when_both_sources_miss():
    footprint = ori.lookup_footprint(
        12.9, 77.6,
        ms_data_source="s3://fake-bucket/india.geojson",
        ms_query_fn=lambda lat, lon, ds: None,
        osm_query_fn=lambda lat, lon, r: None,
    )
    assert footprint is None


def test_lookup_with_no_query_fns_configured_returns_none():
    # No data source wired up yet -> must not fabricate a footprint.
    assert ori.lookup_footprint(12.9, 77.6) is None


def test_estimate_facade_bearing_not_found_result_shape():
    result = ori.estimate_facade_bearing(
        12.9, 77.6,
        ms_data_source="s3://fake-bucket/india.geojson",
        ms_query_fn=lambda lat, lon, ds: None,
        osm_query_fn=lambda lat, lon, r: None,
    )
    assert result == {
        "facade_bearing_deg": None,
        "north_offset_deg": None,
        "source": "not_found",
        "reliability_note": ori.NOT_FOUND_RELIABILITY_NOTE,
        "footprint_polygon": None,
    }


def test_estimate_facade_bearing_end_to_end_via_ms_source():
    result = ori.estimate_facade_bearing(
        12.9, 77.6,
        ms_data_source="s3://fake-bucket/india.geojson",
        ms_query_fn=lambda lat, lon, ds: RECT_EW,
    )
    assert result["source"] == "footprint_estimate"
    assert result["facade_bearing_deg"] == pytest.approx(90.0)
    assert result["north_offset_deg"] == pytest.approx(90.0)


# ---------------------------------------------------------------------------
# 3. Manual override path
# ---------------------------------------------------------------------------

def test_manual_bearing_has_manual_source_and_no_lookup_dependency():
    result = ori.manual_facade_bearing(123.456)
    assert result["facade_bearing_deg"] == pytest.approx(123.456)
    assert result["north_offset_deg"] == pytest.approx(123.456)
    assert result["source"] == "manual"
    assert result["footprint_polygon"] is None
    assert result["reliability_note"] == ori.MANUAL_RELIABILITY_NOTE


def test_manual_bearing_normalises_out_of_range_input():
    result = ori.manual_facade_bearing(-30.0)
    assert result["facade_bearing_deg"] == pytest.approx(330.0)
    assert result["north_offset_deg"] == pytest.approx(330.0)

    result2 = ori.manual_facade_bearing(390.0)
    assert result2["facade_bearing_deg"] == pytest.approx(30.0)
    assert result2["north_offset_deg"] == pytest.approx(30.0)


def test_manual_bearing_passes_through_optional_footprint():
    result = ori.manual_facade_bearing(45.0, footprint_polygon=RECT_EW)
    assert result["footprint_polygon"] == [
        (0.0, 0.0), (30.0, 0.0), (30.0, 10.0), (0.0, 10.0)
    ]


# ---------------------------------------------------------------------------
# Output-shape parity between automated and manual paths
# ---------------------------------------------------------------------------

def test_automated_and_manual_outputs_share_schema():
    automated = ori.estimate_facade_bearing_from_footprint(RECT_EW)
    manual = ori.manual_facade_bearing(90.0, footprint_polygon=RECT_EW)
    assert set(automated) == set(manual) == {
        "facade_bearing_deg", "north_offset_deg", "source", "reliability_note",
        "footprint_polygon",
    }


def test_north_offset_deg_aliases_facade_bearing_deg_for_automated_and_manual():
    """Documents the current assumption (see module docstring): plan-up is
    assumed to face the detected/provided facade, so north_offset_deg is
    currently a plain alias of facade_bearing_deg, not an independent value."""
    automated = ori.estimate_facade_bearing_from_footprint(RECT_EW)
    assert automated["north_offset_deg"] == automated["facade_bearing_deg"]

    manual = ori.manual_facade_bearing(77.0)
    assert manual["north_offset_deg"] == manual["facade_bearing_deg"]
