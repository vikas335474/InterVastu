"""Phase 1c — constraint-based furniture placement solver.

Takes audited room geometry (a room polygon, in the same room-local-feet
coordinate system as :mod:`zone_geometry`) and the object-placement rules
from :mod:`vastu_audit`'s ``OBJECT_PLACEMENT_RULES``, and outputs SPECIFIC
coordinates + rotation for a small, fixed set of furniture items so a later
3D scene builder can render a layout that is provably (not just
decoratively) Vastu-compliant.

SCOPE — deliberately narrow, do not extend without a separate task:
    1. Bed placement       — MasterBedroom, GuestBedroom, ChildrenBedroom.
    2. Stove placement     — Kitchen.
    3. Heavy-furniture wall — LivingRoom (wall *recommendation* only, no
                              furniture footprint/solver for this one).

This module does NOT do general room layout, does NOT render anything, and
does NOT solve for any room type beyond the four above.

-------------------------------------------------------------------------
INTERPRETATION NOTES (read before trusting output as "consultant-approved")
-------------------------------------------------------------------------
Everything below is this module's own geometric interpretation of already-
provisional rules (``vastu_audit.OBJECT_PLACEMENT_RULES``, itself flagged
as pending consultant sign-off). Three interpretation calls in particular
are NOT in the schema and must go on the same sign-off list:

1. "Head direction" / "cook-facing direction" == the compass bearing of
   the OUTWARD normal of the wall the headboard/stove is flush against.
   Reasoning: if the headboard is against (say) the south wall, the
   sleeper's head is at the south end of the bed — i.e. points south.
   Symmetrically, a cook standing in front of a stove against a wall
   faces toward that wall.
2. GuestBedroom and ChildrenBedroom have no ``sleeping_direction`` text in
   the schema (only MasterBedroom does). This module applies the SAME
   general "head South or East, avoid North" preference to all three
   bedroom types, since that is the well-known general form of the rule
   and the schema gives no reason to think it's master-bedroom-specific —
   but this generalisation was made here, not in the schema.
3. Wall-facing direction is classified into just 4 quadrants (N/E/S/W,
   90-deg bins centred on each cardinal), not the 16-sector scheme
   zone_geometry uses for room-to-Brahmasthan bearings. A physical wall
   in ordinary architecture faces one of 4 primary directions; the finer
   16-way scheme is for room-to-centre bearings, not wall orientation.
4. The MasterBedroom-only schema note ("avoid placing the bed directly in
   the NE corner even within an NE-zoned room") is applied here as a pure
   geometry check against the room's OWN NE corner — this module does not
   know the room's assigned Vastu zone (that's a separate concern of
   zone_geometry + the flat's Brahmasthan), so it applies the corner
   avoidance unconditionally for MasterBedroom rather than only when the
   room happens to be NE-zoned. This is a deliberately conservative
   reading, not a schema requirement. GuestBedroom/ChildrenBedroom have no
   such note in the schema, so no corner exclusion is applied to them.

-------------------------------------------------------------------------
"NEVER SILENTLY FAIL OR SILENTLY VIOLATE"
-------------------------------------------------------------------------
Every solver here always returns a placement if the furniture item
physically fits somewhere in the room (checked via Shapely containment).
If no wall lets the item satisfy its preferred direction, the least-bad
geometrically valid placement is returned with ``"compromise": True`` and
a plain-language ``"compromise_note"``. Only a genuine physical
impossibility (the item does not fit against any wall at all) raises a
``ValueError`` — that is a real failure, not a Vastu compromise, and must
not be silently coerced into a placement.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

from shapely.geometry import LineString, Point, Polygon

import zone_geometry as zg
from vastu_audit import OBJECT_PLACEMENT_RULES

Coord = tuple[float, float]

# ---------------------------------------------------------------------------
# Rule wiring — reuse vastu_audit.OBJECT_PLACEMENT_RULES as the single
# source of truth for preferred/forbidden directions; do not duplicate it.
# ---------------------------------------------------------------------------

_MASTER_BEDROOM_HEAD_RULE = OBJECT_PLACEMENT_RULES["MasterBedroom"]["bed_head_direction"]
_KITCHEN_STOVE_RULE = OBJECT_PLACEMENT_RULES["Kitchen"]["stove_facing_direction"]
_LIVING_ROOM_FURNITURE_RULE = OBJECT_PLACEMENT_RULES["LivingRoom"]["heavy_furniture_wall"]

#: See INTERPRETATION NOTE 2 above: Guest/Children bedrooms inherit the same
#: preferred/forbidden head directions as MasterBedroom; only MasterBedroom
#: carries the NE-corner-avoidance note (INTERPRETATION NOTE 4).
BED_HEAD_DIRECTION_RULES: dict[str, dict[str, Any]] = {
    "MasterBedroom": {
        "preferred": list(_MASTER_BEDROOM_HEAD_RULE["preferred"]),
        "forbidden": list(_MASTER_BEDROOM_HEAD_RULE["forbidden"]),
        "avoid_corner": "NE",
    },
    "GuestBedroom": {
        "preferred": list(_MASTER_BEDROOM_HEAD_RULE["preferred"]),
        "forbidden": list(_MASTER_BEDROOM_HEAD_RULE["forbidden"]),
        "avoid_corner": None,
    },
    "ChildrenBedroom": {
        "preferred": list(_MASTER_BEDROOM_HEAD_RULE["preferred"]),
        "forbidden": list(_MASTER_BEDROOM_HEAD_RULE["forbidden"]),
        "avoid_corner": None,
    },
}

#: ASSUMPTION (not in schema): "directly in the corner" is read as within
#: this radius (feet) of the room's NE-most vertex. See INTERPRETATION NOTE 4.
CORNER_EXCLUSION_MARGIN_FT: float = 3.0


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _room_polygon(vertices: Sequence[Coord]) -> Polygon:
    poly = Polygon(vertices)
    if poly.is_empty or poly.area == 0.0:
        raise ValueError(f"room polygon is degenerate (zero area): {vertices!r}")
    if not poly.is_valid:
        poly = poly.buffer(0)
        if poly.is_empty or poly.area == 0.0:
            raise ValueError("room polygon is invalid and could not be repaired")
    return poly


def _wall_quadrant(bearing_deg: float) -> str:
    """Classify a true compass bearing into one of 4 wall-facing quadrants.

    See INTERPRETATION NOTE 3 in the module docstring for why this is a
    coarser 90-deg-bin scheme than zone_geometry's 16-sector one.
    """
    b = bearing_deg % 360.0
    if b >= 315.0 or b < 45.0:
        return "N"
    if b < 135.0:
        return "E"
    if b < 225.0:
        return "S"
    return "W"


def _true_bearing_of_vector(dx: float, dy: float, facade_bearing: float) -> float:
    """True compass bearing of a LOCAL direction vector (dx, dy).

    Reuses zone_geometry's bearing convention/helper (origin at (0,0), so
    the result is the local bearing of the vector itself), then rotates it
    onto true north via facade_bearing exactly as zone_geometry does for
    room centroids.
    """
    local = zg.local_bearing_deg((0.0, 0.0), (dx, dy))
    return (local + facade_bearing) % 360.0


def _polygon_walls(room_poly: Polygon, facade_bearing: float) -> list[dict[str, Any]]:
    """One entry per polygon edge: geometry + the compass direction it faces.

    "Faces" = the edge's outward normal direction (the compass direction
    you'd walk to leave the room through that wall).
    """
    coords = list(room_poly.exterior.coords)[:-1]
    centroid = room_poly.centroid
    n = len(coords)
    walls = []
    for i in range(n):
        p1, p2 = coords[i], coords[(i + 1) % n]
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        length = math.hypot(dx, dy)
        if length == 0.0:
            continue
        ux, uy = dx / length, dy / length

        # Two perpendicular candidates; pick whichever points away from the
        # room's centroid (works for convex/near-convex rooms, which covers
        # every fixture this module targets).
        n1 = (uy, -ux)
        n2 = (-uy, ux)
        mid = ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0)
        to_mid = (mid[0] - centroid.x, mid[1] - centroid.y)
        dot1 = n1[0] * to_mid[0] + n1[1] * to_mid[1]
        dot2 = n2[0] * to_mid[0] + n2[1] * to_mid[1]
        outward = n1 if dot1 >= dot2 else n2
        inward = (-outward[0], -outward[1])

        bearing = _true_bearing_of_vector(outward[0], outward[1], facade_bearing)
        walls.append({
            "p1": p1,
            "p2": p2,
            "length": length,
            "unit": (ux, uy),
            "outward_normal": outward,
            "inward_normal": inward,
            "bearing_deg": bearing,
            "quadrant": _wall_quadrant(bearing),
        })
    return walls


def nearest_wall(
    room_polygon: Sequence[Coord],
    point: Coord,
    facade_bearing: float = 0.0,
) -> dict[str, Any]:
    """Return the polygon wall nearest to `point`, and the distance to it.

    Public wrapper around the same wall/quadrant geometry
    :func:`solve_bed_placement` and :func:`solve_stove_placement` use
    internally (:func:`_polygon_walls`), exposed so other modules can answer
    "which wall is this point flush against, and which compass direction
    does that wall face" without duplicating the wall-finding logic. The
    furniture-detection adapter (:mod:`furniture_detection_adapter`) is the
    first such caller: it reuses this to turn a detected object's position
    into the same wall-flush direction convention this module's own
    INTERPRETATION NOTE 1 already establishes (headboard/stove flush
    against a wall -> the compass direction of that wall).

    Returns ``{"wall": <wall dict from _polygon_walls>, "distance_ft": float}``.
    The wall dict's ``"quadrant"`` (N/E/S/W) and ``"bearing_deg"`` are the
    fields callers typically want; the rest (``p1``/``p2``/``unit``/normals)
    support geometry a caller might also need.
    """
    room_poly = _room_polygon(room_polygon)
    walls = _polygon_walls(room_poly, facade_bearing)
    pt = Point(point)

    best_wall, best_dist = None, None
    for wall in walls:
        segment = LineString([wall["p1"], wall["p2"]])
        distance = segment.distance(pt)
        if best_dist is None or distance < best_dist:
            best_dist, best_wall = distance, wall

    return {"wall": best_wall, "distance_ft": float(best_dist)}


def _room_ne_corner(room_poly: Polygon, facade_bearing: float) -> Coord:
    """The room's own vertex whose true bearing from the room centroid is
    closest to 45 deg (NE) — used for the MasterBedroom corner-avoidance
    check (INTERPRETATION NOTE 4)."""
    centroid = room_poly.centroid
    coords = list(room_poly.exterior.coords)[:-1]
    best_vertex, best_diff = None, None
    for v in coords:
        bearing = _true_bearing_of_vector(v[0] - centroid.x, v[1] - centroid.y, facade_bearing)
        diff = abs(((bearing - 45.0 + 180.0) % 360.0) - 180.0)
        if best_diff is None or diff < best_diff:
            best_diff, best_vertex = diff, v
    return best_vertex


def _wall_flush_rectangle(wall: dict, offset: float, width: float, depth: float) -> list[Coord]:
    """4 corners of a `width` x `depth` rectangle flush against `wall`,
    starting `offset` ft from wall['p1'] along the wall, extending `depth`
    ft inward."""
    ux, uy = wall["unit"]
    inx, iny = wall["inward_normal"]
    p1 = wall["p1"]
    c1 = (p1[0] + offset * ux, p1[1] + offset * uy)
    c2 = (c1[0] + width * ux, c1[1] + width * uy)
    c3 = (c2[0] + depth * inx, c2[1] + depth * iny)
    c4 = (c1[0] + depth * inx, c1[1] + depth * iny)
    return [c1, c2, c3, c4]


def _candidate_offsets(wall_length: float, width: float) -> list[float]:
    """A small, deterministic set of anchor offsets to try along a wall:
    centered, flush to each end. Sufficient for rectangular/near-rectangular
    rooms; this is a constrained solver, not a general 1D bin-packer."""
    span = max(0.0, wall_length - width)
    raw = [span / 2.0, 0.0, span]
    seen: set[float] = set()
    offsets = []
    for o in raw:
        o = max(0.0, min(o, span))
        key = round(o, 6)
        if key not in seen:
            seen.add(key)
            offsets.append(o)
    return offsets


# ---------------------------------------------------------------------------
# 1. Bed placement — MasterBedroom, GuestBedroom, ChildrenBedroom
# ---------------------------------------------------------------------------

def solve_bed_placement(
    room_polygon: Sequence[Coord],
    bed_dimensions: tuple[float, float],
    room_name: str,
    facade_bearing: float = 0.0,
) -> list[dict[str, Any]]:
    """Find a wall-flush bed placement for `room_name` in `room_polygon`.

    bed_dimensions: (width, depth) in feet — width runs along the headboard
    wall, depth runs from headboard into the room (e.g. (6.0, 6.5) for a
    queen).

    Returns a single-item list (see module OUTPUT SHAPE) with keys:
    room, object="bed", position [x, y], rotation_deg, satisfies_rule,
    compromise, compromise_note.

    Raises ValueError if room_name is out of scope, or if the bed does not
    physically fit against any wall of the room at all (a real failure,
    not a Vastu compromise — see module docstring).
    """
    if room_name not in BED_HEAD_DIRECTION_RULES:
        raise ValueError(
            f"solve_bed_placement only supports {sorted(BED_HEAD_DIRECTION_RULES)}, "
            f"got {room_name!r}"
        )

    rule = BED_HEAD_DIRECTION_RULES[room_name]
    preferred, forbidden, avoid_corner = rule["preferred"], rule["forbidden"], rule["avoid_corner"]

    room_poly = _room_polygon(room_polygon)
    width, depth = bed_dimensions
    walls = _polygon_walls(room_poly, facade_bearing)
    room_poly_safe = room_poly.buffer(1e-6)  # tolerate flush-wall floating-point touch

    exclusion_zone = None
    corner_vertex = None
    if avoid_corner == "NE":
        corner_vertex = _room_ne_corner(room_poly, facade_bearing)
        exclusion_zone = Point(corner_vertex).buffer(CORNER_EXCLUSION_MARGIN_FT)

    candidates = []
    for wall in walls:
        if wall["length"] + 1e-9 < width:
            continue
        for offset in _candidate_offsets(wall["length"], width):
            corners = _wall_flush_rectangle(wall, offset, width, depth)
            bed_poly = Polygon(corners)
            if not room_poly_safe.contains(bed_poly):
                continue  # room isn't deep enough perpendicular to this wall

            corner_ok = exclusion_zone is None or not bed_poly.intersects(exclusion_zone)
            quadrant = wall["quadrant"]
            if quadrant in preferred:
                rule_rank = 2
            elif quadrant in forbidden:
                rule_rank = 0
            else:
                rule_rank = 1

            cx = sum(c[0] for c in corners) / 4.0
            cy = sum(c[1] for c in corners) / 4.0
            candidates.append({
                "score": (1 if corner_ok else 0, rule_rank),
                "position": (cx, cy),
                "bearing_deg": wall["bearing_deg"],
                "quadrant": quadrant,
                "corner_ok": corner_ok,
            })

    if not candidates:
        raise ValueError(
            f"No wall in this {room_name} polygon is long/deep enough to fit a "
            f"{width}x{depth} ft bed footprint — the bed does not physically fit."
        )

    candidates.sort(key=lambda c: c["score"], reverse=True)
    best = candidates[0]

    satisfies_rule = best["quadrant"] in preferred and best["corner_ok"]
    compromise = not satisfies_rule
    compromise_note = None
    if compromise:
        notes = []
        if best["quadrant"] not in preferred:
            if best["quadrant"] in forbidden:
                notes.append(
                    f"No available wall placement avoids a forbidden sleeping "
                    f"direction; the only geometrically valid option has the "
                    f"head pointing {best['quadrant']} (schema forbids "
                    f"{sorted(forbidden)} for this room)."
                )
            else:
                notes.append(
                    f"No wall faces the schema's preferred sleeping direction "
                    f"({sorted(preferred)}); the closest geometrically valid "
                    f"option has the head pointing {best['quadrant']}, which is "
                    f"not forbidden but also not preferred."
                )
        if not best["corner_ok"]:
            notes.append(
                f"This placement could not avoid the room's {avoid_corner} "
                f"corner (schema note: avoid placing the bed directly in that "
                f"corner, even within an NE-zoned room)."
            )
        compromise_note = " ".join(notes)

    return [{
        "room": room_name,
        "object": "bed",
        "position": [round(best["position"][0], 4), round(best["position"][1], 4)],
        "rotation_deg": round(best["bearing_deg"], 4),
        "satisfies_rule": satisfies_rule,
        "compromise": compromise,
        "compromise_note": compromise_note,
    }]


# ---------------------------------------------------------------------------
# 2. Stove placement — Kitchen
# ---------------------------------------------------------------------------

def solve_stove_placement(
    room_polygon: Sequence[Coord],
    stove_dimensions: tuple[float, float],
    facade_bearing: float = 0.0,
) -> list[dict[str, Any]]:
    """Find a wall-flush stove placement so the cook faces the schema's
    preferred direction (see vastu_audit.OBJECT_PLACEMENT_RULES["Kitchen"]
    ["stove_facing_direction"], currently preferred=["E"], no forbidden
    direction is documented).

    stove_dimensions: (width, depth) in feet, same convention as bed_dimensions.

    Returns a single-item list; raises ValueError if the stove footprint
    does not physically fit against any wall.
    """
    preferred = _KITCHEN_STOVE_RULE["preferred"]
    forbidden = _KITCHEN_STOVE_RULE.get("forbidden", [])

    room_poly = _room_polygon(room_polygon)
    width, depth = stove_dimensions
    walls = _polygon_walls(room_poly, facade_bearing)
    room_poly_safe = room_poly.buffer(1e-6)

    candidates = []
    for wall in walls:
        if wall["length"] + 1e-9 < width:
            continue
        for offset in _candidate_offsets(wall["length"], width):
            corners = _wall_flush_rectangle(wall, offset, width, depth)
            stove_poly = Polygon(corners)
            if not room_poly_safe.contains(stove_poly):
                continue

            quadrant = wall["quadrant"]
            if quadrant in preferred:
                rule_rank = 2
            elif quadrant in forbidden:
                rule_rank = 0
            else:
                rule_rank = 1

            cx = sum(c[0] for c in corners) / 4.0
            cy = sum(c[1] for c in corners) / 4.0
            candidates.append({
                "score": rule_rank,
                "position": (cx, cy),
                "bearing_deg": wall["bearing_deg"],
                "quadrant": quadrant,
            })

    if not candidates:
        raise ValueError(
            f"No wall in this Kitchen polygon is long/deep enough to fit a "
            f"{width}x{depth} ft stove footprint — the stove does not "
            f"physically fit."
        )

    candidates.sort(key=lambda c: c["score"], reverse=True)
    best = candidates[0]

    satisfies_rule = best["quadrant"] in preferred
    compromise = not satisfies_rule
    compromise_note = None
    if compromise:
        if best["quadrant"] in forbidden:
            compromise_note = (
                f"No available wall placement avoids a forbidden cook-facing "
                f"direction; the only geometrically valid option faces "
                f"{best['quadrant']} (schema forbids {sorted(forbidden)})."
            )
        else:
            compromise_note = (
                f"No wall faces the schema's preferred cook-facing direction "
                f"({sorted(preferred)}); the closest geometrically valid "
                f"option faces {best['quadrant']}, which is not forbidden but "
                f"also not preferred."
            )

    return [{
        "room": "Kitchen",
        "object": "stove",
        "position": [round(best["position"][0], 4), round(best["position"][1], 4)],
        "rotation_deg": round(best["bearing_deg"], 4),
        "satisfies_rule": satisfies_rule,
        "compromise": compromise,
        "compromise_note": compromise_note,
    }]


# ---------------------------------------------------------------------------
# 3. Heavy-furniture wall assignment — LivingRoom
# ---------------------------------------------------------------------------

def solve_living_room_layout(
    room_polygon: Sequence[Coord],
    facade_bearing: float = 0.0,
) -> list[dict[str, Any]]:
    """Identify which wall(s) of the LivingRoom face S/W (per the schema's
    layout_rule) and recommend them for heavy furniture.

    Per the module OUTPUT SHAPE, this returns only "heavy_furniture_zone"
    placement objects (one per recommended wall) — it does NOT emit a
    separate placement object per N/E wall. Any wall NOT in the returned
    list is implicitly the "keep open" set the schema's layout_rule refers
    to; this is documented here rather than encoded as extra output keys,
    to keep the output strictly within the shared placement-object shape.

    If NO wall in the room faces S/W at all (only possible for a
    non-rectangular or unusually rotated room), the nearest available
    wall(s) are returned instead with "compromise": True, so the room
    still gets a usable recommendation rather than an empty list.
    """
    preferred = _LIVING_ROOM_FURNITURE_RULE["preferred"]  # ["S", "W"]

    room_poly = _room_polygon(room_polygon)
    walls = _polygon_walls(room_poly, facade_bearing)

    preferred_walls = [w for w in walls if w["quadrant"] in preferred]
    use_walls = preferred_walls if preferred_walls else walls
    compromise = not preferred_walls

    placements = []
    for wall in use_walls:
        mid = ((wall["p1"][0] + wall["p2"][0]) / 2.0, (wall["p1"][1] + wall["p2"][1]) / 2.0)
        satisfies_rule = wall["quadrant"] in preferred
        note = None
        if compromise:
            note = (
                f"No wall in this room faces the schema's preferred S/W "
                f"heavy-furniture direction ({sorted(preferred)}); "
                f"recommending the nearest available wall (faces "
                f"{wall['quadrant']}) instead so the layout still has a "
                f"usable recommendation."
            )
        placements.append({
            "room": "LivingRoom",
            "object": "heavy_furniture_zone",
            "position": [round(mid[0], 4), round(mid[1], 4)],
            "rotation_deg": round(wall["bearing_deg"], 4),
            "satisfies_rule": satisfies_rule,
            "compromise": compromise,
            "compromise_note": note,
        })
    return placements
