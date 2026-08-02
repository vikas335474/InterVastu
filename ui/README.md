# InterVastu — Local Test UI

A local web UI for manually testing the existing Vastu audit engine
(`genesis/engine/vastu_audit.py`), with real user accounts and per-user
saved flats. No build step — a thin FastAPI wrapper, a small SQLite
persistence layer, and a plain HTML/JS page.

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

Register an account (username + password) on first visit — everything
past the login screen requires being logged in, except the stateless
one-off `/audit` endpoint.

Cookies are marked `Secure` (HTTPS-only) by default. Running locally over
plain `http://127.0.0.1` needs `VASTU_UI_INSECURE_COOKIES=1` set before
starting the server, or the session cookie won't be stored by the browser:

```bash
VASTU_UI_INSECURE_COOKIES=1 uvicorn ui.server:app --reload
```

## Deploying (Render, free tier)

`render.yaml` at the repo root is a Render Blueprint for this app: pip
install, then `uvicorn ui.server:app --host 0.0.0.0 --port $PORT`, health
check on `/`. To deploy:

1. Push this repo to GitHub (already done if you're reading this on a
   branch/PR).
2. In the Render dashboard: **New > Blueprint**, point it at this repo.
   Render reads `render.yaml` and provisions the service on the free plan
   automatically.
3. Once live, open the assigned `https://<service>.onrender.com` URL —
   cookies are already marked `Secure`, which works out of the box since
   Render serves over HTTPS (no `VASTU_UI_INSECURE_COOKIES` needed).

**Read before relying on this for anything but trying the app out:**
Render's **free** web-service plan has no persistent disk — the SQLite
file (`ui/vastu_ui.db`) lives on the container's local, ephemeral
filesystem. It survives while the instance stays up, but is wiped on every
redeploy, and free instances also spin down after ~15 minutes idle and
spin back up on the next request — data does not reliably survive that
cycle either. In practice: registered accounts and saved flats can
disappear without warning. That's an acceptable tradeoff for kicking the
tyres on a free tier, but not for anything you need to keep. Two ways
around it if that matters:

- Upgrade to a Render plan with a persistent disk, mount it, and point
  `VASTU_UI_DB_PATH` at a file inside it.
- Swap SQLite for a hosted database (Render's own free Postgres, or
  similar) — `storage.py` is the only place that would need to change; the
  rest of the app talks to it through plain function calls, not raw SQL
  scattered around.

Neither is done here — this Blueprint deploys the app as-is, ephemeral
storage and all.

## Notes

- This UI adds no audit logic of its own — `/audit` calls the engine's
  existing `audit_layout()` directly.
- Room types, zones, and adjacency flags shown in the dropdowns are read
  from `genesis/engine/vastu_rule_schema.json` at server startup, not
  hardcoded.
- The compliance score uses placeholder severity weights defined in the
  engine (major=10, minor=3) — not schema-derived, not consultant-validated.

## Auth

Real accounts, not a trust-based label. See `auth.py` for the crypto/session
rationale and `storage.py` for the schema.

- **Passwords** are bcrypt-hashed (`auth.hash_password`/`verify_password`);
  this codebase never stores or logs a plaintext password. A password must
  be at least 8 characters; a username is 3-32 characters of
  letters/numbers/`_`/`.`/`-`.
- **Sessions** are server-side: `POST /auth/register` or `POST /auth/login`
  creates a random token (`storage.sessions`), set as an httponly, SameSite
  cookie. `POST /auth/logout` deletes that row, so logout immediately
  revokes access — unlike a stateless/signed token (e.g. JWT), which would
  stay valid until it expires no matter what the server does.
- **Endpoints**: `POST /auth/register`, `POST /auth/login`, `POST
  /auth/logout`, `GET /auth/me` (current user, or 401).
- Every `/flats*` endpoint requires a valid session (`Depends(get_current_user)`
  in `server.py`) and is scoped to that session's user — `storage.py`'s flat
  functions filter by `user_id` directly in SQL, so "flat doesn't exist" and
  "flat belongs to someone else" are indistinguishable to the caller (both
  come back as a 404), rather than letting a wrong-owner request confirm
  another user's flat id exists.

## Persistence

Saved flats and their audit history live in a single SQLite file
(`ui/vastu_ui.db` by default, gitignored — override the path with the
`VASTU_UI_DB_PATH` env var, e.g. for tests or a deploy config).

- **`storage.py`** owns the schema: `users` (username, bcrypt hash),
  `sessions` (token -> user), `flats` (label, owned by `user_id`), and
  `flat_versions` (one row per save). Editing a flat's rooms/plot and
  saving again creates a **new version** rather than overwriting the old
  one, so every past run stays available — that's what makes "tweak it a
  little and check" work: load a flat, edit it, save, and the previous
  version's result is still sitting right there for comparison.
- **Endpoints**: `POST /flats` (create + first version), `GET /flats`
  (list, latest score per flat, scoped to the logged-in user), `GET
  /flats/{id}` (full version history), `POST /flats/{id}/versions` (save an
  edit as a new version), `GET /flats/{id}/versions/{n}` (one specific
  version), `DELETE /flats/{id}`. The stateless `POST /audit` endpoint is
  unchanged, saves nothing, and needs no login, for quick one-off checks.
- The web page's "Saved flats" panel lists everything the logged-in user has
  saved and can load any flat's latest version back into the form for
  editing; saving again asks whether to create a brand-new flat or add a new
  version to the one you loaded.
- A single SQLite file is a deliberate choice for the current scale (a
  handful of registered users). It is not built for a public, many-tenant
  product's request volume — revisit if this grows into that.
