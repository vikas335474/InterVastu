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
  scene/                      # Node — deterministic 3D + depth maps
    src/build_scene.ts         # room polygons + solver output -> Three.js scene
    src/export_depth.ts        # headless render -> depth map + camera views
    tests/
  render_adapter/             # Node — vendor-agnostic styling interface
    src/adapter.ts             # interface + mock provider
    src/providers/             # real providers added post-spike
  docs/
    build_plan.md              # this file
```

## Status

| Path | Status |
| --- | --- |
| `genesis/engine/zone_geometry.py` | Done (Phase 1b) — deterministic Brahmasthan + 16-sector zone assignment, 19 tests |
| `genesis/engine/orientation.py` | Done — footprint lookup (MS Buildings + OSM fallback) + minimum-rotated-rectangle bearing estimate + manual override, 15 tests |
| `genesis/engine/audit.py` | Not started (Phase 1a). Blocked: needs the actual existing `vastu_audit.py` and `vastu_rule_schema.json` content, neither of which exists in this repo yet — waiting on those before extending with object-placement rule checks |
| `genesis/engine/schema/vastu_rule_schema.json` | Not started — pending consultant sign-off |
| `genesis/engine/solver.py` | Not started (Phase 1c) |
| `genesis/engine/fixtures/` | Not started as a shared directory — the Unit 12 L-shape regression fixture currently lives inline in `genesis/engine/tests/test_zone_geometry.py`; extract here if/when `audit.py`/`solver.py` need to share it |
| `scene/` | Not started (Phase 2) |
| `render_adapter/` | Not started |

## Notes

- `genesis/engine/tests/conftest.py` adds `genesis/engine/` to `sys.path` so the existing test files (`import zone_geometry`, `import orientation`) work unmodified after the move into the new directory layout.
- Run the Python test suite from the repo root: `python3 -m pytest genesis/engine/tests -q`.
