"""
Runs the audit engine against every fixture in fixtures/ and prints results.
Not a formal test suite (no assertions) — a readable demonstration/sanity-check
that the four required cases behave as described:
  1. compliant.json            -> 0 violations, score 100
  2. major_ne_toilet.json       -> 1 major violation (Toilet/NE)
  3. minor_kitchen_north.json   -> 1 minor violation (Kitchen/N)
  4. compound_pooja_toilet.json -> 1 major violation (PoojaRoom adjacency), zone itself clean
"""

import json
from pathlib import Path

from vastu_audit import load_schema, audit_layout

BASE_DIR = Path(__file__).parent
SCHEMA = load_schema(BASE_DIR / "vastu_rule_schema.json")
FIXTURES_DIR = BASE_DIR / "fixtures"


def run(fixture_name):
    path = FIXTURES_DIR / fixture_name
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    result = audit_layout(data, SCHEMA)

    print(f"\n{'=' * 70}")
    print(f"FIXTURE: {fixture_name}")
    if "_fixture_purpose" in data:
        print(f"PURPOSE: {data['_fixture_purpose']}")
    print(f"{'=' * 70}")
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    for name in [
        "compliant.json",
        "major_ne_toilet.json",
        "minor_kitchen_north.json",
        "compound_pooja_toilet.json",
    ]:
        run(name)
