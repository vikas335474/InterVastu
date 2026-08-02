"""SQLite-backed persistence for the Vastu audit UI.

At this scale (a handful of known users, at most a few hundred flats) a
single SQLite file is deliberately preferred over a separate database
server: zero setup, one file to back up, plenty fast for this access
pattern. Revisit only if this grows into a genuinely multi-tenant public
product.

Data model
----------
* ``flats``: one row per named flat (label, owner, created_at). ``owner``
  is a free-text string the caller supplies (e.g. a name or email) — there
  is NO authentication here, it's just a label to tell whose flat is whose
  among a small set of known/trusted users. Do not treat it as an access
  control mechanism.
* ``flat_versions``: one row per saved audit run for a flat. Editing a
  flat's polygons/rooms and re-auditing creates a NEW version rather than
  overwriting the old one, so every past run stays available for
  comparison — this is what makes "tweak it a little and see what changed"
  possible without any extra diffing logic: just compare two stored
  versions' ``result_json``.

Building/project sharing (``projects`` / ``project_versions`` / ``project_proposals``)
----------------------------------------------------------------------------------------
Most retail flat owners cannot reliably provide a full traced boundary and
room set themselves. These three tables let ONE building's geometry
(boundary, confirmed facade bearing, a base/typical-unit room layout — e.g.
sourced from a RERA filing or builder blueprint) be captured once and reused
by every flat owner in that project, instead of each of them tracing from
scratch.

* ``projects``: one row per building/project (name, optional RERA
  reference/builder/address). Bare identity only — the actual geometry lives
  in ``project_versions``, exactly the same split as ``flats``/``flat_versions``.
* ``project_versions``: the CONFIRMED, live data for a project at a point in
  time (boundary polygon, facade bearing, base room layout). Versioned, not
  overwritten, same rationale as ``flat_versions``. **The only way a row is
  ever inserted here is via ``approve_project_proposal`` below** — there is
  no direct "just write a project version" function, so every live project
  version has a corresponding proposal on record, including ones an admin
  authored themselves. This keeps exactly one code path for "how did this
  building's data come to be," which is both simpler and more auditable than
  having two.
* ``project_proposals``: a suggested project (``project_id IS NULL``) or a
  suggested new version of an existing one (``project_id`` set), submitted by
  ANYONE — no authentication is required to submit, matching this module's
  existing no-auth stance for flats. A proposal does nothing on its own; it
  only takes effect once an admin calls ``approve_project_proposal`` (which
  the caller — see ``server.py`` — must gate behind an admin check, since
  project data is shared across many unrelated flat owners' audits and a bad
  edit would affect all of them, unlike a flat which only affects its own
  owner). ``reject_project_proposal`` marks a proposal rejected without
  discarding it, so the record of what was suggested and why it wasn't
  accepted stays visible — consistent with this codebase's habit of
  surfacing rather than silently dropping information.

Every function here takes an already-open ``sqlite3.Connection`` (see
``open_db``) rather than managing its own connection lifecycle, so callers
(the FastAPI app, tests) control when a connection opens/closes.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path(__file__).parent / "vastu_ui.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS flats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    owner TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS flat_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    flat_id INTEGER NOT NULL REFERENCES flats(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    input_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (flat_id, version_number)
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    rera_reference TEXT,
    builder TEXT,
    address TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS project_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    boundary_json TEXT,
    facade_bearing_deg REAL,
    base_rooms_json TEXT,
    note TEXT,
    source_proposal_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (project_id, version_number)
);

CREATE TABLE IF NOT EXISTS project_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    proposed_name TEXT,
    proposed_rera_reference TEXT,
    proposed_builder TEXT,
    proposed_address TEXT,
    proposed_boundary_json TEXT,
    proposed_facade_bearing_deg REAL,
    proposed_base_rooms_json TEXT,
    submitted_by TEXT NOT NULL,
    note TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    reviewed_note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    reviewed_at TEXT
);
"""


