"""
Thin FastAPI wrapper over the existing Vastu audit engine, plus a small
SQLite persistence layer (storage.py) so saved flats and their audit
history survive across visits. It adds no audit logic of its own — it
loads the schema via the engine's own load_schema() and calls the engine's
own audit_layout() directly. All audit logic, scoring, and remedy text come
from genesis/engine/vastu_audit.py and vastu_rule_schema.json, unmodified.

Persistence model (see storage.py for the schema/rationale): a "flat" is a
named, owned record; each save/edit creates a new numbered "version" rather
than overwriting the previous one, so a user can tweak a room polygon,
re-audit, and compare the new result against every prior version.
"""

import os
import sys
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
import uvicorn

UI_DIR = Path(__file__).parent
REPO_ROOT = UI_DIR.parent
ENGINE_DIR = REPO_ROOT / "genesis" / "engine"

sys.path.insert(0, str(ENGINE_DIR))
sys.path.insert(0, str(UI_DIR))

from vastu_audit import load_schema, audit_layout  # noqa: E402
import storage  # noqa: E402

SCHEMA_PATH = ENGINE_DIR / "vastu_rule_schema.json"
SCHEMA = load_schema(SCHEMA_PATH)

# Overridable so tests (and a future deploy config) can point at a
# different SQLite file without touching the real one.
DB_PATH = os.environ.get("VASTU_UI_DB_PATH", str(storage.DEFAULT_DB_PATH))

app = FastAPI(title="Vastu Audit Engine — Local Test UI")


def get_conn():
    """Per-request SQLite connection (open/close each call).

    SQLite handles this access pattern fine at this scale and it sidesteps
    any cross-thread sharing concerns from FastAPI running sync endpoints
    in a thread pool — simpler than managing one long-lived connection.
    """
    conn = storage.open_db(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


def _run_audit(payload: dict) -> tuple[dict, dict]:
    """Build the {"plot", "rooms"} input the engine expects and audit it."""
    input_data = {"plot": payload.get("plot", {}), "rooms": payload.get("rooms", [])}
    result = audit_layout(input_data, SCHEMA)
    return input_data, result


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
    """Stateless one-off audit — nothing is saved. Kept for quick checks
    that don't belong to a named flat."""
    return audit_layout(layout, SCHEMA)


# ---------------------------------------------------------------------------
# Persistence: flats + versions
# ---------------------------------------------------------------------------

@app.post("/flats")
def create_flat(payload: dict, conn=Depends(get_conn)):
    """Create a new flat and save its first audit run as version 1."""
    label = (payload.get("label") or "").strip()
    owner = (payload.get("owner") or "").strip()
    if not label or not owner:
        raise HTTPException(status_code=400, detail="label and owner are both required")

    input_data, result = _run_audit(payload)
    flat_id = storage.create_flat(conn, label, owner, input_data, result, note=payload.get("note"))
    return {"flat_id": flat_id, "version": 1, "input": input_data, "result": result}


@app.get("/flats")
def list_flats(conn=Depends(get_conn)):
    return storage.list_flats(conn)


@app.get("/flats/{flat_id}")
def get_flat(flat_id: int, conn=Depends(get_conn)):
    flat = storage.get_flat(conn, flat_id)
    if flat is None:
        raise HTTPException(status_code=404, detail="flat not found")
    return flat


@app.post("/flats/{flat_id}/versions")
def add_flat_version(flat_id: int, payload: dict, conn=Depends(get_conn)):
    """Save an edited layout as a new version of an existing flat and
    re-audit it, so the new result can be compared against prior versions."""
    input_data, result = _run_audit(payload)
    try:
        version = storage.add_version(conn, flat_id, input_data, result, note=payload.get("note"))
    except ValueError:
        raise HTTPException(status_code=404, detail="flat not found")
    return {"flat_id": flat_id, "version": version, "input": input_data, "result": result}


@app.get("/flats/{flat_id}/versions/{version_number}")
def get_flat_version(flat_id: int, version_number: int, conn=Depends(get_conn)):
    version = storage.get_version(conn, flat_id, version_number)
    if version is None:
        raise HTTPException(status_code=404, detail="version not found")
    return version


@app.delete("/flats/{flat_id}")
def delete_flat(flat_id: int, conn=Depends(get_conn)):
    if not storage.delete_flat(conn, flat_id):
        raise HTTPException(status_code=404, detail="flat not found")
    return {"deleted": True}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
