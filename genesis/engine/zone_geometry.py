"""Deterministic zone-assignment layer for a Vastu compliance engine.

This module turns a flat's floor-plan geometry into a structured, per-room
Vastu zone assignment. It is intentionally *deterministic and geometric*: it
performs no orientation/bearing detection of its own (the facade bearing is a
required input) and encodes no Vastu rules — it only answers "which of the 16
directional zones does this room sit in, relative to the flat's true
geometric centre (Brahmasthan), and does any room sit on top of that centre".

Responsibilities
----------------
1. Brahmasthan   : the flat's geometric centre is the centroid of the boundary
                   polygon's *occupied area* (Shapely polygon centroid), NOT
                   the bounding-box centre. For an L-shaped / stepped flat the
                   two differ significantly, and that difference decides whether
                   a central room is truly a Brahmasthan violation.
2. Zone assignment : the 360 degrees are split into 16 sectors of 22.5 deg each
                   (N centred on 0/360). Each room is placed in the sector that
                   contains the bearing from the Brahmasthan to the room's own
                   centroid.
3. Boundary uncertainty : if a room's bearing sits within
                   ``LOW_CONFIDENCE_MARGIN_DEG`` of a sector edge, its zone is
                   flagged ``"low"`` confidence, because small measurement
                   uncertainty could flip the zone (and therefore a violation).
4. Brahmasthan containment : a proper point-in-polygon test (Shapely
                   ``.contains()``) decides whether the exact Brahmasthan point
                   falls inside a room. A room occupying the "central" area
                   without containing the exact point is NOT a containment
                   violation; a near-miss (point just outside a wall) is
                   surfaced separately for human review.

Coordinate & bearing conventions
---------------------------------
* Room and boundary polygons are lists of ``(x, y)`` vertices in **feet**, in
  the plan's own local frame (``+x`` = plan-right, ``+y`` = plan-up).
* Compass bearings use the surveyor convention: **0 deg = North**, increasing
  **clockwise** (90 = East, 180 = South, 270 = West).
* ``facade_bearing`` is the true compass bearing that the plan's ``+y`` axis
  points toward. It rotates the local plan frame onto true north so the zone
  labels (N, NE, ...) are real compass directions. If plan-up already points
  north, pass ``facade_bearing = 0``.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping, Sequence

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

#: A room whose bearing sits closer than this (deg) to a sector edge is flagged
#: low confidence. A real test case saw a 12-deg measurement uncertainty flip a
#: violation, so the flag is deliberately generous.
LOW_CONFIDENCE_MARGIN_DEG: float = 5.0

#: Distance (feet) under which a non-containing room is reported as a
#: Brahmasthan near-miss for human review.
NEAR_MISS_FT: float = 2.0


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


def compute_brahmasthan(boundary: Sequence[Coord]) -> Coord:
    """Return the flat's Brahmasthan as the area centroid of ``boundary``.

    This is the Shapely polygon centroid (the centre of mass of the occupied
    area), NOT the bounding-box centre. For non-rectangular flats the two
    differ, and only this value is Vastu-correct.
    """
    poly = _to_polygon(boundary, label="boundary")
    c = poly.centroid
    return (c.x, c.y)


def local_bearing_deg(origin: Coord, target: Coord) -> float:
    """Bearing (deg, clockwise from plan ``+y``) from ``origin`` to ``target``.

    Returns a value in ``[0, 360)``. Measured in the plan's local frame; add
    the facade bearing to obtain a true compass bearing.
    """
    dx = target[0] - origin[0]
    dy = target[1] - origin[1]
    if dx == 0.0 and dy == 0.0:
        raise ValueError("origin and target coincide; bearing is undefined")
    # atan2(dx, dy) measures clockwise from +y (North-up), matching the
    # surveyor convention where North is 0 and East (+x) is 90.
    return math.degrees(math.atan2(dx, dy)) % 360.0


def sector_index(bearing_deg: float) -> int:
    """Index into :data:`SECTORS` for a true compass ``bearing_deg``.

    N is centred on 0, so sector ``i`` spans ``[i*22.5 - 11.25, i*22.5 + 11.25)``.
    The lower edge is inclusive.
    """
    b = bearing_deg % 360.0
    return int(math.floor((b + SECTOR_HALF_WIDTH_DEG) / SECTOR_WIDTH_DEG)) % len(SECTORS)


def sector_name(bearing_deg: float) -> str:
    """Compass sector label (e.g. ``"NE"``) for a true compass bearing."""
    return SECTORS[sector_index(bearing_deg)]


def _angular_offset_from_center(bearing_deg: float, center_deg: float) -> float:
    """Smallest absolute angular gap (deg, 0..180) between two bearings."""
    diff = (bearing_deg - center_deg + 180.0) % 360.0 - 180.0
    return abs(diff)


def boundary_margin_deg(bearing_deg: float) -> float:
    """Degrees from ``bearing_deg`` to the nearest sector edge (0..11.25).

    A margin of 0 means the bearing sits exactly on an edge (maximally
    uncertain); a margin of 11.25 means it sits dead-centre in its sector.
    """
    idx = sector_index(bearing_deg)
    center = idx * SECTOR_WIDTH_DEG
    offset = _angular_offset_from_center(bearing_deg, center)
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
            # Sequence form: (name, polygon)
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
    brahmasthan: Coord,
    facade_bearing: float,
) -> dict[str, Any]:
    """Compute the zone + Brahmasthan record for a single room."""
    room_poly = _to_polygon(polygon, label=f"room {name!r}")
    centroid = room_poly.centroid
    brahma_pt = Point(brahmasthan)

    # --- Zone assignment (rotate local bearing onto true compass) ----------
    local = local_bearing_deg(brahmasthan, (centroid.x, centroid.y))
    true_bearing = (local + facade_bearing) % 360.0
    zone = sector_name(true_bearing)
    margin = boundary_margin_deg(true_bearing)
    confidence = "low" if margin < LOW_CONFIDENCE_MARGIN_DEG else "high"

    # --- Brahmasthan containment (exact point-in-polygon) ------------------
    contains = bool(room_poly.contains(brahma_pt))
    distance_ft: float | None = None
    if not contains:
        wall_dist = brahma_pt.distance(room_poly.boundary)
        if wall_dist < NEAR_MISS_FT:
            distance_ft = float(wall_dist)

    return {
        "room": name,
        "zone": zone,
        "zone_confidence": confidence,
        "boundary_margin_deg": round(float(margin), 6),
        "bearing_deg": round(float(true_bearing), 6),
        "contains_brahmasthan": contains,
        "brahmasthan_distance_ft": (
            round(distance_ft, 6) if distance_ft is not None else None
        ),
    }


def analyze_zones(
    boundary: Sequence[Coord],
    rooms: Iterable[Mapping[str, Any] | Sequence[Any]],
    facade_bearing: float,
) -> dict[str, Any]:
    """Assign every room to a directional zone relative to the Brahmasthan.

    Parameters
    ----------
    boundary
        The flat's overall boundary polygon as ``(x, y)`` vertices in feet.
        May be non-rectangular (L-shaped, stepped, ...).
    rooms
        Iterable of rooms. Each room is either a mapping with ``name``/``id``
        and ``polygon``/``vertices`` keys, or a ``(name, polygon)`` pair.
    facade_bearing
        True compass bearing (0..360, N=0, clockwise) that the plan's ``+y``
        axis points toward. Provided as input; not computed here.

    Returns
    -------
    dict
        ``{"brahmasthan": {"x", "y"}, "facade_bearing": float,
        "rooms": [<per-room record>, ...]}``.
    """
    if not (0.0 <= facade_bearing < 360.0):
        facade_bearing = facade_bearing % 360.0

    bx, by = compute_brahmasthan(boundary)
    records = [
        analyze_room(name, polygon, (bx, by), facade_bearing)
        for name, polygon in _normalise_rooms(rooms)
    ]

    return {
        "brahmasthan": {"x": round(float(bx), 6), "y": round(float(by), 6)},
        "facade_bearing": round(float(facade_bearing), 6),
        "rooms": records,
    }
