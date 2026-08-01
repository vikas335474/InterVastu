"""Run zone_geometry on a real-flat polygon fixture, then feed the result
into the existing deterministic audit engine (vastu_audit.py), end to end.

This script does no geometry or audit logic of its own — it only:
  1. loads a fixture of {boundary, north_offset_deg, rooms[with polygons]},
  2. calls zone_geometry.analyze_zones() and prints a readable report,
  3. maps each room's computed zone onto the audit engine's expected
     {"plot": ..., "rooms": [{"name", "zone", ...}]} input shape, and
  4. calls vastu_audit.audit_layout() and prints the result.

Room-name mapping note: the audit schema's room_constraints use generic
room-type keys (e.g. "Toilet", "DiningRoom"), not the fixture's more specific
instance names (e.g. "Toilet_master", "DiningRoom_DRG"). ROOM_TYPE_MAP below
records that mapping explicitly; any fixture room name not listed is passed
through unchanged.
"""

import json
import sys
from pathlib import Path

import zone_geometry as zg
from vastu_audit import audit_layout, load_schema

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "flat_unit12_polygons.json"
SCHEMA_PATH = Path(__file__).parent / "vastu_rule_schema.json"

# --- Fixture room name -> audit schema room-type key. Not part of the ---
# --- schema or zone_geometry; this script's own mapping. See module docstring.
ROOM_TYPE_MAP = {
    "Toilet_master": "Toilet",
    "Toilet_central": "Toilet",
    "Toilet_guest": "Toilet",
    "DiningRoom_DRG": "DiningRoom",
}

# Plot-level facts not derivable from geometry alone; supplied here so
# audit_layout() has a complete input. Not asserted by zone_geometry.
PLOT_LEVEL = {
    "shape": "L_shaped_without_correction",
    "floor_slope": {"high_corner": "SW", "low_corner": "NE"},
    "brahmasthan_obstructed": False,
}


def load_fixture(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def print_geometry_report(geometry_result):
    print("=" * 78)
    print("GEOMETRY  (zone_geometry.analyze_zones)")
    print("=" * 78)
    c = geometry_result["centre"]
    p = geometry_result["params"]
    print(f"centre: x={c['x']:.3f}  y={c['y']:.3f}")
    print(f"params: north_offset_deg={p['north_offset_deg']:.3f}  "
          f"brahmasthan_area_fraction={p['brahmasthan_area_fraction']:.6f}")
    print()

    header = (
        f"{'room':<18} {'zone':<5} {'conf':<6} {'margin_deg':>10}  "
        f"{'contains_pt':>11} {'overlaps_reg':>12} {'overlap_frac':>12} {'nearest_ft':>10}"
    )
    print(header)
    print("-" * len(header))
    for r in geometry_result["rooms"]:
        zone = r["zone"] if r["zone"] is not None else "-"
        conf = r["zone_confidence"] if r["zone_confidence"] is not None else "-"
        margin = f"{r['boundary_margin_deg']:.2f}" if r["boundary_margin_deg"] is not None else "-"
        nearest = f"{r['nearest_distance_ft']:.2f}" if r["nearest_distance_ft"] is not None else "-"
        print(
            f"{r['room']:<18} {zone:<5} {conf:<6} {margin:>10}  "
            f"{str(r['contains_centre_point']):>11} {str(r['overlaps_brahmasthan_region']):>12} "
            f"{r['region_overlap_fraction']:>12.4f} {nearest:>10}"
        )
    print()


def build_audit_input(geometry_result):
    rooms = []
    for r in geometry_result["rooms"]:
        audit_name = ROOM_TYPE_MAP.get(r["room"], r["room"])
        rooms.append({"name": audit_name, "zone": r["zone"]})
    return {"plot": PLOT_LEVEL, "rooms": rooms}


def print_audit_report(audit_result):
    print("=" * 78)
    print("AUDIT  (vastu_audit.audit_layout)")
    print("=" * 78)
    print(json.dumps(audit_result, indent=2))


def main():
    fixture = load_fixture(FIXTURE_PATH)
    geometry_result = zg.analyze_zones(
        fixture["boundary"],
        fixture["rooms"],
        north_offset_deg=fixture["north_offset_deg"],
    )
    print_geometry_report(geometry_result)

    schema = load_schema(SCHEMA_PATH)
    audit_input = build_audit_input(geometry_result)
    audit_result = audit_layout(audit_input, schema)
    print_audit_report(audit_result)


if __name__ == "__main__":
    sys.exit(main())
