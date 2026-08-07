# InterVastu

See `docs/build_plan.md` for the repo layout and phase status.

## `genesis/engine/orientation.py` — facade-orientation detection

Determines a building's true-north facade bearing from its footprint
geometry, as an alternative to relying on a phone's magnetic compass
(measured to carry 15-20 degree real-world error from indoor magnetic
interference).

**This module produces an ESTIMATE requiring human confirmation.** The
automated path (`estimate_facade_bearing` / `estimate_facade_bearing_from_footprint`)
derives a bearing from the footprint's minimum rotated bounding rectangle,
which assumes an approximately rectangular building. For irregular,
multi-wing, or podium-style buildings, the detected long edge may not
correspond to the actual unit's facade at all. Every automated result is
returned with `"source": "footprint_estimate"` and a `reliability_note`
spelling this out — **it must be shown to a human for confirmation before
being used in a paid report, and is not a substitute for the manual
override path in production use.**

The manual override path (`manual_facade_bearing`) accepts a
human-confirmed bearing directly (e.g. from a UI where the user rotates
their floor plan onto a satellite image) and returns it in the same output
shape, tagged `"source": "manual"`, with no dependency on footprint lookup.

This module does not fetch footprints from a hardcoded hosting setup — the
Microsoft Global ML Building Footprints and OSM Overpass lookups both take
an injected query function, so the actual data-source wiring (S3 path,
hosted tile server, Overpass endpoint, etc.) is supplied by the caller.

