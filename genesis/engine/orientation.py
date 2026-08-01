"""Facade-orientation detection for a Vastu compliance engine.

This module determines a building's *true-north facade bearing* from its
footprint geometry, to avoid relying on phone compass readings (measured to
carry 15-20 degree real-world error from magnetic interference indoors).

Responsibilities
----------------
1. Footprint lookup   : given a lat/lon, fetch the building's footprint
                        polygon, preferring Microsoft's Global ML Building
                        Footprints dataset with an OSM Overpass fallback.
2. Bearing estimation : from a footprint polygon, compute the minimum
                        rotated bounding rectangle and derive the compass
                        bearing of its long edge, as a labelled *estimate*.
3. Manual override    : accept a human-provided facade bearing directly,
                        in the same output shape but tagged ``"source":
                        "manual"``, with no dependency on (1) or (2).

IMPORTANT — reliability caveat
-------------------------------
The footprint-estimate path (steps 1-2) assumes an approximately
rectangular footprint. For irregular, multi-wing, or podium-style
buildings the detected long edge may not correspond to the actual unit's
facade at all. **This estimate must always be presented to a human for
confirmation before being used in a paid report** — it is not a
substitute for the manual override path in production use.

Coordinate & bearing conventions
---------------------------------
* Footprint polygons are lists of ``(lon, lat)`` or local ``(x, y)``
  vertices, matched to whatever CRS the caller's data source provides.
  Bearing computation only depends on relative vertex geometry.
* Compass bearings use the surveyor convention: **0 deg = true North**,
  increasing **clockwise** (90 = East, 180 = South, 270 = West), reported
  as a value in ``[0, 360)``.

Connecting to ``zone_geometry.py``
-----------------------------------
Every result here also carries a ``north_offset_deg`` value, in the exact
convention ``zone_geometry.analyze_zones()`` expects: the true compass
bearing of the *floor plan's own* ``+y`` (plan-up) direction. This module
assumes the floor plan is drawn with plan-up facing the detected/provided
facade — i.e. ``north_offset_deg == facade_bearing_deg`` — so it is
currently a plain alias, not an independent computation. That assumption is
reasonable for a simple rectangular unit plan but may not hold once
multi-wing/podium geometry or an unconventional plan orientation is in the
mix; it is surfaced as its own field (rather than silently reused under the
``facade_bearing_deg`` name) specifically so a later integration session can
revisit it without a shape change. No integration with ``zone_geometry.py``
happens in this module — that is a separate, later session.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Sequence

from shapely.geometry import Polygon

Coord = tuple[float, float]

#: Reliability note attached to every automated footprint-based estimate.
FOOTPRINT_ESTIMATE_RELIABILITY_NOTE: str = (
    "This facade bearing is an automated ESTIMATE derived from the building "
    "footprint's minimum rotated bounding rectangle. It assumes an "
    "approximately rectangular footprint; for irregular, multi-wing, or "
    "podium-style buildings the detected edge may not correspond to the "
    "actual unit's facade. This estimate MUST be confirmed by a human "
    "before being used in a paid report — it is not a substitute for the "
    "manual override path."
)

#: Reliability note attached to a human-provided manual bearing.
MANUAL_RELIABILITY_NOTE: str = (
    "This facade bearing was provided directly by a human (e.g. via a UI "
    "where the floor plan is rotated onto a satellite image) and is not a "
    "footprint-derived estimate."
)

#: Reliability note attached when no footprint could be found.
NOT_FOUND_RELIABILITY_NOTE: str = (
    "No building footprint could be found for this coordinate from either "
    "the primary or fallback data source. No facade bearing has been "
    "guessed or fabricated; a manual bearing is required."
)


# ---------------------------------------------------------------------------
# 1. Footprint lookup
# ---------------------------------------------------------------------------

def fetch_footprint_ms_buildings(
    lat: float,
    lon: float,
    *,
    data_source: str,
    query_fn: Callable[[float, float, str], Sequence[Coord] | None] | None = None,
) -> Sequence[Coord] | None:
    """Look up a building footprint from a Microsoft Global ML Building
    Footprints extract.

    Parameters
    ----------
    lat, lon
        Query coordinate.
    data_source
        Path or URL to a local extract or hosted copy of the India tile(s)
        of the dataset. This function does not assume any specific hosting
        setup — the caller wires up the actual storage/query mechanism via
        ``query_fn``.
    query_fn
        Callable performing the actual lookup against ``data_source``,
        returning a footprint polygon as a list of ``(lon, lat)`` vertices,
        or ``None`` if nothing is found there. Injected so tests can mock
        the data source without touching the network or disk. If omitted,
        this function returns ``None`` (i.e. "not configured yet").

    Returns
    -------
    list of (x, y) tuples, or None if no footprint was found.
    """
    if query_fn is None:
        return None
    return query_fn(lat, lon, data_source)


def fetch_footprint_osm_overpass(
    lat: float,
    lon: float,
    *,
    radius_m: float = 50.0,
    query_fn: Callable[[float, float, float], Sequence[Coord] | None] | None = None,
) -> Sequence[Coord] | None:
    """Fallback footprint lookup via an OSM Overpass query for ``building``
    tagged ways within ``radius_m`` metres of the coordinate.

    NOTE: OSM building-footprint coverage in India is inconsistent (many
    buildings are untagged or missing entirely), so this path is a fallback
    only — prefer the Microsoft dataset lookup first.

    ``query_fn`` performs the actual Overpass API call/parsing and is
    injected so tests can supply canned results without hitting the
    network. If omitted, this function returns ``None``.
    """
    if query_fn is None:
        return None
    return query_fn(lat, lon, radius_m)


def lookup_footprint(
    lat: float,
    lon: float,
    *,
    ms_data_source: str | None = None,
    ms_query_fn: Callable[[float, float, str], Sequence[Coord] | None] | None = None,
    osm_query_fn: Callable[[float, float, float], Sequence[Coord] | None] | None = None,
    osm_radius_m: float = 50.0,
) -> Sequence[Coord] | None:
    """Try the Microsoft dataset first, then fall back to OSM Overpass.

    Returns ``None`` (never a guessed/fabricated polygon) if neither source
    has a usable footprint.
    """
    if ms_data_source is not None:
        footprint = fetch_footprint_ms_buildings(
            lat, lon, data_source=ms_data_source, query_fn=ms_query_fn
        )
        if footprint:
            return footprint

    footprint = fetch_footprint_osm_overpass(
        lat, lon, radius_m=osm_radius_m, query_fn=osm_query_fn
    )
    if footprint:
        return footprint

    return None


# ---------------------------------------------------------------------------
# 2. Facade bearing calculation (footprint-estimate path)
# ---------------------------------------------------------------------------

def _rectangle_bearing_deg(rect: Polygon) -> float:
    """Compass bearing (0-360, N=0, clockwise) of a rectangle's long edge.

    ``rect`` is expected to be a 4-sided rectangle (e.g. Shapely's
    ``minimum_rotated_rectangle``). Its own exterior-coordinate order is
    used directly, so the returned bearing is one of the two directions
    along the long axis (a bearing and its +180 reciprocal are equivalent
    facade orientations).
    """
    coords = list(rect.exterior.coords)[:-1]  # drop the closing duplicate
    if len(coords) != 4:
        raise ValueError(
            f"expected a 4-vertex rectangle, got {len(coords)} vertices"
        )

    edges = []
    for i in range(4):
        (x1, y1), (x2, y2) = coords[i], coords[(i + 1) % 4]
        length = math.hypot(x2 - x1, y2 - y1)
        edges.append((length, x2 - x1, y2 - y1))

    _, dx, dy = max(edges, key=lambda e: e[0])
    bearing = math.degrees(math.atan2(dx, dy)) % 360.0
    # Normalise to [0, 180) since a facade edge and its reciprocal describe
    # the same wall orientation.
    return bearing % 180.0


def estimate_facade_bearing_from_footprint(
    footprint_polygon: Sequence[Coord],
) -> dict[str, Any]:
    """Estimate the facade bearing from a footprint polygon's minimum
    rotated bounding rectangle.

    This assumes an approximately rectangular footprint (see module
    docstring). The result is always labelled as an estimate requiring
    human confirmation via ``reliability_note``.
    """
    poly = Polygon(footprint_polygon)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty or poly.area == 0.0:
        raise ValueError("footprint polygon is degenerate (zero area)")

    rect = poly.minimum_rotated_rectangle
    bearing = _rectangle_bearing_deg(rect)

    return {
        "facade_bearing_deg": round(float(bearing), 6),
        "north_offset_deg": round(float(bearing), 6),
        "source": "footprint_estimate",
        "reliability_note": FOOTPRINT_ESTIMATE_RELIABILITY_NOTE,
        "footprint_polygon": [(round(float(x), 6), round(float(y), 6)) for x, y in footprint_polygon],
    }


def estimate_facade_bearing(
    lat: float,
    lon: float,
    *,
    ms_data_source: str | None = None,
    ms_query_fn: Callable[[float, float, str], Sequence[Coord] | None] | None = None,
    osm_query_fn: Callable[[float, float, float], Sequence[Coord] | None] | None = None,
    osm_radius_m: float = 50.0,
) -> dict[str, Any]:
    """Look up a footprint for ``(lat, lon)`` and estimate its facade bearing.

    Returns a ``"not_found"`` result (no guessed bearing, no fabricated
    footprint) if neither the primary nor fallback data source has a usable
    footprint for this coordinate.
    """
    footprint = lookup_footprint(
        lat,
        lon,
        ms_data_source=ms_data_source,
        ms_query_fn=ms_query_fn,
        osm_query_fn=osm_query_fn,
        osm_radius_m=osm_radius_m,
    )
    if not footprint:
        return {
            "facade_bearing_deg": None,
            "north_offset_deg": None,
            "source": "not_found",
            "reliability_note": NOT_FOUND_RELIABILITY_NOTE,
            "footprint_polygon": None,
        }

    return estimate_facade_bearing_from_footprint(footprint)


# ---------------------------------------------------------------------------
# 3. Manual override path
# ---------------------------------------------------------------------------

def manual_facade_bearing(
    facade_bearing_deg: float,
    footprint_polygon: Sequence[Coord] | None = None,
) -> dict[str, Any]:
    """Wrap a human-provided facade bearing in the standard output shape.

    Has no dependency on the footprint-lookup path. ``footprint_polygon``
    is optional context (e.g. what the human rotated the plan onto) and is
    passed through unchanged if supplied.
    """
    bearing = float(facade_bearing_deg) % 360.0
    return {
        "facade_bearing_deg": round(bearing, 6),
        "north_offset_deg": round(bearing, 6),
        "source": "manual",
        "reliability_note": MANUAL_RELIABILITY_NOTE,
        "footprint_polygon": (
            [(round(float(x), 6), round(float(y), 6)) for x, y in footprint_polygon]
            if footprint_polygon is not None
            else None
        ),
    }
