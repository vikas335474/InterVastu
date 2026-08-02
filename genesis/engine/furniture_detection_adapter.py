"""OPTIONAL input adapter: ML furniture-detection output -> an "existing
placement" verdict, in the same satisfies_rule/note vocabulary
:mod:`solver` uses for its own NEWLY RECOMMENDED placements.

=========================================================================
READ THIS BEFORE WIRING THIS IN — this module is deliberately NOT called
by solver.py, and solver.py's solve_* functions are unaffected by it.
=========================================================================

What this is
-------------
A translation/checking layer that takes raw object-detection output — the
shape a detector like `anngrrr/planparser <https://github.com/anngrrr/
planparser>`_ produces: a list of ``{"class": ..., "bbox": [...],
"confidence": ...}`` records — and asks, for the small set of furniture
types :mod:`solver` already has an established directional interpretation
for (bed, stove, heavy/sofa furniture), "is THIS ALREADY-PRESENT item
(per the detector) flush against a wall that satisfies the schema's
preferred direction, per the exact same wall-quadrant convention
:func:`solver.solve_bed_placement`/:func:`solver.solve_stove_placement`
use to PLACE a new one?"

This answers a different question than :mod:`solver` does. ``solver.py``'s
``solve_*`` functions search a room for where a NEW item SHOULD go.
This module never searches or recommends a placement — it only scores
an ALREADY-DETECTED item's position against the same rule. The two are
meant to be read side by side (e.g. "the detector found an existing bed
against the north wall; the solver's own recommended placement would put
it on the south wall instead"), not merged into one code path.

Why it is OPT-IN, decoupled, and confidence-gated
--------------------------------------------------
Unlike a geometric solve (deterministic, exact) or a human-confirmed
value (:mod:`orientation`'s manual override), an ML detection is a
probabilistic guess about what is actually in a photographed/scanned
plan. Every accepted result here carries its source detector's confidence
score and an explicit reliability note, mirroring the pattern
:mod:`orientation` already uses for its footprint-derived bearing
estimate:

  * nothing here runs unless a caller explicitly imports and calls it —
    :mod:`solver` never imports this module, and this module never calls
    any ``solve_*`` function;
  * detections below ``min_confidence`` are dropped, but always recorded
    (never silently discarded) in the result's ``skipped`` breakdown;
  * every accepted check carries ``"source": "ml_detection"``, and the
    result as a whole carries :data:`ML_DETECTION_RELIABILITY_NOTE`.

Input contract — read before wiring up a real detector
---------------------------------------------------------
Detection bounding boxes MUST already be in the room's own local-feet
coordinate frame, the same frame ``room_polygon`` is given in (matching
every other module in this package: :mod:`zone_geometry`, :mod:`solver`).

Converting a raw detector's PIXEL-space bounding boxes (e.g. planparser's
native output, which is in image pixels) into that frame requires a
scale/homography calibration this module does NOT attempt — the same
category of explicit non-goal as :mod:`orientation`'s footprint-lookup
functions not hardcoding a tile-hosting setup. That calibration step is
the caller's responsibility (or a separate, later task).

Scope — deliberately narrow, matching solver.py's own SCOPE
--------------------------------------------------------------
Only three furniture types get a directional verdict, because these are
the only ones :mod:`solver` (or, for the LivingRoom, ``vastu_audit``'s
schema-derived rule) already establishes a wall-flush -> compass-direction
interpretation for:

  1. Bed        (planparser classes ``bed``, ``bed2``)     -> MasterBedroom /
                                                                GuestBedroom /
                                                                ChildrenBedroom
                                                                (:data:`solver.BED_HEAD_DIRECTION_RULES`)
  2. Stove       (planparser class ``stove``)                -> Kitchen
                                                                (``vastu_audit.OBJECT_PLACEMENT_RULES["Kitchen"]``)
  3. Heavy/sofa  (planparser classes ``sofa1``/``sofa2``/``sofa3``) -> LivingRoom
                                                                (``vastu_audit.OBJECT_PLACEMENT_RULES["LivingRoom"]``)

Every other planparser class (``toilet``, ``chair``, ``table``, ``sink``,
``door``, ``door2``, ``shower``, ``bathtub``, ``vanity``) is deliberately
given NO directional interpretation here. In particular, ``toilet`` is
excluded even though ``vastu_audit.OBJECT_PLACEMENT_RULES["Toilet"]``
exists: that rule is about which way the SEATED PERSON faces, which is
the OPPOSITE convention from bed/stove (a toilet's seat faces AWAY from
the wall it backs onto, not toward it) and is a genuinely different,
un-established interpretation this module does not attempt to invent —
adding it would be exactly the kind of unscoped guess this project's
other modules explicitly avoid making without a documented basis. A
future task could add it deliberately, with its own documented
interpretation note (the same way ``solver.py`` documents each of its
own).

This module also does NOT check the MasterBedroom NE-corner-avoidance
sub-rule ``solve_bed_placement`` additionally enforces — that check needs
a precise room-local bed footprint, not just an approximate detection
bounding box, and is a reasonable, separately-scoped extension rather
than something to approximate here.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from solver import BED_HEAD_DIRECTION_RULES, nearest_wall
from vastu_audit import OBJECT_PLACEMENT_RULES

Coord = tuple[float, float]

#: Attached to every result returned by :func:`check_detected_furniture`.
#: Kept explicit, mirroring orientation.py's reliability-note pattern, so no
#: caller can treat an ML detection's verdict as equivalent to a geometric
#: solve or a human-confirmed value without seeing this note travel with it.
ML_DETECTION_RELIABILITY_NOTE: str = (
    "Furniture positions/classes in this result come from an automated "
    "object detector, not a geometric solve or human confirmation. Each "
    "accepted check carries the detector's own confidence score; treat "
    "low-confidence or borderline results as needing human review before "
    "acting on them, the same way orientation.py's footprint-estimate "
    "path does."
)

#: Detections with confidence below this are dropped (recorded in
#: ``skipped.low_confidence``, never silently discarded). PRODUCT THRESHOLD,
#: not derived from any detector's own precision/recall curve — a caller
#: with a specific detector (e.g. planparser's published mAP50 numbers)
#: should tune this to that detector, not rely on this default blindly.
DEFAULT_MIN_CONFIDENCE: float = 0.5

#: A detected item's bounding-box centroid must be within this many feet of
#: a room wall to be treated as "flush against" that wall; beyond this, no
#: direction can be inferred (a freestanding / mid-room item) and the
#: detection is recorded in ``skipped.not_wall_flush``. Deliberately the
#: same order of magnitude as solver.py's own CORNER_EXCLUSION_MARGIN_FT,
#: for the same reason: real furniture is rarely placed flush to the exact
#: millimetre, and detection bounding boxes add their own imprecision.
DEFAULT_WALL_FLUSH_MARGIN_FT: float = 2.0

#: planparser class label -> the furniture type this module knows how to
#: check directionally. See the module docstring's Scope section for
#: exactly why every other planparser class is deliberately absent.
DETECTION_CLASS_TO_FURNITURE_TYPE: dict[str, str] = {
    "bed": "bed",
    "bed2": "bed",
    "stove": "stove",
    "sofa1": "heavy_furniture",
    "sofa2": "heavy_furniture",
    "sofa3": "heavy_furniture",
}

#: furniture type -> {room_name: (preferred, forbidden)}. Sourced directly
#: from solver.py / vastu_audit.py's existing rule tables -- this module
#: does not define its own preferred/forbidden directions anywhere.
_FURNITURE_TYPE_ROOM_RULES: dict[str, dict[str, tuple[list[str], list[str]]]] = {
    "bed": {
        room: (rule["preferred"], rule["forbidden"])
        for room, rule in BED_HEAD_DIRECTION_RULES.items()
    },
    "stove": {
        "Kitchen": (
            OBJECT_PLACEMENT_RULES["Kitchen"]["stove_facing_direction"]["preferred"],
            OBJECT_PLACEMENT_RULES["Kitchen"]["stove_facing_direction"]["forbidden"],
        ),
    },
    "heavy_furniture": {
        "LivingRoom": (
            OBJECT_PLACEMENT_RULES["LivingRoom"]["heavy_furniture_wall"]["preferred"],
            OBJECT_PLACEMENT_RULES["LivingRoom"]["heavy_furniture_wall"]["forbidden"],
        ),
    },
}


def _bbox_centroid(bbox: Sequence[float]) -> Coord:
    minx, miny, maxx, maxy = bbox
    return ((minx + maxx) / 2.0, (miny + maxy) / 2.0)


def _check_one_detection(
    detection: Mapping[str, Any],
    furniture_type: str,
    room_name: str,
    room_polygon: Sequence[Coord],
    facade_bearing: float,
    wall_flush_margin_ft: float,
) -> tuple[dict[str, Any] | None, str | None]:
    """Returns ``(check_dict, skip_reason)`` -- exactly one is non-None."""
    preferred, forbidden = _FURNITURE_TYPE_ROOM_RULES[furniture_type][room_name]

    bbox = detection.get("bbox")
    if bbox is None or len(bbox) != 4:
        return None, "malformed"

    centroid = _bbox_centroid(bbox)
    nearest = nearest_wall(room_polygon, centroid, facade_bearing)
    if nearest["distance_ft"] > wall_flush_margin_ft:
        return None, "not_wall_flush"

    quadrant = nearest["wall"]["quadrant"]
    satisfies_rule = quadrant in preferred
    note = None
    if not satisfies_rule:
        if quadrant in forbidden:
            note = (
                f"Detected {furniture_type} faces a forbidden direction "
                f"({quadrant}); schema forbids {sorted(forbidden)} for this "
                f"room/field."
            )
        else:
            note = (
                f"Detected {furniture_type} faces {quadrant}, which is not "
                f"the schema's preferred direction ({sorted(preferred)}) but "
                f"is also not forbidden."
            )

    check = {
        "room": room_name,
        "object": furniture_type,
        "matched_class": detection.get("class"),
        "detection_confidence": detection.get("confidence", 1.0),
        "position": [round(centroid[0], 4), round(centroid[1], 4)],
        "facing_quadrant": quadrant,
        "distance_to_wall_ft": round(nearest["distance_ft"], 4),
        "satisfies_rule": satisfies_rule,
        "note": note,
        "source": "ml_detection",
    }
    return check, None


def check_detected_furniture(
    room_name: str,
    room_polygon: Sequence[Coord],
    detections: Sequence[Mapping[str, Any]],
    facade_bearing: float = 0.0,
    *,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    wall_flush_margin_ft: float = DEFAULT_WALL_FLUSH_MARGIN_FT,
) -> dict[str, Any]:
    """Check ML-detected furniture in ``room_name`` against the same
    preferred/forbidden directions :mod:`solver` uses for a new placement.

    Parameters
    ----------
    room_name
        One of the rooms this module has a rule for: ``"MasterBedroom"``,
        ``"GuestBedroom"``, ``"ChildrenBedroom"`` (bed), ``"Kitchen"``
        (stove), or ``"LivingRoom"`` (sofa/heavy furniture). A detection
        for any other room is not an error here (this function's caller
        already knows the room name); it simply means no detection can be
        in-scope, since ``_FURNITURE_TYPE_ROOM_RULES`` has no entry for it
        for any furniture type -- every detection ends up in
        ``skipped.unsupported_room``.
    room_polygon
        The room's boundary, in the same local-feet frame as ``detections``'
        bounding boxes (see module docstring's Input Contract).
    detections
        Sequence of ``{"class": str, "bbox": [minx, miny, maxx, maxy],
        "confidence": float}`` mappings (``"confidence"`` optional, default
        1.0), in the shape a planparser-class object detector produces.
    facade_bearing
        True compass bearing of the plan's own +y axis -- same convention
        as :func:`zone_geometry.analyze_zones`/:func:`solver.solve_bed_placement`.
    min_confidence, wall_flush_margin_ft
        See :data:`DEFAULT_MIN_CONFIDENCE` / :data:`DEFAULT_WALL_FLUSH_MARGIN_FT`.

    Returns
    -------
    dict
        ``{"room": room_name, "checks": [<per-accepted-detection dict>, ...],
        "skipped": {"low_confidence": [...], "unsupported_class": [...],
        "unsupported_room": [...], "not_wall_flush": [...],
        "malformed": [...]}, "reliability_note": ML_DETECTION_RELIABILITY_NOTE}``.
        Every input detection ends up in exactly one of ``checks`` or one
        ``skipped`` bucket -- nothing is silently dropped.
    """
    checks: list[dict[str, Any]] = []
    skipped: dict[str, list[Any]] = {
        "low_confidence": [],
        "unsupported_class": [],
        "unsupported_room": [],
        "not_wall_flush": [],
        "malformed": [],
    }

    for detection in detections:
        cls = detection.get("class")
        confidence = detection.get("confidence", 1.0)

        if confidence < min_confidence:
            skipped["low_confidence"].append(detection)
            continue

        furniture_type = DETECTION_CLASS_TO_FURNITURE_TYPE.get(cls)
        if furniture_type is None:
            skipped["unsupported_class"].append(detection)
            continue

        if room_name not in _FURNITURE_TYPE_ROOM_RULES.get(furniture_type, {}):
            skipped["unsupported_room"].append(detection)
            continue

        check, skip_reason = _check_one_detection(
            detection, furniture_type, room_name, room_polygon,
            facade_bearing, wall_flush_margin_ft,
        )
        if check is not None:
            checks.append(check)
        else:
            skipped[skip_reason].append(detection)

    return {
        "room": room_name,
        "checks": checks,
        "skipped": skipped,
        "reliability_note": ML_DETECTION_RELIABILITY_NOTE,
    }
