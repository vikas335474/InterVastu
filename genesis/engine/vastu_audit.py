"""
Vastu Compliance Audit Engine — Phase 1 (Deterministic Logic Layer Only)
=========================================================================

Scope, per Genesis Blueprint Pillar 1 ("Vastu compliance is a deterministic
layer, not a generative one") and System_Architecture.md Section 4:

    - Consumes structured JSON (room name, zone, adjacency flags).
    - Checks each room against room_constraints in the rule schema.
    - Checks plot-level rules (brahmasthan, floor_slope, shape).
    - Emits per-room and per-plot violations with severity + remedy text.
    - Sums a compliance score.

Explicitly OUT of scope for this module (later phases per architecture doc):
    - Floor-plan ingestion / OCR / CV parsing
    - Rendering (deterministic layout or generative styling)
    - Frontend / Bubble.io
    - PDF report generation
    - Auth / RLS / Supabase persistence

-------------------------------------------------------------------------
IMPORTANT — DATA SOURCE NOTE (read before trusting output as "approved")
-------------------------------------------------------------------------
This module reads `vastu_rule_schema.json`, whose own `_meta.status` field
says:

    "Draft — expanded from 2-room stub. Requires sign-off from a licensed
    Vastu consultant before production use."

version: 0.2.0 (NOT v1.0, and NOT marked consultant-approved anywhere in
the file). This module makes no attempt to "upgrade" that claim — it just
loads whatever schema file it's pointed at and reports what that file says.
If a consultant-approved v1.0 schema is produced later, point this module
at that file; no code changes should be needed as long as the JSON shape
(zones, room_constraints, plot_level_rules) stays the same.

-------------------------------------------------------------------------
SCORING — THIS IS AN ASSUMPTION, NOT PART OF THE SCHEMA
-------------------------------------------------------------------------
The schema defines severity as categorical ("major"/"minor") with no
numeric weights, and plot_level_rules (shape, floor_slope, brahmasthan)
carry NO severity field at all. There is no scoring formula anywhere in
the source data. The point values and the "plot-level violations default
to major" rule below are placeholder defaults invented for this module so
a single number can be produced. They have NOT been validated by a Vastu
consultant and should be treated as provisional until someone with
domain + product authority signs off on an actual weighting scheme.
"""

import json
import sys
from pathlib import Path

# --- ASSUMPTION: severity -> point deduction. Not in schema. See docstring. ---
SEVERITY_POINTS = {
    "major": 10,
    "minor": 3,
    "unspecified": 5,  # fallback if a forbidden value has no entry in the schema's severity map
}

# --- ASSUMPTION: plot_level_rules have no severity field in the schema, so ---
# --- every plot-level violation is scored as "major" by default. See docstring. ---
PLOT_LEVEL_DEFAULT_SEVERITY = "major"

BASE_SCORE = 100


def load_schema(schema_path):
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


def audit_room(room, schema):
    """
    room: dict with keys:
        - name (str, required) — must match a key in schema['room_constraints']
        - zone (str, optional) — one of the 16 zone codes, or a special
          string like "center" for rooms where the schema puts non-compass
          flags directly in the 'forbidden' list (Toilet, Staircase)
        - adjacency_flags (list[str], optional) — e.g. "shares_wall_with_toilet",
          "under_staircase"

    Returns a list of violation dicts. Empty list = fully compliant.
    A room name not present in the schema returns a single warning dict
    (rule_type = "unknown_room_type") instead of a violation, since we have
    no rule to check it against — this is NOT scored as a compliance failure,
    it's flagged separately so it isn't silently ignored either.
    """
    name = room.get("name")
    constraints = schema.get("room_constraints", {}).get(name)

    if constraints is None:
        return [{
            "room": name,
            "rule_type": "unknown_room_type",
            "message": f"No rule defined for room type '{name}' in this schema version.",
            "severity": None,
        }]

    violations = []
    zone = room.get("zone")
    adjacency_flags = room.get("adjacency_flags", []) or []

    forbidden = constraints.get("forbidden", [])
    severity_map = constraints.get("severity", {})
    remedy_map = constraints.get("remedy", {})

    # Zone check. Some rooms (Toilet, Staircase) put "center" directly in
    # 'forbidden' alongside compass codes, so this same check also catches
    # that case as long as the caller passes zone="center" for a plot-center room.
    if zone and zone in forbidden:
        violations.append({
            "room": name,
            "rule_type": "zone",
            "violation": zone,
            "severity": severity_map.get(zone, "unspecified"),
            "remedy": remedy_map.get(zone, remedy_map.get("default", "No remedy documented in schema for this violation.")),
        })

    # Adjacency / compound-constraint checks (e.g. PoojaRoom + shares_wall_with_toilet,
    # under_staircase). Schema note explicitly flags these as needing a separate
    # adjacency-check pass distinct from the zone check.
    for flag in adjacency_flags:
        if flag in forbidden:
            violations.append({
                "room": name,
                "rule_type": "adjacency",
                "violation": flag,
                "severity": severity_map.get(flag, "unspecified"),
                "remedy": remedy_map.get(flag, remedy_map.get("default", "No remedy documented in schema for this violation.")),
            })

    return violations


