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

## Placement suggestions

Alongside the zone/adjacency audit, a room gets a concrete furniture-
placement suggestion (exact position + rotation, not just "this zone is
wrong") if it both has a supported room type AND the caller supplies its
polygon. This wires `genesis/engine/solver.py`'s existing constructive
solver into the UI via a thin bridge, `genesis/engine/suggestions.py` —
neither file adds any new placement logic of its own.

- **Supported types**: MasterBedroom / GuestBedroom / ChildrenBedroom (bed
  placement), Kitchen (stove placement), LivingRoom (recommended
  heavy-furniture wall) — this is `solver.py`'s own deliberately narrow
  scope, not something extended here. Any other room type, or a room
  without a polygon, is silently skipped (not an error — most rooms just
  don't have a placement solver).
- **Inputs**: each room row in the UI has an optional polygon field (JSON
  `[[x,y],...]` in feet) and, for bed/stove rooms, optional width/depth
  overrides (defaults: queen bed 6x6.5 ft, twin bed 4x6.5 ft for
  ChildrenBedroom, stove 2x2 ft — placeholders, not validated against a real
  furniture catalog). A plot-level "facade bearing" field rotates local
  polygon coordinates onto true north for the suggestion, same convention as
  `zone_geometry.py`'s `north_offset_deg` — separate from that module's own
  Brahmasthan zone assignment, not integrated with it in this pass.
- **Output**: `POST /audit`, `POST /flats`, and `POST /flats/{id}/versions`
  all return a `"suggestions"` list alongside the usual audit fields. Each
  entry is either `{"room", "placements": [...]}` (solver.py's own output,
  unmodified — position, rotation, `satisfies_rule`, `compromise`,
  `compromise_note`) or `{"room", "suggestion_error": "...", "error_type":
  "..."}`. Two distinct failure modes are deliberately NOT conflated:
  `error_type: "invalid_geometry"` means the polygon itself is malformed
  (wrong type, too few vertices, non-numeric coordinates — this endpoint has
  no upstream schema validation, so garbage input off the wire must be
  assumed possible, not just clean requests from this page's own JS);
  `error_type: "solver_error"` means the polygon is well-formed but the
  furniture genuinely does not fit anywhere in that room (a real geometric
  failure, not a Vastu compromise — see `solver.py`'s docstring). Either
  way this is a per-room error, never a 500 — one malformed or too-small
  room does not take down the zone/adjacency audit or any other room's
  suggestion in the same request (`genesis/engine/suggestions.py`).
- `facade_bearing_deg` and any `furniture_dimensions` overrides are saved
  as part of a flat's version input, so reloading a saved flat restores its
  polygons and suggestion settings exactly as entered.

## Shape diagnosis (hollow-centre + missing zones)

The Plot fieldset has an optional **flat boundary polygon** field (JSON
`[[x,y],...]` in feet, same convention as room polygons). When supplied, the
server runs `zone_geometry.diagnose_shape()` (true centroid vs. bounding-box
centre, hollow/external-centre check, cut/missing compass zones) and
`vastu_audit.audit_shape_defects()` merges the results into the same scored
violation list, so a hollow centre or a cut NE/SW corner lowers the
compliance score exactly like any other major/minor violation. The result
also carries a `shape_diagnosis` block, rendered as a standalone panel above
the violation list. Leaving the boundary field blank skips this entirely —
the rest of the audit is unaffected either way.

## Ritual/activation protocol (opt-in)

A checkbox ("Include traditional ritual/activation protocol with remedies")
sends `include_ritual_protocol: true` in the request. When set, any
directional violation (hollow-centre, missing-zone, Brahmasthan obstruction)
gets a `ritual` block attached — the classical presiding deity, mantra, and
Prana Pratishtha activation sequence for that direction
(`genesis/engine/ritual_protocol.py`) — rendered as a collapsed `<details>`
dropdown under the violation. **Off by default.** This is religious/cultural
content, not a validated intervention; every ritual block carries its own
disclaimer, and `audit_layout()` itself never depends on or imports this
module — the server only calls it when the caller explicitly opts in.
