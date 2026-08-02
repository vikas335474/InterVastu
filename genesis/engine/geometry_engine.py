"""Reusable vector-math primitives for high-resolution Vastu grid analysis.

This module adds two things :mod:`zone_geometry` does not already provide:

1. A general 2D rotation primitive (:func:`rotate_point`,
   :func:`rotate_polygon`) for rotating vertex coordinates about an
   arbitrary origin. :mod:`zone_geometry` already corrects for
   ``north_offset_deg`` today, but it does so by rotating the *bearing
   measurement* (see ``zone_geometry.bearing_deg``), not the geometry
   itself — sufficient for "which sector is this room in", but not for
   overlaying a true-north-aligned square grid on the plan, which needs the
   vertices themselves rotated into a true-north frame first.
2. A classical square Vastu Purusha Mandala grid overlay
   (:func:`pada_grid`), aligned to true north via (1), giving per-cell
   ("pada") occupancy fractions for the boundary and each room at a
   caller-selectable resolution.

Scope note — why this is NOT the "32-Pada perimeter" some AI-generated
Vastu specs describe
--------------------------------------------------------------------------
A construct describing "32 equal angular segments radiating outward from
the centroid" does not correspond to any classical Vastu Purusha Mandala
this project could source. The classical padas are a SQUARE grid
subdivision of the plot — commonly 8x8 (64 pada, "Manduka") or 9x9 (81
pada, "Paramasayika", the most widely cited residential grid), scaling up
to 32x32 (1024 pada) in the sastra texts for very large sites — not a
radial/angular slicing. :mod:`zone_geometry` already owns angular/sector
logic (the 16-sector scheme in ``analyze_zones``); this module deliberately
does not duplicate or reinvent that with a differently-shaped, non-
traditional "angular pada" construct. :func:`pada_grid` below implements
the actual classical square-grid mandala instead, at a selectable order.

Scope note — devata/deity mapping
--------------------------------------------------------------------------
This module computes geometric pada occupancy ONLY. It assigns no deity,
name, or interpretation to any cell. Per-pada deity mapping (the "45
devata" set: 32 peripheral + 13 core, per some traditions) was already
explicitly scoped OUT of this codebase pending dedicated consultant
sourcing — see the "Scope" section of ``ritual_protocol.py``'s module
docstring. Nothing here revisits that decision; :func:`pada_grid`'s output
is shaped so a future, consultant-sourced deity map could be attached per
cell later without a reshape, but no such map is invented here.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

from shapely.geometry import box

from zone_geometry import Coord, _to_polygon, compute_centre

# ---------------------------------------------------------------------------
# Rotation
# ---------------------------------------------------------------------------


def rotate_point(point: Coord, angle_deg: float, origin: Coord = (0.0, 0.0)) -> Coord:
    """Rotate ``point`` by ``angle_deg`` counter-clockwise about ``origin``.

    Standard 2D affine rotation in an ``x`` right / ``y`` up plane::

        x' = Cx + (x - Cx) * cos(theta) - (y - Cy) * sin(theta)
        y' = Cy + (x - Cx) * sin(theta) + (y - Cy) * cos(theta)

    This is a general-purpose primitive with no compass/bearing semantics
    of its own — positive ``angle_deg`` is a standard mathematical
    counter-clockwise turn. See :func:`align_to_true_north` for the
    compass-aware wrapper that gets the sign right for this codebase's
    "clockwise from north" bearing convention (verified against
    ``zone_geometry.bearing_deg`` in the test suite, not just asserted).
    """
    cx, cy = origin
    x, y = point
    theta = math.radians(angle_deg)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    dx, dy = x - cx, y - cy
    return (
        cx + dx * cos_t - dy * sin_t,
        cy + dx * sin_t + dy * cos_t,
    )


def rotate_polygon(
    vertices: Sequence[Coord], angle_deg: float, origin: Coord = (0.0, 0.0)
) -> list[Coord]:
    """Rotate every vertex in ``vertices`` by ``angle_deg`` about ``origin``.

    See :func:`rotate_point` for the convention. ``origin`` is a plain
    ``(x, y)`` pair, not inferred from ``vertices`` — pass the flat's
    Brahmasthan centre (:func:`zone_geometry.compute_centre`) explicitly to
    rotate about the plot's true centroid.
    """
    return [rotate_point(v, angle_deg, origin) for v in vertices]


def align_to_true_north(
    vertices: Sequence[Coord], north_offset_deg: float, origin: Coord
) -> list[Coord]:
    """Rotate ``vertices`` so that true north maps onto the world ``+y`` axis.

    ``north_offset_deg`` is the true compass bearing (0 = N, clockwise) of
    the plan's own ``+y`` direction, in exactly
    ``zone_geometry.analyze_zones``'s convention. After this rotation, a
    bearing computed on the rotated points with ``north_offset_deg=0`` is
    numerically identical to the bearing computed on the original points
    with the original ``north_offset_deg`` — this equivalence is asserted
    directly in the test suite, not just derived by hand, because compass
    "clockwise from north" and standard math "counter-clockwise from +x"
    conventions are easy to get backwards.
    """
    return rotate_polygon(vertices, -north_offset_deg, origin)


# ---------------------------------------------------------------------------
# Classical square pada grid
# ---------------------------------------------------------------------------

#: Named classical grid orders this module knows about. Any positive integer
#: order works; these are just the two most commonly cited in residential
#: Vastu literature, exposed for readability at call sites.
MANDUKA_ORDER = 8  #: 8x8 = 64 pada ("Manduka" mandala).
PARAMASAYIKA_ORDER = 9  #: 9x9 = 81 pada ("Paramasayika" mandala) — the default.


def pada_grid(
    boundary: Sequence[Coord],
    rooms: Sequence[tuple[str, Sequence[Coord]]],
    north_offset_deg: float,
    order: int = PARAMASAYIKA_ORDER,
) -> dict[str, Any]:
    """Overlay a classical ``order`` x ``order`` square pada grid on a flat.

    The boundary and rooms are first rotated into a true-north-aligned
    frame (see :func:`align_to_true_north`), then the *rotated* boundary's
    axis-aligned bounding box is subdivided into ``order`` x ``order`` equal
    square cells ("pada"). For each cell this returns the fraction of the
    cell's area occupied by the boundary (the built footprint) and by each
    room, using exact polygon intersection — not a point-sample.

    Cells are indexed ``(row, col)`` with ``row`` 0 at the south edge of the
    bounding box increasing northward, and ``col`` 0 at the west edge
    increasing eastward, both in the true-north-aligned frame. This module
    assigns no classical pada *name* (e.g. specific deity, "Aryaman",
    "Pusha", ...) to any cell — see the module docstring's devata scope
    note.

    Parameters
    ----------
    boundary
        The flat's boundary polygon, in the same local ``(x, y)`` feet
        frame as :func:`zone_geometry.analyze_zones`.
    rooms
        ``(name, polygon)`` pairs, same frame as ``boundary``.
    north_offset_deg
        True compass bearing of the plan's own ``+y``, same convention as
        :mod:`zone_geometry`.
    order
        Grid resolution (cells per side). Must be >= 1. Defaults to the 9x9
        Paramasayika mandala (81 pada). Pass :data:`MANDUKA_ORDER` for the
        8x8 (64 pada) alternative some traditions use instead.

    Returns
    -------
    dict
        ``{
            "order": int,
            "north_offset_deg": float,
            "bounding_box": {"min_x", "min_y", "max_x", "max_y"},  # true-north frame
            "cell_size_ft": float,
            "cells": [
                {
                    "row": int, "col": int,
                    "bounds": {"min_x", "min_y", "max_x", "max_y"},
                    "boundary_occupancy_fraction": float,  # 0..1
                    "room_occupancy": {room_name: fraction, ...},  # 0..1 each
                }, ...
            ],
        }``
        ``cells`` always has exactly ``order * order`` entries, in
        row-major order, even for cells entirely outside the (possibly
        irregular) footprint — their ``boundary_occupancy_fraction`` is
        simply ``0.0``.
    """
    if order < 1:
        raise ValueError(f"order must be >= 1, got {order!r}")

    north_offset_deg = north_offset_deg % 360.0
    centre = compute_centre(boundary)

    rotated_boundary = align_to_true_north(boundary, north_offset_deg, centre)
    boundary_poly = _to_polygon(rotated_boundary, label="boundary")

    rotated_rooms = [
        (name, _to_polygon(align_to_true_north(polygon, north_offset_deg, centre), label=f"room {name!r}"))
        for name, polygon in rooms
    ]

    minx, miny, maxx, maxy = boundary_poly.bounds
    width, height = maxx - minx, maxy - miny
    cell_w, cell_h = width / order, height / order

    cells: list[dict[str, Any]] = []
    for row in range(order):
        cy0 = miny + row * cell_h
        cy1 = cy0 + cell_h
        for col in range(order):
            cx0 = minx + col * cell_w
            cx1 = cx0 + cell_w
            cell_box = box(cx0, cy0, cx1, cy1)
            cell_area = cell_box.area

            boundary_fraction = 0.0
            if cell_area > 0.0:
                boundary_fraction = boundary_poly.intersection(cell_box).area / cell_area

            room_occupancy: dict[str, float] = {}
            if cell_area > 0.0:
                for name, room_poly in rotated_rooms:
                    inter = room_poly.intersection(cell_box).area
                    if inter > 0.0:
                        room_occupancy[name] = round(inter / cell_area, 6)

            cells.append({
                "row": row,
                "col": col,
                "bounds": {
                    "min_x": round(cx0, 6), "min_y": round(cy0, 6),
                    "max_x": round(cx1, 6), "max_y": round(cy1, 6),
                },
                "boundary_occupancy_fraction": round(boundary_fraction, 6),
                "room_occupancy": room_occupancy,
            })

    return {
        "order": order,
        "north_offset_deg": round(north_offset_deg, 6),
        "bounding_box": {
            "min_x": round(minx, 6), "min_y": round(miny, 6),
            "max_x": round(maxx, 6), "max_y": round(maxy, 6),
        },
        "cell_size_ft": {"width": round(cell_w, 6), "height": round(cell_h, 6)},
        "cells": cells,
    }