def audit_plot_level(plot, schema):
    """
    plot: dict with keys:
        - shape (str) — e.g. "rectangle", "square", "triangular",
          "polygonal_irregular", "L_shaped_without_correction"
        - floor_slope (dict) — {"high_corner": "SW", "low_corner": "NE"}
        - brahmasthan_obstructed (bool)
        - brahmasthan_obstruction_type (str, optional) — free text, e.g.
          "toilet", "staircase", "load-bearing pillar"

    Returns a list of violation dicts, using PLOT_LEVEL_DEFAULT_SEVERITY
    since the schema does not define severity for these rules.
    """
    violations = []
    rules = schema.get("plot_level_rules", {})

    # --- Shape ---
    shape = plot.get("shape")
    shape_rule = rules.get("shape", {})
    if shape is not None and shape in shape_rule.get("forbidden", []):
        violations.append({
            "rule_type": "plot_shape",
            "violation": shape,
            "severity": PLOT_LEVEL_DEFAULT_SEVERITY,
            "remedy": "No remedy documented in schema; irregular plot shapes generally require structural correction (per schema notes), not a cosmetic fix.",
        })

    # --- Floor slope ---
    # Rule text: "Ground level should be higher in SW, sloping down towards NE."
    slope = plot.get("floor_slope", {}) or {}
    high_corner = slope.get("high_corner")
    low_corner = slope.get("low_corner")
    if high_corner is not None or low_corner is not None:
        if high_corner != "SW" or low_corner != "NE":
            violations.append({
                "rule_type": "floor_slope",
                "violation": f"high_corner={high_corner}, low_corner={low_corner} (schema expects high_corner=SW, low_corner=NE)",
                "severity": PLOT_LEVEL_DEFAULT_SEVERITY,
                "remedy": "No remedy documented in schema; slope correction is a structural/regrading fix.",
            })

    # --- Brahmasthan (plot center) ---
    if plot.get("brahmasthan_obstructed") is True:
        obstruction = plot.get("brahmasthan_obstruction_type", "unspecified structure")
        violations.append({
            "rule_type": "brahmasthan",
            "violation": f"plot center obstructed by: {obstruction}",
            "severity": PLOT_LEVEL_DEFAULT_SEVERITY,
            "remedy": "No remedy documented in schema; rule requires the geometric center be kept open, light, and free of heavy structure.",
        })

    return violations


# -------------------------------------------------------------------------
# BRAHMASTHAN-OBSTRUCTION CHECK — bridges the zone_geometry region-overlap
# output into scored/informational audit output. Additive: does not change
# audit_room / audit_plot_level / audit_layout's existing behaviour when this
# check isn't invoked (see audit_layout's geometry_results=None default).
# -------------------------------------------------------------------------

# --- ASSUMPTION: which room TYPES count as a Brahmasthan "obstruction" is a
# --- Vastu-consultant decision, not settled here. Toilet/Staircase/StoreRoom
# --- are heavy/impure structures traditionally excluded from the plot
# --- centre; other heavy structures (pillars, heavy storage) may belong on
# --- this list too. An open LivingRoom sitting over the centre is
# --- deliberately NOT treated as a defect — open/light rooms over the
# --- Brahmasthan are traditionally considered fine, even ideal.
DEFAULT_BRAHMASTHAN_OBSTRUCTING_TYPES = {"Toilet", "Staircase", "StoreRoom"}

