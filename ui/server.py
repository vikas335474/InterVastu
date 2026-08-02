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

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
import uvicorn

UI_DIR = Path(__file__).parent
REPO_ROOT = UI_DIR.parent
ENGINE_DIR = REPO_ROOT / "genesis" / "engine"

sys.path.insert(0, str(ENGINE_DIR))
sys.path.insert(0, str(UI_DIR))

from vastu_audit import load_schema, audit_layout  # noqa: E402
import zone_geometry as zg  # noqa: E402
import ritual_protocol  # noqa: E402
import storage  # noqa: E402
import suggestions  # noqa: E402

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


def require_admin(x_admin_token: str | None = Header(None)):
    """Gate for actions affecting SHARED project data (many unrelated flat
    owners' audits depend on it, unlike a flat which only affects its own
    owner) — see storage.py's module docstring for why project_versions can
    only be written via an approved proposal, and why approval itself needs
    a real gate instead of the rest of this app's no-auth stance.

    Deliberately FAILS CLOSED: if VASTU_ADMIN_TOKEN isn't set on the server
    at all, admin endpoints refuse every request (503) rather than silently
    accepting any/no token (which an unset env var would otherwise look
    like). This is a single shared-secret gate, not a user-account system —
    proportionate to "one or a few trusted admins," the same scale
    assumption storage.py's own README already states for the rest of this
    app; revisit if that assumption stops holding.
    """
    configured_token = os.environ.get("VASTU_ADMIN_TOKEN")
    if not configured_token:
        raise HTTPException(
            status_code=503,
            detail="Admin functionality is not configured on this server (VASTU_ADMIN_TOKEN is unset).",
        )
    if x_admin_token != configured_token:
        raise HTTPException(status_code=403, detail="Invalid or missing admin token.")


def _run_audit(payload: dict) -> tuple[dict, dict]:
    """Build the {"plot", "rooms"} input the engine expects, audit it, and
    attach constructive placement suggestions (suggestions.py) for any room
    that both supplied a "polygon" and has a supported room type (see
    suggestions.py — most room types have no placement solver at all, that's
    not an error, those rooms just get no "suggestions" entry).

    facade_bearing_deg / furniture_dimensions are optional top-level payload
    keys; see suggestions.suggest_for_layout for their meaning and defaults.
    Rooms without a "polygon" key are unaffected — they still get the usual
    zone/adjacency audit, just no placement suggestion.
    """
    rooms = payload.get("rooms", [])
    facade_bearing_deg = payload.get("facade_bearing_deg", 0.0) or 0.0
    furniture_dimensions = payload.get("furniture_dimensions")
    boundary = payload.get("boundary")

    # Persist facade_bearing_deg/furniture_dimensions/boundary alongside
    # plot/rooms so a saved flat round-trips through storage with its
    # suggestion + shape-diagnosis inputs intact, not just its audit inputs.
    input_data = {
        "plot": payload.get("plot", {}),
        "rooms": rooms,
        "facade_bearing_deg": facade_bearing_deg,
        "furniture_dimensions": furniture_dimensions,
        "boundary": boundary,
    }

    # Footprint-level shape diagnosis (hollow-centre + missing-zone) only runs
    # when the caller supplies a "boundary" polygon; when it's absent the audit
    # is exactly as before (no shape_defect_* keys). facade_bearing_deg is the
    # plan's north offset, in the same convention diagnose_shape expects.
    shape_diagnosis = None
    if boundary:
        try:
            shape_diagnosis = zg.diagnose_shape(boundary, north_offset_deg=facade_bearing_deg)
        except (ValueError, TypeError):
            # A malformed boundary must not take down the whole audit; the rest
            # of the report (zone/adjacency/suggestions) is still valid.
            shape_diagnosis = None

    result = audit_layout(input_data, SCHEMA, shape_diagnosis=shape_diagnosis)
    if shape_diagnosis is not None:
        result["shape_diagnosis"] = shape_diagnosis
    result["suggestions"] = suggestions.suggest_for_layout(
        rooms, facade_bearing_deg=facade_bearing_deg, furniture_dimensions=furniture_dimensions
    )

    # OPT-IN ONLY. Traditional ritual/activation content (ritual_protocol.py)
    # is attached to directional defects only when the caller explicitly sets
    # include_ritual_protocol: true. It is off by default because enabling it
    # is a product/legal/cultural decision, not an audit default — see the
    # ritual_protocol module docstring. include_ritual_protocol is persisted in
    # input_data so a saved flat records whether it was requested.
    include_ritual = bool(payload.get("include_ritual_protocol"))
    input_data["include_ritual_protocol"] = include_ritual
    if include_ritual:
        for key in ("shape_defect_violations", "brahmasthan_violations"):
            if key in result:
                result[key] = ritual_protocol.enrich_defects_with_ritual(result[key])

    return input_data, result


