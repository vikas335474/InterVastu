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
from shapely.geometry import Point, Polygon, box

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

#: The 8 coarse compass octants, used only by the shape-diagnosis layer
#: (:func:`diagnose_shape`) to label a *cut/missing region* by direction. The
#: 16-sector :data:`SECTORS` scheme stays the authority for room-to-centre
#: bearings; a physical corner that has been chamfered/notched off a footprint
#: maps naturally onto one of 8 directions (the "head/arms/feet" of the Vastu
#: Purusha), which is also the granularity the traditional missing-zone
#: remedies are written at.
OCTANTS: tuple[str, ...] = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")

#: Dual-centre diagnostic threshold. The distance between the true area
#: centroid and the bounding-box centre, normalised by the bounding-box
#: diagonal, at or above which a flat is flagged ``high_center_offset`` (a
#: strongly off-centre mass distribution, typical of pronounced L-/T-shapes).
#: This is a PRODUCT THRESHOLD, not a settled Vastu constant — a plain
#: rectangle scores ~0 and this value simply separates those from strongly
#: irregular footprints. Exposed as a parameter so it can be tuned without a
#: code change. Calibration note: because the offset is normalised by the
#: bounding-box diagonal, realistic L-shapes land in a fairly narrow band —
#: a mild L ~0.04, a square with one quadrant removed ~0.08, a thin-armed
#: deep L ~0.14 — so this default sits mid-band to fire on pronounced-but-real
#: irregularity while ignoring near-rectangular plans. NOTE: this is
#: deliberately independent of the hollow-centre test below; a footprint can
#: have a small offset yet still place its centroid outside itself (a U-shape
#: does exactly this), so both are checked.
DEFAULT_CENTER_OFFSET_FRACTION_THRESHOLD: float = 0.08

#: A cut region (bounding box minus the actual footprint) smaller than this
#: fraction of the bounding-box area is treated as tracing/measurement noise
#: and not reported as a missing zone. PRODUCT THRESHOLD, not a Vastu constant:
#: the Unit 12 fixture itself documents +/-2-3 ft tracing tolerance, which is
#: exactly the kind of sliver this is meant to filter out.
DEFAULT_MISSING_ZONE_AREA_FRACTION_THRESHOLD: float = 0.03


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


def octant_name(true_bearing_deg: float) -> str:
    """Coarse 8-way compass octant (e.g. ``"NE"``) for a true compass bearing.

    N is centred on 0, so octant ``i`` spans ``[i*45 - 22.5, i*45 + 22.5)``.
    Used only by :func:`diagnose_shape` to label cut/missing regions — see
    :data:`OCTANTS` for why the finer 16-sector scheme is not used there.
    """
    b = true_bearing_deg % 360.0
    return OCTANTS[int(math.floor((b + 22.5) / 45.0)) % len(OCTANTS)]


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


# ---------------------------------------------------------------------------
# Shape diagnosis — dual-centre check + cut/missing-zone detection
# ---------------------------------------------------------------------------
#
# This layer answers a different question from analyze_zones(): not "where is
# each room" but "is the FOOTPRINT ITSELF structurally defective" — the two
# classic irregular-plan defects that a bounding box hides:
#
#   1. Hollow / external centre. For a U-shaped (or otherwise strongly
#      concave) flat the true area centroid — the Brahmasthan — can fall in
#      empty space *outside the footprint entirely*. Traditionally this is
#      one of the most serious plan defects (the sacred centre is missing),
#      and it is invisible to any bounding-box centre, which always sits
#      inside the box. This is checked directly with a point-in-polygon test,
#      independently of the offset magnitude: a footprint can have a *small*
#      centroid<->bbox-centre offset and still place its centroid outside
#      itself, so offset size alone would miss it.
#
#   2. Cut / missing zones. A rectangle minus the actual footprint is the set
#      of "cut corners" — the regions a full rectangular plot would occupy
#      but this flat does not. Each such region is labelled by the compass
#      octant it sits in, which is exactly how the traditional
#      "missing NE / missing SW / ..." remedies are indexed.
#
# It is deterministic and geometric only; it assigns no severities and encodes
# no remedies (that belongs to the rule/audit layer, vastu_audit.py). The two
# thresholds it uses are documented PRODUCT choices, not Vastu constants —
# see their constant definitions above.