# --- ASSUMPTION: 5% is a placeholder threshold chosen only to avoid firing
# --- on rounding-level slivers of overlap — it is NOT a validated cutoff.
# --- Whether partial overlap should scale severity continuously instead of
# --- being a binary major violation is also a consultant sign-off item.
DEFAULT_BRAHMASTHAN_OVERLAP_THRESHOLD = 0.05


def _brahmasthan_remedy(schema):
    """Pull a 'center' remedy from the schema if one exists, else a generic default.

    The schema currently has no room_constraints.*.remedy.center entry for
    any room (Toilet's forbidden list includes "center" but its remedy map
    only covers NE/SW) — this falls back to a documented placeholder in that
    case rather than emitting a violation with no remedy text at all.
    """
    toilet = schema.get("room_constraints", {}).get("Toilet", {})
    remedy = toilet.get("remedy", {}).get("center")
    if remedy:
        return remedy
    return (
        "No remedy documented; classical Vastu requires the central zone be "
        "kept open — structural relocation is the traditional fix, "
        "mitigation only."
    )


def audit_brahmasthan(
    geometry_results,
    schema,
    obstructing_types=None,
    overlap_threshold=DEFAULT_BRAHMASTHAN_OVERLAP_THRESHOLD,
):
    """
    Turn zone_geometry's per-room Brahmasthan fields into audit output.

    geometry_results: iterable of dicts, one per room, in the shape produced
        by zone_geometry.analyze_zones()["rooms"]. Each item must have:
            - "room" (str) — room name. Used both as the type key checked
              against obstructing_types AND as the label in violation text,
              UNLESS the item also carries a "room_type" key, in which case
              "room_type" is used for the obstructing_types check instead
              (needed when instance names like "Toilet_master" don't match
              schema room-type keys like "Toilet" 1:1 — see run_geometry.py).
            - "contains_centre_point" (bool)
            - "overlaps_brahmasthan_region" (bool)
            - "region_overlap_fraction" (float)
    schema: the loaded rule schema, used only to look up a "center" remedy
        (see _brahmasthan_remedy).
    obstructing_types: set of room-type names for which a central overlap is
        a defect. Defaults to DEFAULT_BRAHMASTHAN_OBSTRUCTING_TYPES.
    overlap_threshold: minimum region_overlap_fraction (for non-containing
        rooms) that counts as a scored violation rather than a below-
        threshold informational note. Defaults to
        DEFAULT_BRAHMASTHAN_OVERLAP_THRESHOLD.

    Returns (scored_violations, informational_notes) — two lists, kept
    separate the same way audit_layout separates scored_violations from
    unscored_warnings:
        - scored_violations: rule_type="brahmasthan_obstruction",
          severity="major".
        - informational_notes: rule_type in
          {"brahmasthan_info", "brahmasthan_minor_overlap"}, severity=None
          — visible for human review, never scored.
    """
    if obstructing_types is None:
        obstructing_types = DEFAULT_BRAHMASTHAN_OBSTRUCTING_TYPES

    remedy = _brahmasthan_remedy(schema)

    scored_violations = []
    informational_notes = []

    for room in geometry_results:
        name = room.get("room")
        room_type = room.get("room_type", name)
        contains = bool(room.get("contains_centre_point"))
        overlaps = bool(room.get("overlaps_brahmasthan_region"))
        fraction = room.get("region_overlap_fraction") or 0.0

        if room_type not in obstructing_types:
            # Non-obstructing room type overlapping the region is visible,
            # never scored — e.g. an open LivingRoom over the centre.
            if overlaps:
                informational_notes.append({
                    "room": name,
                    "rule_type": "brahmasthan_info",
                    "message": (
                        f"{name} overlaps the central Brahmasthan region "
                        f"({fraction:.0%}); not scored as a defect for this "
                        f"room type."
                    ),
                    "severity": None,
                })
            continue

        if contains or fraction >= overlap_threshold:
            if contains:
                violation_text = f"{name} contains the exact centre"
            else:
                violation_text = (
                    f"{name} overlaps central Brahmasthan region ({fraction:.0%})"
                )
            scored_violations.append({
                "room": name,
                "rule_type": "brahmasthan_obstruction",
                "violation": violation_text,
                "severity": "major",
                "remedy": remedy,
            })
        elif overlaps:
            # Obstructing type, but the overlap is a thin sliver below the
            # scoring threshold — surfaced for human review, not silently
            # dropped.
            informational_notes.append({
                "room": name,
                "rule_type": "brahmasthan_minor_overlap",
                "message": (
                    f"{name} has a small Brahmasthan region overlap "
                    f"({fraction:.0%}), below the {overlap_threshold:.0%} "
                    f"scoring threshold."
                ),
                "severity": None,
            })

    return scored_violations, informational_notes