@app.get("/")
def index():
    return FileResponse(UI_DIR / "index.html")


@app.get("/admin")
def admin_page():
    """Serves the admin review UI. The page itself is static HTML/JS — it
    prompts for the admin token client-side and sends it as a header on
    every request; the actual gate is require_admin() on each endpoint
    below, not this route (serving the page's HTML is not sensitive, since
    it does nothing without a valid token)."""
    return FileResponse(UI_DIR / "admin.html")


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
    that don't belong to a named flat. Includes placement suggestions (see
    _run_audit) for any room that supplied a polygon and a supported type."""
    _, result = _run_audit(layout)
    return result


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


# ---------------------------------------------------------------------------
# Projects: shared building-level data, reused across many flat owners.
# See storage.py's module docstring for the submit -> approve/reject model.
#
# Route order matters here: FastAPI/Starlette matches routes in registration
# order, and "/projects/proposals" would otherwise be swallowed by the
# earlier, more general "/projects/{project_id}" (which would try to parse
# "proposals" as an int and 422). All literal "/projects/proposals..."
# routes are therefore registered BEFORE the "/projects/{project_id}..."
# routes below them.
# ---------------------------------------------------------------------------

@app.post("/projects/proposals")
def submit_project_proposal(payload: dict, conn=Depends(get_conn)):
    """Public — anyone can propose a brand-new project (omit project_id) or
    a correction/update to an existing one (set project_id). Takes effect on
    nothing until an admin approves it; see storage.submit_project_proposal.
    """
    submitted_by = (payload.get("submitted_by") or "").strip()
    if not submitted_by:
        raise HTTPException(status_code=400, detail="submitted_by is required")

    try:
        proposal_id = storage.submit_project_proposal(
            conn,
            submitted_by,
            project_id=payload.get("project_id"),
            proposed_name=payload.get("proposed_name"),
            proposed_rera_reference=payload.get("proposed_rera_reference"),
            proposed_builder=payload.get("proposed_builder"),
            proposed_address=payload.get("proposed_address"),
            proposed_boundary=payload.get("proposed_boundary"),
            proposed_facade_bearing_deg=payload.get("proposed_facade_bearing_deg"),
            proposed_base_rooms=payload.get("proposed_base_rooms"),
            note=payload.get("note"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"proposal_id": proposal_id, "status": "pending"}


@app.get("/projects/proposals")
def list_project_proposals(
    status: str | None = None, conn=Depends(get_conn), _admin=Depends(require_admin)
):
    """Admin-only — this is the review queue. Listing every proposal
    (including who submitted what) is reserved to an admin even though a
    single proposal by id (below) is public."""
    return storage.list_project_proposals(conn, status=status)


@app.post("/projects/proposals/{proposal_id}/approve")
def approve_project_proposal(
    proposal_id: int, payload: dict | None = None, conn=Depends(get_conn), _admin=Depends(require_admin)
):
    """Admin-only. Accepting a proposal as-is is the only path in v1 — an
    admin who wants different data submits their own corrective proposal
    and approves that instead, rather than editing someone else's proposal
    in place (keeps exactly one code path for "how project data changes,"
    per storage.py's module docstring)."""
    reviewed_note = (payload or {}).get("reviewed_note")
    try:
        result = storage.approve_project_proposal(conn, proposal_id, reviewed_note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@app.post("/projects/proposals/{proposal_id}/reject")
def reject_project_proposal(
    proposal_id: int, payload: dict | None = None, conn=Depends(get_conn), _admin=Depends(require_admin)
):
    """Admin-only. The proposal row is kept (status='rejected'), not deleted."""
    reviewed_note = (payload or {}).get("reviewed_note")
    try:
        storage.reject_project_proposal(conn, proposal_id, reviewed_note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"proposal_id": proposal_id, "status": "rejected"}


@app.get("/projects/proposals/{proposal_id}")
def get_project_proposal(proposal_id: int, conn=Depends(get_conn)):
    """Public by design — a submitter gets this id back from the POST above
    and can use it to check their own proposal's status. Proposal content
    isn't sensitive (it's the same kind of data a project version would
    publish anyway once approved)."""
    proposal = storage.get_project_proposal(conn, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="proposal not found")
    return proposal


@app.get("/projects")
def list_projects(conn=Depends(get_conn)):
    """Public — anyone can browse projects to attach their flat to."""
    return storage.list_projects(conn)


@app.get("/projects/{project_id}")
def get_project(project_id: int, conn=Depends(get_conn)):
    """Public — full version history of one project, so a flat owner can see
    what a project's confirmed geometry looked like at any point."""
    project = storage.get_project(conn, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


@app.get("/projects/{project_id}/versions/{version_number}")
def get_project_version(project_id: int, version_number: int, conn=Depends(get_conn)):
    version = storage.get_project_version(conn, project_id, version_number)
    if version is None:
        raise HTTPException(status_code=404, detail="project version not found")
    return version


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