def diagnose_shape(
    boundary: Sequence[Coord],
    north_offset_deg: float = 0.0,
    *,
    center_offset_fraction_threshold: float = DEFAULT_CENTER_OFFSET_FRACTION_THRESHOLD,
    missing_zone_area_fraction_threshold: float = DEFAULT_MISSING_ZONE_AREA_FRACTION_THRESHOLD,
) -> dict[str, Any]:
    """Diagnose footprint-level shape defects for a flat boundary polygon.

    Parameters
    ----------
    boundary
        The flat's overall boundary polygon as ``(x, y)`` vertices in feet.
    north_offset_deg
        True compass bearing (0..360, N=0, clockwise) of the plan's own
        ``+y`` direction — same convention as :func:`analyze_zones`. Used only
        to label cut/missing regions by compass octant.
    center_offset_fraction_threshold
        See :data:`DEFAULT_CENTER_OFFSET_FRACTION_THRESHOLD`.
    missing_zone_area_fraction_threshold
        See :data:`DEFAULT_MISSING_ZONE_AREA_FRACTION_THRESHOLD`.

    Returns
    -------
    dict
        ``{
            "centroid": {"x", "y"},                 # true area centroid (Brahmasthan)
            "bbox_center": {"x", "y"},              # axis-aligned bounding-box centre
            "bounding_box": {"min_x", "min_y", "max_x", "max_y"},
            "center_offset_ft": float,             # distance centroid<->bbox_center
            "center_offset_fraction": float,       # offset / bbox diagonal
            "high_center_offset": bool,            # offset_fraction >= threshold
            "centroid_inside_boundary": bool,
            "hollow_center": bool,                 # centroid falls OUTSIDE the footprint
            "footprint_fill_fraction": float,      # footprint area / bbox area
            "missing_zones": [                      # one entry per octant with a real cut
                {"octant", "zones", "area_ft2", "area_fraction"}, ...
            ],
            "params": {...},
        }``

    Notes
    -----
    ``high_center_offset`` and ``hollow_center`` are deliberately separate
    flags for the same reason the module docstring gives: they catch different
    defects and neither implies the other.
    """
    north_offset_deg = north_offset_deg % 360.0
    poly = _to_polygon(boundary, label="boundary")

    centroid = poly.centroid
    cx, cy = centroid.x, centroid.y

    minx, miny, maxx, maxy = poly.bounds
    bbox_cx, bbox_cy = (minx + maxx) / 2.0, (miny + maxy) / 2.0
    width, height = (maxx - minx), (maxy - miny)
    diagonal = math.hypot(width, height)
    bbox_area = width * height

    offset = math.hypot(cx - bbox_cx, cy - bbox_cy)
    offset_fraction = (offset / diagonal) if diagonal > 0.0 else 0.0

    # Point-in-polygon: distance is exactly 0.0 for a point inside or on the
    # boundary, > 0 only for a point strictly outside. A tiny tolerance guards
    # against floating-point noise on the boundary case.
    centroid_inside = bool(poly.distance(centroid) < 1e-9)

    # --- Cut / missing zones: bounding box minus the actual footprint -------
    missing_by_octant: dict[str, dict[str, Any]] = {}
    if bbox_area > 0.0:
        diff = box(minx, miny, maxx, maxy).difference(poly)
        pieces = list(getattr(diff, "geoms", [diff])) if not diff.is_empty else []
        for piece in pieces:
            if piece.is_empty or piece.area <= 0.0:
                continue
            area_fraction = piece.area / bbox_area
            if area_fraction < missing_zone_area_fraction_threshold:
                continue  # tracing/measurement sliver, not a real cut
            pc = piece.centroid
            # A cut region can only fail to have a bearing if it is centred
            # exactly on the flat centroid, which is geometrically impossible
            # for a region that is disjoint from the footprint; guard anyway.
            if pc.x == cx and pc.y == cy:
                continue
            bearing = bearing_deg((cx, cy), (pc.x, pc.y), north_offset_deg)
            octant = octant_name(bearing)
            zone = sector_name(bearing)
            entry = missing_by_octant.setdefault(
                octant, {"octant": octant, "zones": set(), "area_ft2": 0.0}
            )
            entry["area_ft2"] += float(piece.area)
            entry["zones"].add(zone)

    missing_zones = []
    for octant in OCTANTS:  # stable, compass-ordered output
        entry = missing_by_octant.get(octant)
        if entry is None:
            continue
        missing_zones.append({
            "octant": entry["octant"],
            "zones": sorted(entry["zones"]),
            "area_ft2": round(entry["area_ft2"], 6),
            "area_fraction": round(entry["area_ft2"] / bbox_area, 6),
        })

    return {
        "centroid": {"x": round(float(cx), 6), "y": round(float(cy), 6)},
        "bbox_center": {"x": round(float(bbox_cx), 6), "y": round(float(bbox_cy), 6)},
        "bounding_box": {
            "min_x": round(float(minx), 6), "min_y": round(float(miny), 6),
            "max_x": round(float(maxx), 6), "max_y": round(float(maxy), 6),
        },
        "center_offset_ft": round(float(offset), 6),
        "center_offset_fraction": round(float(offset_fraction), 6),
        "high_center_offset": bool(offset_fraction >= center_offset_fraction_threshold),
        "centroid_inside_boundary": centroid_inside,
        "hollow_center": (not centroid_inside),
        "footprint_fill_fraction": round(float(poly.area / bbox_area), 6) if bbox_area > 0.0 else None,
        "missing_zones": missing_zones,
        "params": {
            "north_offset_deg": round(float(north_offset_deg), 6),
            "center_offset_fraction_threshold": float(center_offset_fraction_threshold),
            "missing_zone_area_fraction_threshold": float(missing_zone_area_fraction_threshold),
        },
    }