def compute_score(scored_violations, base=BASE_SCORE):
    """
    scored_violations: list of violation dicts that have a non-None 'severity'.
    (unknown_room_type warnings are excluded upstream — they carry severity=None
    and are not compliance failures, just missing-rule flags.)
    """
    score = base
    for v in scored_violations:
        score -= SEVERITY_POINTS.get(v.get("severity"), SEVERITY_POINTS["unspecified"])
    return max(score, 0)


def audit_layout(
    input_data,
    schema,
    geometry_results=None,
    brahmasthan_obstructing_types=None,
    brahmasthan_overlap_threshold=DEFAULT_BRAHMASTHAN_OVERLAP_THRESHOLD,
):
    """
    input_data: dict with keys:
        - "plot": dict (see audit_plot_level)
        - "rooms": list of room dicts (see audit_room)
    geometry_results: OPTIONAL. Per-room list from zone_geometry (see
        audit_brahmasthan's docstring for the expected shape). When provided,
        audit_brahmasthan() is run and its output is merged in (see return
        shape below). When omitted (the default), behaviour is IDENTICAL to
        before this parameter existed — no brahmasthan_* keys are added to
        the result, existing callers are unaffected.
    brahmasthan_obstructing_types / brahmasthan_overlap_threshold: passed
        through to audit_brahmasthan() when geometry_results is provided;
        see that function's docstring.

    Returns a result dict:
        {
          "rooms": [ { "room": ..., "zone": ..., "violations": [...] }, ... ],  # only rooms WITH violations/warnings
          "plot_level": [ ... ],
          "compliance_score": int (0-100),
          "total_scored_violations": int,
          "major_count": int,
          "minor_count": int,
          "unscored_warnings": [ ... ],  # e.g. unknown_room_type
          # only present when geometry_results is provided:
          "brahmasthan_violations": [ ... ],  # scored, rule_type=brahmasthan_obstruction
          "brahmasthan_notes": [ ... ],       # informational, never scored
        }
    """
    room_results = []
    scored_violations = []
    unscored_warnings = []

    for room in input_data.get("rooms", []):
        room_violations = audit_room(room, schema)
        if not room_violations:
            continue
        room_results.append({
            "room": room.get("name"),
            "zone": room.get("zone"),
            "violations": room_violations,
        })
        for v in room_violations:
            if v.get("severity") is None:
                unscored_warnings.append(v)
            else:
                scored_violations.append(v)

    plot_violations = audit_plot_level(input_data.get("plot", {}), schema)
    scored_violations.extend(plot_violations)

    result = {
        "rooms": room_results,
        "plot_level": plot_violations,
        "compliance_score": None,  # filled in below, after brahmasthan merge
        "total_scored_violations": None,
        "major_count": None,
        "minor_count": None,
        "unscored_warnings": unscored_warnings,
    }

    if geometry_results is not None:
        brahmasthan_violations, brahmasthan_notes = audit_brahmasthan(
            geometry_results,
            schema,
            obstructing_types=brahmasthan_obstructing_types,
            overlap_threshold=brahmasthan_overlap_threshold,
        )
        scored_violations.extend(brahmasthan_violations)
        result["brahmasthan_violations"] = brahmasthan_violations
        result["brahmasthan_notes"] = brahmasthan_notes

    result["compliance_score"] = compute_score(scored_violations)
    result["total_scored_violations"] = len(scored_violations)
    result["major_count"] = sum(1 for v in scored_violations if v.get("severity") == "major")
    result["minor_count"] = sum(1 for v in scored_violations if v.get("severity") == "minor")

    return result