- **Upgrading an existing dev database**: a file created before accounts
  existed (`flats.owner` as free text, no `users`/`sessions` tables) is
  rejected with a clear `RuntimeError` on startup rather than silently
  half-working — see `storage._reject_legacy_pre_auth_schema`'s docstring.
  Delete the old file (it's a local test artifact, gitignored) to get a
  fresh one, or hand-migrate it per that error message.

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

## Floor plan tracing tool (photo upload + click-to-trace)

The "Trace your floor plan" fieldset (shown first, above Plot/Rooms) is a
guided, click-to-trace aid for building the boundary and room polygons
without hand-typing coordinate JSON:

1. Optionally upload a floor-plan photo/scan (any raster image format —
   PDFs must be exported/screenshotted as an image first, no PDF rendering
   is included). Without an upload, tracing happens directly on a plain grid
   (default 1 square = 1 ft, adjustable) instead.
2. **Photo mode: calibration is recommended, not required.** Click two
   points a known real-world distance apart (e.g. a door) and type that
   distance in feet — but tracing is never blocked on this. Skipping it uses
   image pixels as a placeholder unit instead of refusing outright, because
   most of the Vastu geometry (hollow/external-centre check, missing-zone
   direction, room-to-centre compass zones) only depends on angles and area
   *ratios* — it comes out correct either way. Only absolute measurements
   (sq ft, furniture-fit suggestions) need the real calibration, and a clear
   badge/banner says so whenever a trace is uncalibrated. Calibrating at any
   point — including after tracing — rescales everything already traced to
   match (`recomputeAllFeetFromPx`, driven off each shape's permanently
   retained pixel points), so nothing ends up mixing units within a session.
3. Click around the flat's outer wall, corner by corner, then "Finish shape"
   to commit the boundary — this writes straight into the `#plot-boundary`
   field above.
4. Pick a room type, click around its walls, "Finish shape" — this adds a
   new row to the Rooms list below with that room's polygon pre-filled (you
   still pick its compass zone there; tracing does not compute the zone).
   Repeat for each room.
5. Drag the compass needle to set which way is North on the plan; this
   writes into the existing "Facade bearing" field, using the exact same
   0=N/clockwise convention `zone_geometry.py` uses internally.

**What this deliberately is NOT**: there is no automatic wall/room detection
(computer vision) anywhere in this tool. Every point comes from a human
click; the tool only measures distances and angles from those clicks and
converts pixels to feet via the calibration step. This is a conscious
design choice — automatic CV extraction from a photo is failure-prone
(scale, wall detection, OCR) and a silently-wrong extraction would corrupt
every downstream Vastu calculation without the user ever knowing. The
click-to-trace approach keeps a human validating every coordinate while
still avoiding hand-typed JSON.

All of this is a pure client-side convenience layer over fields that already
existed and already worked without it (`#plot-boundary`, each room's
`.room-polygon` textarea, `#facade-bearing`) — no server or engine change was
needed to add it, and the underlying JSON fields stay visible/editable so
nothing is hidden from the person doing the audit.

## Building/project sharing (reduces burden on individual flat owners)

Most retail flat owners cannot reliably trace their own flat from scratch.
`storage.py`'s `projects` / `project_versions` / `project_proposals` tables
let one building's confirmed geometry (boundary, facade bearing, a
base/typical room layout — sourced from a RERA filing, builder blueprint, or
a resident's trace) be captured once and reused by every flat owner in that
project.

**Flow**: anyone can *propose* a new project or a correction to an existing
one (`POST /projects/proposals`, no auth) — this does nothing on its own.
An admin reviews it at `/admin` and approves or rejects
(`POST /projects/proposals/{id}/approve|reject`). Only on approval does the
data become the project's new live version, visible to everyone via
`GET /projects` / `GET /projects/{id}` (public, no token). On the main page,
a "Your building / project" section lets a user pick a project and
pre-fill their flat's boundary/facade-bearing/rooms from it, or submit their
own traced data as a suggestion for the next owner.

**Why the admin gate**: unlike a flat (which only affects its own owner), a
project's data is shared across many unrelated flat owners' audits — a bad
edit would silently affect all of them. So writing a project's LIVE version
is possible only via `approve_project_proposal`, gated by
`require_admin()` in `server.py`, a single shared-secret check:

```bash
export VASTU_ADMIN_TOKEN=<a-token-only-you-know>
```

**Fails closed**: if `VASTU_ADMIN_TOKEN` is unset on the server, every
admin-only endpoint refuses with 503 rather than silently accepting any (or
no) token — an unconfigured secret must never look like "no auth required."
This is one shared-secret gate for "one or a few trusted admins," not a
user-account system — proportionate to this app's existing no-auth,
small-trusted-circle scale (see the top of this file); revisit if that scale
assumption stops holding.

Visit `/admin` (paste the token once, it's kept in that browser's
`localStorage`) to see pending proposals, expand their proposed boundary/
room JSON, and approve or reject with an optional note. Rejected proposals
are kept (not deleted) so what was suggested — and why it wasn't accepted —
stays on record.

**Deliberately simple for v1**: approving accepts a proposal exactly as
submitted; there's no edit-then-approve step. An admin who wants different
data submits their own corrective proposal and approves that instead — this
keeps a single code path for "how project data changes" (every live version
traces back to exactly one proposal, `source_proposal_id`), which is both
simpler and more auditable than having two ways to write the same table.

**What this does NOT do**: no automated RERA scraping (there is no unified
API across India's 30+ state RERA portals — most are per-state PDF filings,
not structured data or floor-plan APIs). The realistic path for RERA data is
a human reading the filing and either uploading its layout page as a photo
into the tracing tool, or typing the reference into the "RERA reference"
field as a citation — both already supported, no separate ingestion pipeline
needed.

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
