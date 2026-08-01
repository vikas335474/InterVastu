"""Deterministic zone-geometry layer for a Vastu compliance engine (Phase 1b).

This module turns a flat's floor-plan geometry into a structured, per-room
Vastu zone assignment. It is intentionally *deterministic and geometric*: it
performs no orientation/bearing detection of its own (``north_offset_deg`` is
a required input, produced by a separate module later) and encodes no Vastu
rules — it only answers "which of the 16 directional zones does this room
sit in, relative to the flat's true geometric centre (Brahmasthan)" and
"does any room sit on, or overlap, that centre".

Responsibilities
-----------------
1. Brahmasthan centre : the flat's geometric centre is the Shapely centroid
                   of the boundary polygon's *occupied area*, NOT the
                   bounding-box centre. For an L-shaped / stepped flat the two
                   differ significantly, and that difference decides whether
                   a central room is truly a Brahmasthan violation.
2. Brahmasthan region : the Brahmasthan is traditionally the central ~1/9 of
                   the plot (the 3x3 core of a 9x9 pada grid), not a single
                   point. This module computes that region as the boundary
                   polygon scaled down about its centroid, with the area
                   fraction exposed as a parameter (default 1/9). See
                   ``brahmasthan_region`` below for the caveat on this value.
3. Zone assignment : the 360 degrees are split into 16 sectors of 22.5 deg
                   each (N centred on 0/360). Each room is placed in the
                   sector that contains the compass bearing from the centre
                   to the room's own centroid.
4. Boundary uncertainty : if a room's bearing sits within
                   ``LOW_CONFIDENCE_MARGIN_DEG`` of a sector edge, its zone is
                   flagged ``"low"`` confidence, because small measurement
                   uncertainty could flip the zone (and therefore a
                   violation). A real test case saw a 12 deg measurement
                   error flip a major violation.
5. Brahmasthan checks : two separate, both-reported tests per room —
                   (a) does the room polygon *contain* the exact centroid
                   point (a strict point-in-polygon test), and
                   (b) does the room polygon *overlap* the central-1/9
                   region, and if so what fraction of the region does it
                   cover. These answer different questions: a room can sit
                   over part of the central zone without ever containing the
                   single centroid point, and that still matters
                   traditionally. A near-miss (neither, but within 2 ft of
                   the region) is surfaced separately for human review
                   rather than silently cleared.

Coordinate & bearing conventions
---------------------------------
* Boundary and room polygons are lists of ``(x, y)`` vertices in **feet**, in
  the plan's own local frame (``+x`` = plan-right, ``+y`` = plan-up).
* Compass bearings use the surveyor convention: **0 deg = North**, increasing
  **clockwise** (90 = East, 180 = South, 270 = West).
* ``north_offset_deg`` is the true compass bearing (0 = N, clockwise) of the
  plan's own straight-up (``+y``) direction. A room's compass bearing from
  the centre is::

      bearing = (north_offset_deg + degrees(atan2(dx, dy))) % 360

  where ``dx = room_cx - centre_x`` and ``dy = room_cy - centre_y``. This
  makes plan-up equal true north when ``north_offset_deg == 0``, and rotates
  correctly for any other facade orientation.

Explicitly out of scope
------------------------
Orientation / facade-bearing *detection* (i.e. producing ``north_offset_deg``
from a raw floor plan) is a separate, later module. This module only
consumes that value.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping, Sequence

from shapely.affinity import scale as shapely_scale
from shapely.geometry import Point, Polygon

Coord = tuple[float, float]

# ---------------------------------------------------------------------------
# Directional-sector constants
# ---------------------------------------------------------------------------

#: The 16 compass sectors in clockwise order, starting with N centred on 0 deg.
SECTORS: tuple[str, ...] = (
    "N", "NNE", "NE", "ENE",
    "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW",
    "W", "WNW", "NW", "NNW",
)

#: Angular width of each sector (360 / 16).
SECTOR_WIDTH_DEG: float = 360.0 / len(SECTORS)  # 22.5

#: Half-width of a sector; a sector spans centre +/- this to its two edges.
SECTOR_HALF_WIDTH_DEG: float = SECTOR_WIDTH_DEG / 2.0  # 11.25

#: A room whose bearing sits closer than this (deg) to a sector edge is
#: flagged low confidence. A real test case saw a 12 deg measurement
#: uncertainty flip a major violation, so this margin is deliberately
#: generous rather than tight.
LOW_CONFIDENCE_MARGIN_DEG: float = 5.0

#: Distance (feet) under which a room that neither contains the centroid nor
#: overlaps the Brahmasthan region is still reported as a near-miss for
#: human review, rather than silently cleared.
NEAR_MISS_FT: float = 2.0

#: Default fraction of the plot's area treated as the Brahmasthan region (the
#: central 3x3 core of a 9x9 pada grid == 1/9 of the plot). NOTE: whether 1/9
#: (the 3x3 core) or the stricter 1/81 (the single central pada) is the
#: "correct" reading is a live disagreement among Vastu consultants — this
#: default is a product choice, not a settled fact, and is exposed as a
#: parameter precisely so it can be revisited without a code change.
DEFAULT_BRAHMASTHAN_AREA_FRACTION: float = 1.0 / 9.0


# ---------------------------------------------------------------------------
# Low-level geometry / bearing helpers
# ---------------------------------------------------------------------------

def _to_polygon(vertices: Sequence[Coord], *, label: str) -> Polygon:
    """Build a valid Shapely polygon from a vertex list, or raise ValueError."""
    poly = Polygon(vertices)
    if poly.is_empty or poly.area == 0.0:
        raise ValueError(f"{label} polygon is degenerate (zero area): {vertices!r}")
    if not poly.is_valid:
        # A self-intersecting polygon has an undefined centroid; repair it.
        poly = poly.buffer(0)
        if poly.is_empty or poly.area == 0.0:
            raise ValueError(f"{label} polygon is invalid and could not be repaired")
    return poly


def compute_centre(boundary: Sequence[Coord]) -> Coord:
    """Return the flat's Brahmasthan centre as the area centroid of ``boundary``.

    This is the Shapely polygon centroid (the centre of mass of the occupied
    area), NOT the bounding-box centre. For non-rectangular flats (L-shaped,
    stepped, ...) the two differ, and only this value is Vastu-correct.
    """
    poly = _to_polygon(boundary, label="boundary")
    c = poly.centroid
    return (c.x, c.y)


def compute_brahmasthan_region(
    boundary: Sequence[Coord],
    centre: Coord,
    area_fraction: float = DEFAULT_BRAHMASTHAN_AREA_FRACTION,
) -> Polygon:
    """Return the central Brahmasthan region as a scaled-down boundary polygon.

    The region is the boundary polygon scaled about ``centre`` by the linear
    factor ``sqrt(area_fraction)`` (so its area is ``area_fraction`` times the
    boundary's area), using Shapely affine scaling. Scaling (rather than, say,
    an inscribed rectangle) is used so the region's shape still reflects the
    plot's own shape for non-rectangular boundaries.
    """
    if not (0.0 < area_fraction <= 1.0):
        raise ValueError(f"area_fraction must be in (0, 1], got {area_fraction!r}")
    poly = _to_polygon(boundary, label="boundary")
    linear_factor = math.sqrt(area_fraction)
    region = shapely_scale(poly, xfact=linear_factor, yfact=linear_factor, origin=centre)
    if region.is_empty or region.area == 0.0:
        raise ValueError("Brahmasthan region collapsed to zero area; check boundary/area_fraction")
    return region


def local_bearing_deg(origin: Coord, target: Coord) -> float:
    """Plan-local bearing (deg, clockwise from plan ``+y``) from ``origin`` to ``target``.

    Returns a value in ``[0, 360)``, measured in the plan's own local frame
    (before any ``north_offset_deg`` rotation is applied). Kept as a public
    helper: other modules (e.g. the furniture-placement solver) reuse this
    same convention for local direction vectors, not just room bearings.
    """
    dx = target[0] - origin[0]
    dy = target[1] - origin[1]
    if dx == 0.0 and dy == 0.0:
        raise ValueError("origin and target coincide; bearing is undefined")
    # atan2(dx, dy) measures clockwise from +y (North-up), matching the
    # surveyor convention where North is 0 and East (+x) is 90.
    return math.degrees(math.atan2(dx, dy)) % 360.0


def bearing_deg(centre: Coord, target: Coord, north_offset_deg: float) -> float:
    """True compass bearing (deg, 0=N, clockwise) from ``centre`` to ``target``.

    dx = target_x - centre_x, dy = target_y - centre_y;
    bearing = (north_offset_deg + degrees(atan2(dx, dy))) % 360.

    Combines :func:`local_bearing_deg` (the plan-local bearing) with
    ``north_offset_deg`` to rotate it onto true north.
    """
    local = local_bearing_deg(centre, target)
    return (north_offset_deg + local) % 360.0


def sector_index(true_bearing_deg: float) -> int:
    """Index into :data:`SECTORS` for a true compass bearing.

    N is centred on 0, so sector ``i`` spans ``[i*22.5 - 11.25, i*22.5 + 11.25)``.
    The lower edge is inclusive.
    """
    b = true_bearing_deg % 360.0
    return int(math.floor((b + SECTOR_HALF_WIDTH_DEG) / SECTOR_WIDTH_DEG)) % len(SECTORS)


def sector_name(true_bearing_deg: float) -> str:
    """Compass sector label (e.g. ``"NE"``) for a true compass bearing."""
    return SECTORS[sector_index(true_bearing_deg)]


def _angular_offset_from_center(bearing: float, center_deg: float) -> float:
    """Smallest absolute angular gap (deg, 0..180) between two bearings."""
    diff = (bearing - center_deg + 180.0) % 360.0 - 180.0
    return abs(diff)


def boundary_margin_deg(true_bearing_deg: float) -> float:
    """Degrees from ``true_bearing_deg`` to the nearest sector edge (0..11.25).

    A margin of 0 means the bearing sits exactly on an edge (maximally
    uncertain); a margin of 11.25 means it sits dead-centre in its sector.
    """
    idx = sector_index(true_bearing_deg)
    center = idx * SECTOR_WIDTH_DEG
    offset = _angular_offset_from_center(true_bearing_deg, center)
    margin = SECTOR_HALF_WIDTH_DEG - offset
    # Guard against tiny negative values from floating-point noise.
    return max(0.0, margin)


# ---------------------------------------------------------------------------
# Room input normalisation
# ---------------------------------------------------------------------------

def _normalise_rooms(
    rooms: Iterable[Mapping[str, Any] | Sequence[Any]],
) -> list[tuple[str, Sequence[Coord]]]:
    """Coerce assorted room inputs into ``(name, polygon)`` pairs.

    Accepts either mappings with ``name``/``id`` and ``polygon``/``vertices``
    keys, or ``(name, polygon)`` tuples/lists.
    """
    normalised: list[tuple[str, Sequence[Coord]]] = []
    for i, room in enumerate(rooms):
        if isinstance(room, Mapping):
            name = room.get("name") or room.get("id")
            polygon = room.get("polygon") or room.get("vertices")
        else:
            try:
                name, polygon = room
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"room #{i} is not a (name, polygon) pair: {room!r}"
                ) from exc
        if name is None:
            name = f"room_{i}"
        if polygon is None:
            raise ValueError(f"room {name!r} is missing its polygon")
        normalised.append((str(name), polygon))
    return normalised


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_room(
    name: str,
    polygon: Sequence[Coord],
    centre: Coord,
    region: Polygon,
    north_offset_deg: float,
) -> dict[str, Any]:
    """Compute the zone + Brahmasthan record for a single room."""
    room_poly = _to_polygon(polygon, label=f"room {name!r}")
    centroid = room_poly.centroid
    centre_pt = Point(centre)

    # --- Zone assignment ----------------------------------------------------
    # A room whose own centroid coincides exactly with the plot centre has no
    # well-defined bearing (this is the Brahmasthan room itself); report the
    # zone fields as None rather than raising or guessing a direction.
    if centroid.x == centre[0] and centroid.y == centre[1]:
        true_bearing = None
        zone = None
        margin = None
        confidence = None
    else:
        true_bearing = bearing_deg(centre, (centroid.x, centroid.y), north_offset_deg)
        zone = sector_name(true_bearing)
        margin = boundary_margin_deg(true_bearing)
        confidence = "low" if margin < LOW_CONFIDENCE_MARGIN_DEG else "high"

    # --- Brahmasthan checks: point containment vs. region overlap ----------
    contains_centre_point = bool(room_poly.contains(centre_pt))

    intersection = room_poly.intersection(region)
    overlaps_region = not intersection.is_empty and intersection.area > 0.0
    region_overlap_fraction = (intersection.area / region.area) if overlaps_region else 0.0

    nearest_distance_ft: float | None = None
    if not contains_centre_point and not overlaps_region:
        dist = room_poly.distance(region)
        if dist < NEAR_MISS_FT:
            nearest_distance_ft = float(dist)

    return {
        "room": name,
        "zone": zone,
        "zone_confidence": confidence,
        "boundary_margin_deg": round(float(margin), 6) if margin is not None else None,
        "bearing_deg": round(float(true_bearing), 6) if true_bearing is not None else None,
        "contains_centre_point": contains_centre_point,
        "overlaps_brahmasthan_region": overlaps_region,
        "region_overlap_fraction": round(float(region_overlap_fraction), 6),
        "nearest_distance_ft": (
            round(nearest_distance_ft, 6) if nearest_distance_ft is not None else None
        ),
    }


def analyze_zones(
    boundary: Sequence[Coord],
    rooms: Iterable[Mapping[str, Any] | Sequence[Any]],
    north_offset_deg: float,
    brahmasthan_area_fraction: float = DEFAULT_BRAHMASTHAN_AREA_FRACTION,
) -> dict[str, Any]:
    """Assign every room to a directional zone and Brahmasthan status.

    Parameters
    ----------
    boundary
        The flat's overall boundary polygon as ``(x, y)`` vertices in feet.
        May be non-rectangular (L-shaped, stepped, ...).
    rooms
        Iterable of rooms. Each room is either a mapping with ``name``/``id``
        and ``polygon``/``vertices`` keys, or a ``(name, polygon)`` pair.
    north_offset_deg
        True compass bearing (0..360, N=0, clockwise) of the plan's own
        straight-up (``+y``) direction. See module docstring for the bearing
        formula this drives.
    brahmasthan_area_fraction
        Fraction of the boundary's area treated as the central Brahmasthan
        region (default 1/9, the 3x3 core of a 9x9 pada grid). See
        :data:`DEFAULT_BRAHMASTHAN_AREA_FRACTION` for the caveat on this
        value.

    Returns
    -------
    dict
        ``{"centre": {"x", "y"}, "brahmasthan_region": [(x, y), ...],
        "params": {"north_offset_deg", "brahmasthan_area_fraction"},
        "rooms": [<per-room record>, ...]}``.
    """
    north_offset_deg = north_offset_deg % 360.0

    cx, cy = compute_centre(boundary)
    region = compute_brahmasthan_region(boundary, (cx, cy), brahmasthan_area_fraction)

    records = [
        analyze_room(name, polygon, (cx, cy), region, north_offset_deg)
        for name, polygon in _normalise_rooms(rooms)
    ]

    region_vertices = [(round(float(x), 6), round(float(y), 6)) for x, y in region.exterior.coords]

    return {
        "centre": {"x": round(float(cx), 6), "y": round(float(cy), 6)},
        "brahmasthan_region": region_vertices,
        "params": {
            "north_offset_deg": round(float(north_offset_deg), 6),
            "brahmasthan_area_fraction": float(brahmasthan_area_fraction),
        },
        "rooms": records,
    }