# -------------------------------------------------------------------------
# OBJECT-PLACEMENT RULES — MY INTERPRETATION, NOT SCHEMA-APPROVED
# -------------------------------------------------------------------------
# The schema's own room_constraints only carry compass-zone rules
# (preferred/acceptable/forbidden zones + adjacency flags). Several rooms
# ALSO have free-text object-level guidance embedded in unrelated fields:
# MasterBedroom.sleeping_direction, Toilet.seat_direction,
# LivingRoom.layout_rule, DiningRoom.seating_rule, and two remedy-text
# mentions (Kitchen "cook facing east", StudyRoom "desk oriented ...").
#
# The table below is THIS MODULE'S structured reading of that free text
# into preferred/forbidden direction codes — it is NOT itself part of
# vastu_rule_schema.json, was not written by a Vastu consultant, and must
# go on the same consultant sign-off list as the rest of the schema (see
# the DATA SOURCE NOTE at the top of this file) before being treated as
# authoritative. If a future schema version encodes these rules directly
# with structured fields, prefer that over this table.
#
# Shape: OBJECT_PLACEMENT_RULES[room_name][object_field] = {
#     "preferred": [direction, ...],
#     "forbidden": [direction, ...],   # may be empty — see rule below
#     "severity":  "major" | "minor",  # ASSUMPTION, see SEVERITY_POINTS note
#     "remedy":    str,
#     "source_text": str,  # the schema text this entry was derived from
# }
#
# Violation rule per field:
#   - if "forbidden" is non-empty: violation iff the given direction is IN
#     "forbidden" (the schema text names specific bad directions).
#   - if "forbidden" is empty: violation iff the given direction is NOT IN
#     "preferred" (the schema text only names a single good direction, with
#     no named opposite — treated as "anything else is non-compliant").
OBJECT_PLACEMENT_RULES = {
    "MasterBedroom": {
        "bed_head_direction": {
            "preferred": ["S", "E"],
            "forbidden": ["N"],
            "severity": "major",
            "remedy": (
                "Reorient the bed so the sleeper's head points South or "
                "East. Sources most consistently single out a "
                "North-pointing head as the one sleeping direction to "
                "avoid above all others."
            ),
            "source_text": (
                "MasterBedroom.sleeping_direction: 'Head towards South "
                "or East; sleeping with head towards North is the one "
                "point sources most consistently advise against.'"
            ),
        },
    },
    "Toilet": {
        "seat_direction": {
            "preferred": ["N", "S"],
            "forbidden": ["E", "W"],
            "severity": "minor",
            "remedy": (
                "Reposition the seat so the person faces North or South "
                "while seated, never East or West."
            ),
            "source_text": (
                "Toilet.seat_direction: 'Person should face North or "
                "South while seated; never East or West.'"
            ),
        },
    },
    "Kitchen": {
        "stove_facing_direction": {
            "preferred": ["E"],
            "forbidden": [],
            "severity": "minor",
            "remedy": "Position the cook facing East while cooking.",
            "source_text": (
                "Kitchen NE remedy note: 'cook facing east' (see "
                "room_constraints.Kitchen.remedy.NE)."
            ),
        },
    },
    "StudyRoom": {
        "desk_facing_direction": {
            "preferred": ["E", "N"],
            "forbidden": [],
            "severity": "minor",
            "remedy": (
                "Orient the desk so the person faces East or North, "
                "regardless of the room's own zone."
            ),
            "source_text": (
                "StudyRoom SW remedy note: 'Desk oriented so the person "
                "faces East or North regardless of room zone.' (see "
                "room_constraints.StudyRoom.remedy.SW)."
            ),
        },
    },
    "LivingRoom": {
        "heavy_furniture_wall": {
            "preferred": ["S", "W"],
            "forbidden": ["N", "E"],
            "severity": "minor",
            "remedy": (
                "Relocate heavy furniture (sofas, cabinets) to the S/W "
                "walls; keep the N/E sides open for light and "
                "circulation."
            ),
            "source_text": (
                "LivingRoom.layout_rule: 'Heavy furniture (sofas, "
                "cabinets) along S/W walls; keep N/E sides relatively "
                "open for light and circulation.'"
            ),
        },
    },
    "DiningRoom": {
        "seating_facing_direction": {
            "preferred": ["E"],
            "forbidden": [],
            "severity": "minor",
            "remedy": "Arrange seating so the family faces East while eating.",
            "source_text": (
                "DiningRoom.seating_rule: 'Family should ideally face "
                "East while eating.'"
            ),
        },
    },
}


