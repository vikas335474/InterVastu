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
"""


def open_db(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open (creating if necessary) the SQLite file at ``db_path`` and
    ensure the schema exists. Returns a connection with row access by
    column name (``sqlite3.Row``) and foreign-key enforcement turned on.
    """
    conn = sqlite3.connect(db_path)
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
