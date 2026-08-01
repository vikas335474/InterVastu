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

Integration with the deterministic zone-assignment layer (`zone_geometry.py`)
is intentionally out of scope here and happens in a later session, once both
modules are independently tested.

## `genesis/engine/zone_geometry.py` — deterministic zone-assignment layer

Assigns each room in a flat to one of the 16 Vastu compass sectors relative
to the flat's true geometric centre (Brahmasthan), computed as the
occupied-area polygon centroid rather than a bounding-box centre. See the
module docstring for the full coordinate/bearing conventions.

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
