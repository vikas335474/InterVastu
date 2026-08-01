"""
Thin FastAPI wrapper over the existing Vastu audit engine, for local manual
testing only. It adds no rules of its own — it just loads the schema via
the engine's own load_schema() and calls the engine's own audit_layout()
directly. All audit logic, scoring, and remedy text come from
genesis/engine/vastu_audit.py and vastu_rule_schema.json, unmodified.
"""

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
import uvicorn

UI_DIR = Path(__file__).parent
REPO_ROOT = UI_DIR.parent
ENGINE_DIR = REPO_ROOT / "genesis" / "engine"

sys.path.insert(0, str(ENGINE_DIR))

from vastu_audit import load_schema, audit_layout  # noqa: E402

SCHEMA_PATH = ENGINE_DIR / "vastu_rule_schema.json"
SCHEMA = load_schema(SCHEMA_PATH)

app = FastAPI(title="Vastu Audit Engine — Local Test UI")


@app.get("/")
def index():
    return FileResponse(UI_DIR / "index.html")


@app.get("/schema-info")
def schema_info():
    room_constraints = SCHEMA.get("room_constraints", {})
    zones = set(SCHEMA.get("zones", []))

    room_types = {}
    for name, constraints in room_constraints.items():
        forbidden = constraints.get("forbidden", [])
        adjacency_flags = [f for f in forbidden if f not in zones]
        room_types[name] = {
            "preferred": constraints.get("preferred", []),
            "acceptable": constraints.get("acceptable", []),
            "forbidden": forbidden,
            "adjacency_flags": adjacency_flags,
        }

    return {
        "room_types": list(room_constraints.keys()),
        "zones": SCHEMA.get("zones", []),
        "room_type_details": room_types,
        "plot_shapes": {
            "preferred": SCHEMA.get("plot_level_rules", {}).get("shape", {}).get("preferred", []),
            "forbidden": SCHEMA.get("plot_level_rules", {}).get("shape", {}).get("forbidden", []),
        },
        "schema_meta": SCHEMA.get("_meta", {}),
    }


@app.post("/audit")
def audit(layout: dict):
    return audit_layout(layout, SCHEMA)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