def open_db(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open (creating if necessary) the SQLite file at ``db_path`` and
    ensure the schema exists. Returns a connection with row access by
    column name (``sqlite3.Row``) and foreign-key enforcement turned on.

    ``check_same_thread=False``: FastAPI runs sync path-operation
    dependencies (like the caller's per-request ``get_conn()``) in a worker
    thread pool, and a generator dependency's setup (before ``yield``) and
    teardown (after ``yield``, i.e. this connection's ``.close()``) are not
    guaranteed to land on the SAME worker thread — a real browser firing
    several fetches on page load reliably triggers this. sqlite3 connections
    are single-thread-only by default and raise ProgrammingError in that
    case. This is safe to relax here specifically because each connection
    is still only ever used by ONE request at a time sequentially (opened
    and closed within that one request's dependency lifecycle) — the
    constraint being relaxed is "same OS thread", not "no concurrent use".
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def create_flat(
    conn: sqlite3.Connection,
    label: str,
    owner: str,
    input_data: dict[str, Any],
    result_data: dict[str, Any],
    note: str | None = None,
) -> int:
    """Create a new flat with its first version (version_number=1).

    Returns the new flat's id.
    """
    cur = conn.execute(
        "INSERT INTO flats (label, owner) VALUES (?, ?)", (label, owner)
    )
    flat_id = cur.lastrowid
    conn.execute(
        "INSERT INTO flat_versions (flat_id, version_number, input_json, result_json, note) "
        "VALUES (?, 1, ?, ?, ?)",
        (flat_id, json.dumps(input_data), json.dumps(result_data), note),
    )
    conn.commit()
    return flat_id


def add_version(
    conn: sqlite3.Connection,
    flat_id: int,
    input_data: dict[str, Any],
    result_data: dict[str, Any],
    note: str | None = None,
) -> int:
    """Add a new version to an existing flat (e.g. after editing/re-auditing).

    Returns the new version_number (1 + the previous highest for this flat).
    Raises ValueError if flat_id doesn't exist — callers should turn this
    into a 404, not a 500.
    """
    row = conn.execute("SELECT id FROM flats WHERE id = ?", (flat_id,)).fetchone()
    if row is None:
        raise ValueError(f"flat {flat_id} does not exist")

    max_version = conn.execute(
        "SELECT MAX(version_number) AS m FROM flat_versions WHERE flat_id = ?",
        (flat_id,),
    ).fetchone()["m"]
    next_version = (max_version or 0) + 1

    conn.execute(
        "INSERT INTO flat_versions (flat_id, version_number, input_json, result_json, note) "
        "VALUES (?, ?, ?, ?, ?)",
        (flat_id, next_version, json.dumps(input_data), json.dumps(result_data), note),
    )
    conn.commit()
    return next_version


def list_flats(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """One summary row per flat, using its LATEST version for the score."""
    rows = conn.execute(
        """
        SELECT f.id, f.label, f.owner, f.created_at,
               v.version_number AS latest_version,
               v.result_json AS latest_result_json,
               v.created_at AS latest_version_created_at
        FROM flats f
        JOIN flat_versions v ON v.flat_id = f.id
        WHERE v.version_number = (
            SELECT MAX(version_number) FROM flat_versions WHERE flat_id = f.id
        )
        ORDER BY f.id
        """
    ).fetchall()

    summaries = []
    for r in rows:
        result = json.loads(r["latest_result_json"])
        summaries.append({
            "id": r["id"],
            "label": r["label"],
            "owner": r["owner"],
            "created_at": r["created_at"],
            "latest_version": r["latest_version"],
            "latest_version_created_at": r["latest_version_created_at"],
            "latest_compliance_score": result.get("compliance_score"),
            "latest_major_count": result.get("major_count"),
            "latest_minor_count": result.get("minor_count"),
        })
    return summaries


def get_flat(conn: sqlite3.Connection, flat_id: int) -> dict[str, Any] | None:
    """Full flat record with ALL versions (oldest first), or None if missing."""
    flat_row = conn.execute("SELECT * FROM flats WHERE id = ?", (flat_id,)).fetchone()
    if flat_row is None:
        return None

    version_rows = conn.execute(
        "SELECT version_number, input_json, result_json, note, created_at "
        "FROM flat_versions WHERE flat_id = ? ORDER BY version_number",
        (flat_id,),
    ).fetchall()

    return {
        "id": flat_row["id"],
        "label": flat_row["label"],
        "owner": flat_row["owner"],
        "created_at": flat_row["created_at"],
        "versions": [_version_dict(v) for v in version_rows],
    }


def get_version(
    conn: sqlite3.Connection, flat_id: int, version_number: int
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT version_number, input_json, result_json, note, created_at "
        "FROM flat_versions WHERE flat_id = ? AND version_number = ?",
        (flat_id, version_number),
    ).fetchone()
    if row is None:
        return None
    return _version_dict(row)


def delete_flat(conn: sqlite3.Connection, flat_id: int) -> bool:
    """Delete a flat and all its versions. Returns True if a flat was deleted."""
    cur = conn.execute("DELETE FROM flats WHERE id = ?", (flat_id,))
    conn.commit()
    return cur.rowcount > 0


def _version_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "version_number": row["version_number"],
        "input": json.loads(row["input_json"]),
        "result": json.loads(row["result_json"]),
        "note": row["note"],
        "created_at": row["created_at"],
    }


# ---------------------------------------------------------------------------
# Projects: shared building-level data (see module docstring)
# ---------------------------------------------------------------------------

def submit_project_proposal(
    conn: sqlite3.Connection,
    submitted_by: str,
    *,
    project_id: int | None = None,
    proposed_name: str | None = None,
    proposed_rera_reference: str | None = None,
    proposed_builder: str | None = None,
    proposed_address: str | None = None,
    proposed_boundary: list | None = None,
    proposed_facade_bearing_deg: float | None = None,
    proposed_base_rooms: list | None = None,
    note: str | None = None,
) -> int:
    """Record a proposal — either a brand-new project (``project_id=None``)
    or a suggested new version of an existing one. Takes effect on NOTHING
    until ``approve_project_proposal`` is called; this only inserts a
    'pending' row. No authentication is required here (matches this
    module's existing no-auth stance) — approval is where trust is enforced,
    by the caller (see ``server.py``).

    Raises ValueError if ``project_id`` is given but doesn't exist, or if
    ``project_id`` is None and no ``proposed_name`` was given (a new project
    needs at least a name to be reviewable).
    """
    if project_id is not None:
        row = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise ValueError(f"project {project_id} does not exist")
    elif not proposed_name:
        raise ValueError("proposed_name is required when proposing a new project (project_id is None)")

    cur = conn.execute(
        """
        INSERT INTO project_proposals (
            project_id, proposed_name, proposed_rera_reference, proposed_builder,
            proposed_address, proposed_boundary_json, proposed_facade_bearing_deg,
            proposed_base_rooms_json, submitted_by, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project_id, proposed_name, proposed_rera_reference, proposed_builder,
            proposed_address,
            json.dumps(proposed_boundary) if proposed_boundary is not None else None,
            proposed_facade_bearing_deg,
            json.dumps(proposed_base_rooms) if proposed_base_rooms is not None else None,
            submitted_by, note,
        ),
    )
    conn.commit()
    return cur.lastrowid


def list_project_proposals(
    conn: sqlite3.Connection, status: str | None = None
) -> list[dict[str, Any]]:
    """All proposals, optionally filtered by status ('pending'/'approved'/'rejected').

    Newest first, so an admin reviewing 'pending' sees the latest first.
    """
    if status is not None:
        rows = conn.execute(
            "SELECT * FROM project_proposals WHERE status = ? ORDER BY id DESC", (status,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM project_proposals ORDER BY id DESC").fetchall()
    return [_proposal_dict(r) for r in rows]


def get_project_proposal(conn: sqlite3.Connection, proposal_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM project_proposals WHERE id = ?", (proposal_id,)
    ).fetchone()
    return _proposal_dict(row) if row is not None else None


def approve_project_proposal(
    conn: sqlite3.Connection, proposal_id: int, reviewed_note: str | None = None
) -> dict[str, Any]:
    """Accept a pending proposal, creating (or adding a version to) a project.

    Returns ``{"project_id": ..., "version_number": ...}``. Raises
    ValueError if the proposal doesn't exist or isn't 'pending' (approving
    twice, or approving something already rejected, is refused rather than
    silently allowed — the status field is the single source of truth for
    whether a proposal has been acted on).
    """
    proposal = conn.execute(
        "SELECT * FROM project_proposals WHERE id = ?", (proposal_id,)
    ).fetchone()
    if proposal is None:
        raise ValueError(f"proposal {proposal_id} does not exist")
    if proposal["status"] != "pending":
        raise ValueError(f"proposal {proposal_id} is not pending (status={proposal['status']!r})")

    project_id = proposal["project_id"]
    if project_id is None:
        cur = conn.execute(
            "INSERT INTO projects (name, rera_reference, builder, address) VALUES (?, ?, ?, ?)",
            (proposal["proposed_name"], proposal["proposed_rera_reference"],
             proposal["proposed_builder"], proposal["proposed_address"]),
        )
        project_id = cur.lastrowid
        next_version = 1
    else:
        max_version = conn.execute(
            "SELECT MAX(version_number) AS m FROM project_versions WHERE project_id = ?",
            (project_id,),
        ).fetchone()["m"]
        next_version = (max_version or 0) + 1

    conn.execute(
        """
        INSERT INTO project_versions (
            project_id, version_number, boundary_json, facade_bearing_deg,
            base_rooms_json, note, source_proposal_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project_id, next_version,
            proposal["proposed_boundary_json"], proposal["proposed_facade_bearing_deg"],
            proposal["proposed_base_rooms_json"], proposal["note"], proposal_id,
        ),
    )
    conn.execute(
        "UPDATE project_proposals SET status = 'approved', reviewed_note = ?, "
        "reviewed_at = datetime('now') WHERE id = ?",
        (reviewed_note, proposal_id),
    )
    conn.commit()
    return {"project_id": project_id, "version_number": next_version}


def reject_project_proposal(
    conn: sqlite3.Connection, proposal_id: int, reviewed_note: str | None = None
) -> None:
    """Mark a pending proposal rejected. The row is kept, not deleted, so
    what was suggested (and why it wasn't accepted) stays on record.

    Raises ValueError if the proposal doesn't exist or isn't 'pending'.
    """
    proposal = conn.execute(
        "SELECT status FROM project_proposals WHERE id = ?", (proposal_id,)
    ).fetchone()
    if proposal is None:
        raise ValueError(f"proposal {proposal_id} does not exist")
    if proposal["status"] != "pending":
        raise ValueError(f"proposal {proposal_id} is not pending (status={proposal['status']!r})")

    conn.execute(
        "UPDATE project_proposals SET status = 'rejected', reviewed_note = ?, "
        "reviewed_at = datetime('now') WHERE id = ?",
        (reviewed_note, proposal_id),
    )
    conn.commit()


def list_projects(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """One summary row per project that has at least one approved version
    (a project with zero versions — impossible via approve_project_proposal's
    own flow, since version 1 is created in the same transaction as the
    project row — is excluded defensively rather than crashing on a NULL
    join)."""
    rows = conn.execute(
        """
        SELECT p.id, p.name, p.rera_reference, p.builder, p.address, p.created_at,
               v.version_number AS latest_version,
               v.facade_bearing_deg AS latest_facade_bearing_deg,
               v.created_at AS latest_version_created_at
        FROM projects p
        JOIN project_versions v ON v.project_id = p.id
        WHERE v.version_number = (
            SELECT MAX(version_number) FROM project_versions WHERE project_id = p.id
        )
        ORDER BY p.id
        """
    ).fetchall()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "rera_reference": r["rera_reference"],
            "builder": r["builder"],
            "address": r["address"],
            "created_at": r["created_at"],
            "latest_version": r["latest_version"],
            "latest_facade_bearing_deg": r["latest_facade_bearing_deg"],
            "latest_version_created_at": r["latest_version_created_at"],
        }
        for r in rows
    ]


def get_project(conn: sqlite3.Connection, project_id: int) -> dict[str, Any] | None:
    """Full project record with ALL versions (oldest first), or None if missing."""
    project_row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project_row is None:
        return None

    version_rows = conn.execute(
        "SELECT * FROM project_versions WHERE project_id = ? ORDER BY version_number",
        (project_id,),
    ).fetchall()

    return {
        "id": project_row["id"],
        "name": project_row["name"],
        "rera_reference": project_row["rera_reference"],
        "builder": project_row["builder"],
        "address": project_row["address"],
        "created_at": project_row["created_at"],
        "versions": [_project_version_dict(v) for v in version_rows],
    }


def get_project_version(
    conn: sqlite3.Connection, project_id: int, version_number: int
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM project_versions WHERE project_id = ? AND version_number = ?",
        (project_id, version_number),
    ).fetchone()
    return _project_version_dict(row) if row is not None else None


def _project_version_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "version_number": row["version_number"],
        "boundary": json.loads(row["boundary_json"]) if row["boundary_json"] else None,
        "facade_bearing_deg": row["facade_bearing_deg"],
        "base_rooms": json.loads(row["base_rooms_json"]) if row["base_rooms_json"] else None,
        "note": row["note"],
        "source_proposal_id": row["source_proposal_id"],
        "created_at": row["created_at"],
    }


def _proposal_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "proposed_name": row["proposed_name"],
        "proposed_rera_reference": row["proposed_rera_reference"],
        "proposed_builder": row["proposed_builder"],
        "proposed_address": row["proposed_address"],
        "proposed_boundary": (
            json.loads(row["proposed_boundary_json"]) if row["proposed_boundary_json"] else None
        ),
        "proposed_facade_bearing_deg": row["proposed_facade_bearing_deg"],
        "proposed_base_rooms": (
            json.loads(row["proposed_base_rooms_json"]) if row["proposed_base_rooms_json"] else None
        ),
        "submitted_by": row["submitted_by"],
        "note": row["note"],
        "status": row["status"],
        "reviewed_note": row["reviewed_note"],
        "created_at": row["created_at"],
        "reviewed_at": row["reviewed_at"],
    }
