"""Bridges solver.py's constructive furniture-placement output into a
per-room suggestion list a caller (the UI, or anything else) can attach
alongside an audit_layout() result.

This module invents NO new placement logic of its own. It only:
  - maps each room name to the right solver.solve_* function, for the small,
    deliberately narrow set of room types solver.py supports at all
    (MasterBedroom/GuestBedroom/ChildrenBedroom, Kitchen, LivingRoom — see
    solver.py's module docstring for why the list stops there);
  - supplies documented DEFAULT furniture footprints when the caller doesn't
    pass its own (see DEFAULT_FURNITURE_DIMENSIONS — these are placeholders,
    not validated against any real furniture catalog or architect review);
  - turns solver.py's ValueError ("this furniture item does not physically
    fit in this room") into a structured, non-crashing "suggestion_error"
    entry instead of letting it propagate, since a caller's request for an
    audit should never fail just because one room happens to be too small
    for the default bed size.

A room only gets a suggestion if the caller supplies its polygon (a
suggestion is inherently geometric — there is no way to place a bed against
a wall without knowing the room's shape). Rooms without a polygon, or whose
type has no solver at all, are silently skipped — this is not an error
condition, most rooms in a layout simply won't have a placement solver.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import solver

Coord = tuple[float, float]

#: ASSUMPTION: placeholder furniture footprints (width, depth) in feet.
#: NOT validated against any real furniture catalog or architect review —
#: a caller can override per-room via the `furniture_dimensions` argument.
DEFAULT_FURNITURE_DIMENSIONS: dict[str, tuple[float, float]] = {
    "MasterBedroom": (6.0, 6.5),    # queen bed
    "GuestBedroom": (6.0, 6.5),     # queen bed
    "ChildrenBedroom": (4.0, 6.5),  # twin bed
    "Kitchen": (2.0, 2.0),          # stove footprint
}

#: Room types with a bed solver (solver.solve_bed_placement).
_BED_ROOMS = {"MasterBedroom", "GuestBedroom", "ChildrenBedroom"}


def suggest_for_room(
    room_name: str,
    polygon: Sequence[Coord],
    facade_bearing_deg: float = 0.0,
    furniture_dimensions: Mapping[str, tuple[float, float]] | None = None,
) -> dict[str, Any] | None:
    """Return a suggestion record for one room, or None if this room type
    has no solver at all (not an error — see module docstring).

    Return shape on success: {"room": ..., "placements": [...]} — the exact
    list solver.py's solve_* functions return, unmodified.
    Return shape on a real solver failure (furniture doesn't physically
    fit): {"room": ..., "suggestion_error": "<message>"}.
    """
    overrides = furniture_dimensions or {}

    try:
        if room_name in _BED_ROOMS:
            dims = overrides.get(room_name) or DEFAULT_FURNITURE_DIMENSIONS.get(room_name)
            if dims is None:
                return {"room": room_name, "suggestion_error": "no bed dimensions available"}
            placements = solver.solve_bed_placement(polygon, tuple(dims), room_name, facade_bearing_deg)
        elif room_name == "Kitchen":
            dims = overrides.get(room_name) or DEFAULT_FURNITURE_DIMENSIONS.get(room_name)
            if dims is None:
                return {"room": room_name, "suggestion_error": "no stove dimensions available"}
            placements = solver.solve_stove_placement(polygon, tuple(dims), facade_bearing_deg)
        elif room_name == "LivingRoom":
            placements = solver.solve_living_room_layout(polygon, facade_bearing_deg)
        else:
            return None  # out of solver.py's scope; not an error
    except ValueError as exc:
        return {"room": room_name, "suggestion_error": str(exc)}

    return {"room": room_name, "placements": placements}


def suggest_for_layout(
    rooms: Sequence[Mapping[str, Any]],
    facade_bearing_deg: float = 0.0,
    furniture_dimensions: Mapping[str, tuple[float, float]] | None = None,
) -> list[dict[str, Any]]:
    """Suggestion records for every room in `rooms` that has BOTH a polygon
    and a supported type.

    rooms: the same per-room dicts passed into vastu_audit.audit_layout
    (each needs at least "name"), PLUS an optional "polygon" key. Rooms
    without a "polygon" are silently skipped (a geometric suggestion needs
    geometry) — this lets callers pass the exact same room list used for
    the zone/adjacency audit, with polygons attached only where available.
    """
    results = []
    for room in rooms:
        polygon = room.get("polygon")
        if not polygon:
            continue
        suggestion = suggest_for_room(
            room.get("name"), polygon, facade_bearing_deg, furniture_dimensions
        )
        if suggestion is not None:
            results.append(suggestion)
    return results