def audit_object_placement(room, schema):
    """
    Check a room's OPTIONAL object-placement data against
    OBJECT_PLACEMENT_RULES (see the ASSUMPTION note above that table — this
    is this module's own interpretation of the schema's free text, not a
    schema-defined check).

    room: dict with keys:
        - name (str, required)
        - objects (dict, optional) — e.g. {"bed_head_direction": "N"}.
          Unrecognised rooms or fields are silently ignored (not flagged as
          unknown_room_type like audit_room does), since 'objects' is an
          optional, additive input and most rooms simply won't have an
          object-placement rule at all.

    Note: `schema` is accepted (and reserved) for symmetry with audit_room
    and to allow a future schema version to supply this table directly, but
    the current implementation reads only OBJECT_PLACEMENT_RULES above.

    Returns a list of violation dicts shaped like audit_room's zone/adjacency
    violations, with rule_type = "object_placement", so they merge directly
    into audit_layout-style scoring and reporting.
    """
    name = room.get("name")
    objects = room.get("objects") or {}
    room_rules = OBJECT_PLACEMENT_RULES.get(name, {})

    violations = []
    for field, direction in objects.items():
        rule = room_rules.get(field)
        if rule is None:
            continue

        forbidden = rule.get("forbidden", [])
        preferred = rule.get("preferred", [])
        is_violation = (
            direction in forbidden if forbidden else direction not in preferred
        )
        if not is_violation:
            continue

        violations.append({
            "room": name,
            "rule_type": "object_placement",
            "violation": f"{field}={direction}",
            "severity": rule.get("severity", "minor"),
            "remedy": rule.get("remedy", "No remedy documented for this object-placement rule."),
        })

    return violations


def audit_layout_with_objects(input_data, schema):
    """
    Superset of audit_layout(): same plot-level + zone/adjacency checks,
    PLUS each room's optional 'objects' data checked via
    audit_object_placement(). Added alongside audit_layout/audit_room
    without modifying either — existing callers of audit_layout are
    unaffected.

    Object-placement severities ("major"/"minor") are scored on the SAME
    SEVERITY_POINTS scale as zone/adjacency violations (see the scoring
    ASSUMPTION note at the top of this file) — this is a deliberate reuse,
    not an oversight; a separate points scale was not warranted since the
    schema doesn't numerically weight either category.

    input_data / return shape: identical to audit_layout.
    """
    room_results = []
    scored_violations = []
    unscored_warnings = []

    for room in input_data.get("rooms", []):
        room_violations = audit_room(room, schema) + audit_object_placement(room, schema)
        if not room_violations:
            continue
        room_results.append({
            "room": room.get("name"),
            "zone": room.get("zone"),
            "violations": room_violations,
        })
        for v in room_violations:
            if v.get("severity") is None:
                unscored_warnings.append(v)
            else:
                scored_violations.append(v)

    plot_violations = audit_plot_level(input_data.get("plot", {}), schema)
    scored_violations.extend(plot_violations)

    return {
        "rooms": room_results,
        "plot_level": plot_violations,
        "compliance_score": compute_score(scored_violations),
        "total_scored_violations": len(scored_violations),
        "major_count": sum(1 for v in scored_violations if v.get("severity") == "major"),
        "minor_count": sum(1 for v in scored_violations if v.get("severity") == "minor"),
        "unscored_warnings": unscored_warnings,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python vastu_audit.py <input_layout.json> [schema_path]")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    schema_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).parent / "vastu_rule_schema.json"

    schema = load_schema(schema_path)
    with open(input_path, "r", encoding="utf-8") as f:
        input_data = json.load(f)

    result = audit_layout(input_data, schema)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
