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
| `genesis/engine/vastu_audit.py` | Done (Phase 1a) — room/plot zone-and-adjacency audit (`audit_room`/`audit_layout`) plus an object-placement extension (`audit_object_placement`/`audit_layout_with_objects`) covering sleeping/seat/stove/desk/furniture/seating direction rules, 16 tests. `OBJECT_PLACEMENT_RULES` is this module's own interpretation of the schema's free text — flagged in-code as pending consultant sign-off, same as the schema itself |
| `genesis/engine/vastu_rule_schema.json` | v0.2.0 draft, in place — still explicitly "pending sign-off from a licensed Vastu consultant" per its own `_meta.status` |
| `genesis/engine/solver.py` | Done (Phase 1c) — constraint-based placement for bed (MasterBedroom/GuestBedroom/ChildrenBedroom), stove (Kitchen), and heavy-furniture wall recommendation (LivingRoom) only; always returns a least-bad placement with a `compromise`/`compromise_note` flag rather than silently failing or violating a rule, 13 tests. Does not attempt general room layout or any other room type |
| `genesis/engine/fixtures/` | Not started as a shared directory — the Unit 12 L-shape regression fixture currently lives inline in `genesis/engine/tests/test_zone_geometry.py`; extract here if a future task needs to share it across modules |
| `scene/` | Not started (Phase 2) — `solver.py`'s output shape (list of `{room, object, position, rotation_deg, satisfies_rule, compromise, compromise_note}`) is designed to feed directly into this |
| `render_adapter/` | Not started |

## Notes

- `genesis/engine/tests/conftest.py` adds `genesis/engine/` to `sys.path` so the existing test files (`import zone_geometry`, `import orientation`) work unmodified after the move into the new directory layout.
- Run the Python test suite from the repo root: `python3 -m pytest genesis/engine/tests -q`.