Every result also carries a `north_offset_deg` value in `zone_geometry.py`'s
own convention (true bearing of the floor plan's `+y` axis), currently a
plain alias of `facade_bearing_deg` under the assumption that plan-up faces
the detected/provided facade — see the module docstring for the caveat.
Integration with the deterministic zone-assignment layer (`zone_geometry.py`)
is intentionally out of scope here and happens in a later session, once both
modules are independently tested.

**Cost note for the later visual confirmation step:** Microsoft Global ML
Building Footprints and OSM Overpass are both free data sources. The only
thing that later "is this your building?" human-confirmation UI will need
that isn't free-by-default is map **tiles** to render underneath the
footprint outline (e.g. Google Maps or Mapbox) — both have usable free
tiers, so this doesn't block anything now, but it's a real dependency to
account for when that UI gets built.

## `genesis/engine/zone_geometry.py` — deterministic zone-assignment layer

Assigns each room in a flat to one of the 16 Vastu compass sectors relative
to the flat's true geometric centre (Brahmasthan), computed as the
occupied-area polygon centroid rather than a bounding-box centre. See the
module docstring for the full coordinate/bearing conventions.

### `diagnose_shape()` — footprint-level shape defects (dual-centre + missing zones)

A separate, footprint-level diagnostic (not per-room) that catches the two
classic irregular-plan defects a bounding box hides:

* **Hollow / external centre.** For a U-shaped (or strongly concave) flat the
  true area centroid — the Brahmasthan — can fall in open space *outside the
  built footprint entirely*. This is checked with a direct point-in-polygon
  test, **independently of the centroid-vs-bounding-box offset magnitude**: a
  footprint can have a *small* offset yet still place its centroid outside
  itself (a U-shape does exactly this), so an offset-size check alone would
  miss it. The dual-centre comparison (true centroid vs. bounding-box centre)
  is also reported, with a strongly off-centre mass distribution flagged
  separately as `high_center_offset` (informational, not itself a defect).
* **Cut / missing zones.** The bounding box minus the actual footprint is the
  set of "cut corners"; each region above a noise threshold is labelled by the
  compass octant it sits in (NE/SW/SE/NW/…), which is how the traditional
  "missing NE / missing SW" remedies are indexed.

This is deterministic geometry only. The rule/severity/remedy layer lives in
`vastu_audit.audit_shape_defects()` (wired into `audit_layout()` via an
optional `shape_diagnosis=` argument, additive and backward-compatible). The
two thresholds `diagnose_shape` uses (centre-offset fraction, missing-zone
area fraction) are documented **product choices, not settled Vastu constants**,
and the missing-zone severity map in `vastu_audit` is flagged as pending the
same licensed-consultant sign-off as the rest of the schema. Run the end-to-end
demo (`python3 genesis/engine/run_geometry.py`) to see it on the Unit 12
L-shaped fixture, where it reports a cut NE zone as a scored major defect.

## `genesis/engine/geometry_engine.py` — rotation primitive + classical pada-grid overlay

Two additions on top of `zone_geometry.py`, both deterministic geometry only:

* **Rotation.** `rotate_point` / `rotate_polygon` are a general-purpose 2D
  affine rotation about an arbitrary origin. `zone_geometry.py` already
  corrects for `north_offset_deg`, but by rotating the *bearing
  measurement*, not the vertices — enough for "which sector is this room
  in", but not for overlaying an axis-aligned grid, which needs the
  geometry itself rotated into a true-north frame first. `align_to_true_north`
  is that compass-aware wrapper; the sign convention (compass
  "clockwise-from-north" vs. standard math "counter-clockwise-from-+x") is
  easy to get backwards, so it's asserted directly against
  `zone_geometry.bearing_deg` in the test suite rather than only derived by
  hand — see `tests/test_geometry_engine.py`.
* **`pada_grid()`** overlays a classical **square** Vastu Purusha Mandala
  grid (default 9x9 = 81 pada, the "Paramasayika" mandala most commonly
  cited for residential plots; `MANDUKA_ORDER` = 8x8/64 pada is the other
  commonly cited alternative) on the true-north-aligned flat, and reports
  exact-intersection occupancy fractions per cell for the footprint and
  each room. It deliberately does **not** implement a "32 equal angular
  segments radiating from the centroid" construct some AI-generated Vastu
  specs describe as "32-Pada" — the classical padas are a square grid
  subdivision, not a radial slicing, and `zone_geometry.py`'s existing
  16-sector scheme already owns angular zone logic. The grid is laid over the
  rotated boundary's **bounding box**, which is exact for a rectangular flat
  but not for an irregular one (on the Unit 12 L-shape, 6 of 81 cells fall
  entirely outside the footprint and 32 more are partially cut). That is a
  documented **product choice**, not a settled Vastu constant — classically
  the mandala is inscribed on the plot, and its application to irregular
  footprints is genuinely disputed among practitioners, so the module picks
  the unambiguous construction and exposes `boundary_occupancy_fraction` (0.0
  for a cell wholly outside the footprint) as the lever for callers who want
  to filter or weight on it. `pada_grid()` also
  assigns **no deity/interpretation** to any cell — per-pada devata mapping
  was already explicitly scoped out of this codebase pending dedicated
  consultant sourcing (see `ritual_protocol.py`'s module docstring), and
  this module doesn't revisit that call; its output shape just leaves room
  for a future consultant-sourced map to be attached per cell later. Run
  `python3 genesis/engine/run_geometry.py` to see a pada-occupancy summary
  on the Unit 12 fixture, printed after the existing geometry/shape reports.

### `pada_devata_45()` — EXPERIMENTAL 45-devata overlay (second, opt-in method)

A second method, coexisting with `pada_grid()` rather than replacing it —
calling it never changes `pada_grid()`'s own output. It reuses the exact
same 9x9 grid and attaches a `"devata"` name to each cell for the classical
"45-devata" scheme (32 peripheral + 13 core padas of the 81-pada grid).

**Only 9 of the 81 cells are named**: the 4 corner + 4 side-midpoint border
anchors and the inner 3x3 Brahmasthan, reusing this project's existing
`ritual_protocol.DIRECTION_DEITIES` names. The other 72 cells are returned
as `devata=None, needs_verification=True` rather than a guessed name —
published Vastu texts disagree on the exact 32-border-name roster and the
13-way interior grouping, and this module does not invent a resolution to
that disagreement. An `overrides={(row, col): name}` parameter lets a
caller fill in the rest after checking them against a primary source or a
consultant; overrides are trusted as-is and can also correct a built-in
anchor name. Every result carries a `disclaimer` field spelling this out —
see `geometry_engine.py`'s "UNVERIFIED — READ BEFORE USING" block for the
full reasoning. Run `python3 genesis/engine/run_geometry.py` to see it on
the Unit 12 fixture, printed as its own clearly-labelled section.

### `entrance_pada()` — locating a door on the 32-pada perimeter ring

`vastu_rule_schema.json` evaluates `MainEntrance` at 16-zone resolution only
(preferred N/NE/E, forbidden S). Practising consultants evaluate the main
door against the **32 perimeter padas**, since auspiciousness varies pada by
pada *within* an otherwise-favourable direction. The 32 is not a separate
construct: a 9x9 grid has 81 padas, of which the border ring is exactly
81 − 7×7 = 32 — the same ring `pada_grid()` already computes.

`entrance_pada()` locates a door opening on that ring by **boundary
intersection**, not centroid bearing. A door is a segment on a perimeter
wall, so the classical question is which pada the opening falls in — a
different question from "what bearing is this door marker's centroid from
the plot centre", which is what the audit path answers today. Openings that
straddle two padas report both with their length shares rather than being
rounded to one.

The difference is not academic. On the Unit 12 fixture, the existing 16-zone
path assigns the entrance `ESE` at **`low` confidence, 0.58° from a sector
edge** — a small tracing error flips the zone. `entrance_pada()` puts the
same door unambiguously at ring index 15 (East side) with 100% overlap and no
straddle.

**Ratings are not included and are not guessed.** Per-pada auspiciousness
varies across classical texts and regional traditions; supplying a table from
general knowledge is precisely the fabricated precision this project refuses
elsewhere. Ratings are injected via `ratings={ring_index: rating}` — the same
pattern as `pada_devata_45(overrides=…)` — and unrated padas report
`rating=None, needs_verification=True`. Every result carries
`ENTRANCE_PADA_DISCLAIMER`. When a consultant supplies ratings, no code
changes.

## `genesis/engine/ritual_protocol.py` — OPTIONAL ritual/activation content

An **opt-in, fully decoupled** layer that pairs a directional physical remedy
with its culturally-authentic counterpart: the classical Vastu Purusha Mandala
presiding deity and mantra for each of the 8 octants + the Brahmasthan (e.g.
Ishana/Shiva for NE, Agni for SE, Brahma for the centre), plus the traditional
Prana Pratishtha activation sequence, timing, and repetition guidance.

Unlike invented "floor-band" scoring (which this project **refused** to add),
this content reflects a real tradition rather than fabricated pseudo-precision
— but that is a statement about authenticity, **not efficacy**: it is religious
practice, no outcome is claimed, and every returned block carries an explicit
disclaimer. It is deliberately **not** wired into `audit_layout` (that never
imports it); `enrich_defects_with_ritual()` attaches content only to defects
carrying a resolvable `direction` tag, and the UI exposes it behind an opt-in
`include_ritual_protocol` flag that is **off by default**. Enabling it in a
shipped product is a product + legal + cultural decision, not an engineering
default — see the module docstring for the full rationale.

## `scene/` — deterministic 3D scene assembly + depth-map export

Takes room polygons (in `zone_geometry.py`'s coordinate convention) plus
`solver.py`'s furniture-placement output and builds an exact Three.js scene:
box-extruded walls (with door/window openings cut out), floor/ceiling
planes, and placeholder furniture boxes sized to real-world dimensions
(`src/furniture_catalog.ts`). This is the deterministic geometry layer that
a later AI styling step only re-textures — it never moves anything, so
position/rotation here are treated as final.

Rendering (`src/export_views.ts`) is a headless Playwright browser doing a
real WebGL render, not a server-side GL library — the same renderer/scene
code will be reusable for an interactive in-browser viewer later. For each
room it exports one 3/4-angle eye-level view as a color PNG plus a true
single-channel grayscale depth-map PNG (pixel value linear in
camera-forward distance, via a small custom shader — `THREE.MeshDepthMaterial`'s
default packing is nonlinear NDC depth and compresses almost the entire
visible range into a handful of the 256 gray levels at ordinary near/far
ratios, so it isn't used here).

```
cd scene && npm install
npx tsx src/export_views.ts <scene_input.json> <output_dir>
npm test
```

Furniture placeholders are simple boxes, not licensed 3D assets — sourcing
real furniture meshes is a separate follow-up task and nothing here is
blocked on it.

## `render_adapter/` — vendor-agnostic AI render-styling interface

Defines `StylingProvider` (`src/types.ts`) — a single `styleImage()` method
that any AI render-styling vendor will implement. **No real vendor is wired
in yet**: a Phase-0 bake-off (Replicate, PromeAI, etc.) is still pending, so
this package has zero runtime dependencies and makes zero network calls.

`MockStylingProvider` (`src/providers/mock_provider.ts`) stands in for a
real vendor during development: it overlays a flat color wash plus a label
(stamped with a tiny embedded bitmap font, `src/bitmap_font.ts`) onto the
input depth map and saves that as the "styled" output. It's deliberately
ugly — its only job is to exercise the rest of the pipeline (batching, cost
tracking, drift-checking) without an API key or inference spend.

`checkGeometryDrift()` (`src/drift_check.ts`) is a clearly-labeled **stub**
that always returns a fixed placeholder result. Its docstring spells out
the real implementation: re-run a monocular depth-estimation model (e.g. an
open MiDaS-family model) on the styled output and compare it against the
original depth map to catch a vendor moving or inventing geometry. That's
deferred until the vendor spike picks a provider, since which failure modes
are worth checking depends on the vendor.

```
cd render_adapter && npm install
npx tsx src/cli.ts [depthMapPath] [stylePrompt] [outputDir]   # depthMapPath defaults to a synthetic fixture
npm test
```

Tested end to end against a real depth map from `scene/`'s
`export_views.ts` output, not just synthetic fixtures.
