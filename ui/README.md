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
