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


def audit_layout(input_data, schema):
    """
    input_data: dict with keys:
        - "plot": dict (see audit_plot_level)
        - "rooms": list of room dicts (see audit_room)

    Returns a result dict:
        {
          "rooms": [ { "room": ..., "zone": ..., "violations": [...] }, ... ],  # only rooms WITH violations/warnings
          "plot_level": [ ... ],
          "compliance_score": int (0-100),
          "total_scored_violations": int,
          "major_count": int,
          "minor_count": int,
          "unscored_warnings": [ ... ]  # e.g. unknown_room_type
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
