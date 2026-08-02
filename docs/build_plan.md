# InterVastu build plan

```
genesis/
  engine/                    # Python — the moat
    schema/                  # vastu_rule_schema.json (consultant-signed, when ready)
    zone_geometry.py          # Phase 1b
    audit.py                  # Phase 1a (extends existing vastu_audit.py)
    orientation.py             # footprint fetch + bearing calc + manual override
    solver.py                  # Phase 1c furniture placement
    fixtures/                  # test flats, incl. Unit 12 L-shape as permanent regression fixture
    tests/
scene/                        # Node/TS — deterministic 3D + depth maps (repo root, not under genesis/)
  src/build_scene.ts           # room polygons + solver output -> Three.js scene (browser-safe, no Node built-ins)
  src/scene_cli.ts              # CLI: build_scene + save reusable scene.json (THREE.ObjectLoader format)
  src/export_views.ts           # CLI: whole pipeline -> per-room color PNG + grayscale depth-map PNG
  src/browser/render_entry.ts   # bundled (esbuild) into the headless Playwright page; does the actual WebGL render
  src/coords.ts, furniture_catalog.ts, png_encoder.ts, types.ts
  tests/
render_adapter/               # Node — vendor-agnostic styling interface (repo root)
  src/types.ts                  # StylingProvider interface (no vendor wired in yet)
  src/providers/mock_provider.ts # MockStylingProvider — no network calls, no vendor deps
  src/drift_check.ts            # checkGeometryDrift — STUB pending vendor spike
  src/png.ts, bitmap_font.ts, cli.ts
  tests/
docs/
  build_plan.md                # this file
```

## Status

| Path | Status |
| --- | --- |
| `genesis/engine/zone_geometry.py` | Done (Phase 1b) — deterministic Brahmasthan + 16-sector zone assignment, plus `diagnose_shape()`: footprint-level dual-centre (hollow / high-offset) check + cut/missing-zone detection (bounding box minus footprint, labelled by octant). Thresholds are documented product choices, not Vastu constants. 25 tests |
| `genesis/engine/orientation.py` | Done — footprint lookup (MS Buildings + OSM fallback) + minimum-rotated-rectangle bearing estimate + manual override, 15 tests |
| `genesis/engine/vastu_audit.py` | Done (Phase 1a) — room/plot zone-and-adjacency audit (`audit_room`/`audit_layout`) plus an object-placement extension (`audit_object_placement`/`audit_layout_with_objects`) covering sleeping/seat/stove/desk/furniture/seating direction rules, plus `audit_shape_defects()` which turns `zone_geometry.diagnose_shape()` output (hollow-centre + missing-zone) into scored/informational audit entries with traditional remedies (wired into `audit_layout` via an optional `shape_diagnosis=`, additive/backward-compatible), 16 + 9 tests. `OBJECT_PLACEMENT_RULES`, the missing-zone severity map, and the shape-defect remedy text are this module's own interpretation — flagged in-code as pending consultant/legal sign-off, same as the schema itself |
| `genesis/engine/ritual_protocol.py` | Done (OPT-IN, decoupled) — authentic directional-lokapala deity/mantra map (8 octants + Brahmasthan) + Prana Pratishtha activation sequence, timing, and an always-attached efficacy disclaimer. `enrich_defects_with_ritual` attaches content only to defects carrying a resolvable `direction` tag; purely additive, never touches severity/score. Deliberately NOT wired into `audit_layout` — enabling it in a shipped product is a product/legal/cultural decision (see module docstring). UI exposes it behind an opt-in `include_ritual_protocol` flag, off by default. 9 tests |
| `genesis/engine/vastu_rule_schema.json` | v0.2.0 draft, in place — still explicitly "pending sign-off from a licensed Vastu consultant" per its own `_meta.status` |
| `genesis/engine/solver.py` | Done (Phase 1c) — constraint-based placement for bed (MasterBedroom/GuestBedroom/ChildrenBedroom), stove (Kitchen), and heavy-furniture wall recommendation (LivingRoom) only; always returns a least-bad placement with a `compromise`/`compromise_note` flag rather than silently failing or violating a rule, 13 tests. Does not attempt general room layout or any other room type |
| `genesis/engine/fixtures/` | Not started as a shared directory for the hand-built audit fixtures — the Unit 12 L-shape regression fixture still lives inline in `genesis/engine/tests/test_zone_geometry.py`; extract here if a future task needs to share it across modules. `fixtures/houseexpo_sample/` (added) is a separate, already-shared exception: 40 real floor-plan boundaries sampled from the external HouseExpo dataset (MIT licensed), used only as a structural stress-test corpus for `zone_geometry.py` — see its own `README.md` for provenance/selection and `genesis/engine/tests/test_houseexpo_regression.py` for what is/isn't asserted (no Vastu ground truth exists for this data, so only structural invariants are checked, not Vastu correctness) |
| `scene/` | Done (Phase 2, initial pass) — deterministic Three.js scene assembly (box-extruded walls with opening cuts, floor/ceiling planes, placeholder furniture boxes sized per `furniture_catalog.ts`) driven directly by `solver.py`'s output shape; headless Playwright rendering (real WebGL, not a server-side GL library, so the same renderer is reusable for a later in-browser viewer) produces a color PNG and a true single-channel grayscale linear-depth PNG per room via a custom depth shader (not `MeshDepthMaterial`'s default nonlinear packing, which compresses almost the whole range into a handful of gray levels at typical near/far ratios); 3 tests on a 12x16 single-room + bed fixture. Real licensed furniture meshes (currently placeholder boxes) and `.glb` export (currently a reusable `THREE.ObjectLoader`-format `.json`) are explicit follow-ups, not blocked by anything here |
| `render_adapter/` | Done (initial pass) — vendor-agnostic `StylingProvider` interface (`styleImage`) plus `MockStylingProvider` (flat color wash + bitmap-font label stamped onto the input depth map; zero runtime dependencies, no network calls) so the rest of the pipeline is testable before the Phase-0 vendor bake-off (Replicate, PromeAI, etc.) picks a real provider. `checkGeometryDrift` is a deliberately fixed-result STUB — see its module docstring for exactly what the real MiDaS-family-model-based implementation needs to do; not implemented here since it depends on which vendor gets picked. 4 tests, plus manually verified end to end against a real depth map from `scene/`'s `export_views.ts` output |

## Notes

- `genesis/engine/tests/conftest.py` adds `genesis/engine/` to `sys.path` so the existing test files (`import zone_geometry`, `import orientation`) work unmodified after the move into the new directory layout.
- Run the Python test suite from the repo root: `python3 -m pytest genesis/engine/tests -q`.
