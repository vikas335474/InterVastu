# Vastu Audit Engine — Local Test UI

A minimal local web UI for manually testing the existing Vastu audit engine
(`genesis/engine/vastu_audit.py`). No database, no auth, no build step —
just a thin FastAPI wrapper and a plain HTML/JS page.

## Run

From the repo root:

```bash
pip install -r requirements.txt
uvicorn ui.server:app --reload
```

Then open:

```
http://127.0.0.1:8000/
```

## Notes

- This UI adds no audit logic of its own — `/audit` calls the engine's
  existing `audit_layout()` directly.
- Room types, zones, and adjacency flags shown in the dropdowns are read
  from `genesis/engine/vastu_rule_schema.json` at server startup, not
  hardcoded.
- The compliance score uses placeholder severity weights defined in the
  engine (major=10, minor=3) — not schema-derived, not consultant-validated.

## Persistence

Saved flats and their audit history live in a single SQLite file
(`ui/vastu_ui.db` by default, gitignored — override the path with the
`VASTU_UI_DB_PATH` env var, e.g. for tests or a deploy config).

- **`storage.py`** owns the schema: a `flats` table (label + free-text
  `owner` string — there is no authentication, `owner` is just a label to
  tell whose flat is whose among a small set of known/trusted people) and a
  `flat_versions` table (one row per save). Editing a flat's rooms/plot and
  saving again creates a **new version** rather than overwriting the old
  one, so every past run stays available — that's what makes "tweak it a
  little and check" work: load a flat, edit it, save, and the previous
  version's result is still sitting right there for comparison.
- **Endpoints**: `POST /flats` (create + first version), `GET /flats`
  (list, latest score per flat), `GET /flats/{id}` (full version history),
  `POST /flats/{id}/versions` (save an edit as a new version), `GET
  /flats/{id}/versions/{n}` (one specific version), `DELETE /flats/{id}`.
  The original stateless `POST /audit` endpoint is unchanged and saves
  nothing, for quick one-off checks.
- The web page's "Saved flats" panel lists everything saved so far and can
  load any flat's latest version back into the form for editing; saving
  again asks whether to create a brand-new flat or add a new version to the
  one you loaded.
- A single SQLite file is a deliberate choice for the current scale (a
  handful of known users). It is not a multi-tenant production database —
  revisit if this grows into a public, many-users product.
