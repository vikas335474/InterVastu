# InterVastu External Analysis Validation & Adaptation Report

Scope: validates an externally-produced comparison of InterVastu against five
related open-source repositories, against the live source in this repo
(`genesis/engine/`, `scene/`, `render_adapter/`, `docs/build_plan.md`) and
each external repo's public README/architecture. Read-only validation +
recommendations; no code changed as part of this report.

## 1. Validation Summary

| # | Claim | Status | Evidence |
|---|-------|--------|----------|
| 1 | Geometry-first, deterministic approach | **Confirmed** | `vastu_audit.py` header: "Vastu compliance is a deterministic layer, not a generative one"; every threshold/weight is called out in-code as a documented product assumption, not a Vastu constant (`SEVERITY_POINTS`, `DEFAULT_CENTER_OFFSET_FRACTION_THRESHOLD`, etc.) |
| 2 | Facade/true-north orientation estimate from footprint (preferred over magnetic compass) | **Confirmed** | `orientation.py` computes bearing from `minimum_rotated_rectangle`'s long edge; docstring explicitly frames this as an alternative to a "15-20 degree real-world error" compass reading |
| 3 | 16-zone assignment relative to true geometric centroid (not bbox centre) | **Confirmed** | `zone_geometry.compute_centre()` uses Shapely polygon centroid; `SECTORS` has 16 entries at 22.5° width; `diagnose_shape()` separately reports `bbox_center` for comparison |
| 4 | Footprint-level shape defect diagnosis (hollow/external centre, missing/cut zones) | **Confirmed** | `zone_geometry.diagnose_shape()` implements both `hollow_center` (point-in-polygon test) and `missing_zones` (bbox-minus-footprint, octant-labelled) independently, exactly as described |
| 5 | Ritual/deity/mantra content fully decoupled, opt-in, with disclaimers | **Confirmed** | `ritual_protocol.py` is never imported by `vastu_audit.audit_layout`; `enrich_defects_with_ritual` is a separate call; every block carries `RITUAL_DISCLAIMER`; build plan confirms UI gates it behind `include_ritual_protocol`, off by default |
| 6 | Deterministic 3D scene assembly (Three.js) with wall openings, floors/ceilings, furniture placeholders | **Confirmed** | `scene/src/build_scene.ts` + build plan: box-extruded walls with opening cuts, floor/ceiling planes, furniture boxes sized via `furniture_catalog.ts`; furniture is explicitly "placeholder boxes," not licensed meshes |
| 7 | Depth-map export + vendor-agnostic AI styling interface (currently mocked) | **Confirmed** | `scene/src/export_views.ts` emits linear-depth PNGs via custom shader (README explains why `MeshDepthMaterial`'s default packing was rejected); `render_adapter/src/types.ts` defines `StylingProvider`, only `MockStylingProvider` implemented, `checkGeometryDrift` is an explicit stub |
| 8 | Strong emphasis on human confirmation for orientation, no invented "floor-band" scoring | **Confirmed** | `orientation.py`'s `FOOTPRINT_ESTIMATE_RELIABILITY_NOTE` mandates human confirmation "before being used in a paid report"; `ritual_protocol.py` docstring explicitly contrasts itself with "invented numeric floor-band scoring, which this project deliberately refused to add" |

**Caveat on claim 8 and the scoring layer generally:** `vastu_audit.py` *does*
produce a single 0–100 `compliance_score` (`SEVERITY_POINTS` = major:10,
minor:3; `BASE_SCORE = 100`). This is not a "floor-band" system, but it is
still an invented point scale — the module's own docstring is explicit that
this "has NOT been validated by a Vastu consultant and should be treated as
provisional." The claim as stated ("avoidance of fabricated floor-band
scoring") is accurate to the letter (no floor-band concept exists in this
codebase) but could be read as implying no numeric scoring at all exists,
which is not the case. Marking this **Partially true** for precision.

### External repos — corrections to the claims table

| Repo | Claim in original table | Validation |
|------|--------------------------|------------|
| Pranit-satnurkar/Vastu_Architect | "Per-room scoring across directional zones, 3D viz, CAD/DXF export" | **Confirmed**, and understated — README also claims BSP-based auto-layout generation, environmental/solar/fire-safety analysis, and an AIA-standard DXF export pipeline (`ezdxf`). Orientation is **not** footprint-derived; it appears to rely on a manual "north arrow overlay" plus `SunCalc.js` for solar position, not a geometric bearing estimate. This is a materially different (weaker, manual-only) orientation approach than InterVastu's. |
| jasoncobra3/Floorplan-Dimractor | "Multi-format dimension parsing, cabinet codes, Streamlit + CLI, dual PDF libs" | **Confirmed** as described — PyMuPDF + pdfplumber, regex-driven multi-format (inches/feet-inches/fractions) dimension extraction, Streamlit dashboard + CLI, cabinet/appliance code detection, JSON output. |
| anngrrr/planparser | "YOLO11 + Faster R-CNN, 15 classes, Gradio + FastAPI" | **Confirmed**, with detail: YOLO11-Large (mAP50 0.937) as primary, Faster R-CNN ResNet-50-FPN (mAP50 0.728) as an alternative switchable model; 15 classes are furniture/fixtures (bed, sofa, sink, stove, toilet, table, chair, door, etc.) — **not** structural elements like walls. Trained on 1,033 images / ~25k boxes (Floorplan Details Fork, CC BY 4.0). |
| sankhya007/S.T.I.T.C.H | "UNet wall segmentation, tiled inference + Gaussian blending for large plans" | **Confirmed**, with an important scope correction: the project's stated purpose is to feed a *crowd-evacuation simulation* (a sibling project, "T.R.A.G.I.C"), not a Vastu or design pipeline. Output is a binary wall/walkable mask, not a vector wall layout. UNet+ResNet34 trained on ~10k images (CubiCasa5K + Modified Swiss Dwellings). |
| TeaganLi/HouseExpo | "~35k plans, vector verts, room categories, Gym simulator" | **Confirmed**, precisely — 35,126 plans / 252,550 rooms, JSON vertex + room-category format, bundled `PseudoSLAM` OpenAI-Gym-compatible simulator. Built on SUNCG. Its primary purpose is robot SLAM/navigation research, not architectural analysis — the "ideal offline testbed" framing in the original table is a repurposing of the data, not a stated goal of the project itself. |

No repos were found to be private, renamed, or deleted — all five resolved and had readable READMEs.

## 2. Corrected Comparison Table

| Repo | Focus | Verified Strengths | Verified Gaps / Caveats | Relation to InterVastu |
|------|-------|---------------------|--------------------------|--------------------------|
| Vastu_Architect | Full-stack Vastu compliance + generation | Per-room directional scoring, BSP auto-layout, 2D/3D viz (Konva+Three.js), AIA-standard DXF export, environmental/solar analysis | Orientation is manual/solar-derived, not footprint-geometry-derived; no evidence of a true occupied-area-centroid Brahmasthan calc or shape-defect diagnosis | Closest peer on scoring + 3D + CAD; **weaker** than InterVastu on orientation rigor and geometric shape diagnosis |
| Floorplan-Dimractor | PDF dimension & code extraction | Multi-format dimension parsing (in/ft-in/fractions), cabinet code detection, dual-library PDF text extraction, Streamlit + CLI | Text/PDF-only — no floor-plan image (raster) support, no room polygon output | Complementary upstream: could feed dimension data into InterVastu's geometry layer, but produces text/spans, not polygons |
| planparser | Furniture/fixture object detection | Two production-grade trained models (YOLO11, Faster R-CNN), 15 furniture/fixture classes, Gradio + FastAPI, real inference benchmarks | Detects furniture/fixtures only, not walls/rooms/structure; no orientation or geometric output | Complementary: could seed/validate InterVastu's furniture placeholders or `solver.py` inputs from a real raster plan |
| S.T.I.T.C.H | Wall segmentation (binary mask) | Tiled inference + Gaussian blending solves the seam problem on large plans; trained on two solid public datasets | Built for evacuation simulation, not vectorization; outputs a raster mask, not room polygons — would need a separate vectorization step before it could feed `zone_geometry.py` | Structural input candidate, but requires a masks→polygons bridge InterVastu doesn't have today |
| HouseExpo | Large 2D layout dataset + SLAM sim | 35k+ real, vectorized floor plans with room categories — directly polygon-shaped data | Room categories are generic (kitchen/bedroom/etc.), not Vastu zones; no compass/orientation metadata; U.S./generic layouts, not India-specific | Strongest candidate as an **offline regression/stress-test corpus** for `zone_geometry.analyze_zones` / `diagnose_shape` — free, large, and already in (x,y) vertex form |

## 3. Identified Gaps & Opportunities (prioritized)

1. **HouseExpo as a regression/stress-test corpus for `zone_geometry.py`** (High value, low risk). InterVastu's own test suite currently exercises a small, hand-built set of fixtures (the Unit-12 L-shape plus unit tests). HouseExpo's 35k real (if non-Vastu, non-India) vector floor plans are a free way to stress-test `analyze_zones`/`diagnose_shape` against degenerate/self-intersecting/highly irregular polygons the hand-built fixtures don't cover — e.g. confirming `_to_polygon`'s `buffer(0)` repair path and the `missing_zone_area_fraction_threshold` sliver filter hold up at scale. Purely a **test-time** dependency; ships no runtime coupling.

2. **planparser-style furniture/fixture detection as an optional input to `solver.py`** (Medium value, medium risk). `solver.py` currently *places* a fixed, narrow set of furniture (bed, stove, one wall recommendation) given a room polygon — it does not *detect* existing furniture from a real plan. A planparser-class detector could seed `solver.py`'s room-polygon-level inputs from a scanned/raster plan, or (longer-term) validate that a proposed placement doesn't collide with existing fixtures. This is additive to the input side only; it must not touch the deterministic geometry/scoring core.

3. **Floorplan-Dimractor-style dimension extraction as an optional ingestion helper** (Medium value, low-medium risk). InterVastu today assumes room/boundary polygons are already supplied in feet. A dimension-extraction front-end (text-based, PDF-native) could turn an annotated PDF plan into the vertex+dimension data `zone_geometry.py` consumes — but this only helps for text-native PDFs, not scanned rasters, and does not itself produce a closed polygon (it extracts spans/labels, which still need to be assembled into a boundary). Worth prototyping as a separate, decoupled ingestion module, not a core dependency.

4. **S.T.I.T.C.H-style tiled wall segmentation as an optional structural input** (Lower priority, higher risk/effort). Its raster mask output is a meaningfully different representation than the vector polygons `zone_geometry.py` requires — adopting it means also building (or adopting) a mask→polygon vectorization step, which is real added surface area and a new failure mode (mis-vectorized walls silently corrupting a "deterministic" geometry pipeline). Worth watching, not adopting now; if pursued, any vectorized output must be surfaced with the same "estimate, needs human confirmation" framing InterVastu already applies to `orientation.py`.

5. **CAD/DXF export maturity gap vs. Vastu_Architect** (Product gap, not urgent). InterVastu's `scene/` produces a Three.js scene + PNG/depth exports; there is no DXF/CAD export anywhere in the current pipeline (`scene/src/*`, `render_adapter/src/*` confirm this — no `ezdxf`-equivalent or CAD-layer code exists). If a CAD deliverable becomes a product requirement, `ezdxf` (Python, MIT-licensed, already proven in Vastu_Architect) is a reasonable dependency to evaluate — but this is a new feature area, not an adaptation of existing code, and should be scoped separately.

6. **No scoring pattern from Vastu_Architect is recommended for adoption.** Its BSP auto-layout and 0–100 grade are generative/product features that sit upstream of and orthogonal to InterVastu's deterministic audit core; adopting its scoring approach specifically would not add anything InterVastu's own (already-flagged-as-provisional) `compute_score` doesn't already do, and risks diluting the "no fabricated precision" stance the project has deliberately held to.

## 4. Recommended Adaptations

Item 1 was implemented in a follow-up session (see below); the rest are
scoped but not built — each touches either a new external dependency (a
trained model, a new library) or a new data representation (raster masks,
PDF text spans) that deserves its own design/review pass rather than being
bundled into a research report or a single follow-up task.

Prioritized, in order of value/risk ratio:

1. **IMPLEMENTED.** `genesis/engine/fixtures/houseexpo_sample/` (40 real HouseExpo boundaries: the upstream 10-house "mini" set + a `seed=42` random draw of 30 more from the full 35,126-house archive, MIT licensed, ~256 KB total, provenance documented in its own `README.md`) plus `genesis/engine/tests/test_houseexpo_regression.py`, which runs `diagnose_shape()` and `analyze_zones()` against every fixture and asserts only structural invariants (no exceptions — including on the 3 sampled boundaries that are self-intersecting per Shapely — every documented field present with the right type/range, and the `hollow_center == not centroid_inside_boundary` cross-field invariant). Deliberately asserts nothing about Vastu correctness, since HouseExpo carries no Vastu ground truth. 81 new tests, all passing; full suite now 209 tests. Does not touch `vastu_audit.py`'s scoring or schema, and is purely additive/test-only.
2. **(Scope separately)** A design spike for an optional `furniture_detection` input adapter feeding `solver.py`, modeled on planparser's class list, kept behind an explicit opt-in flag the same way `ritual_protocol.py` is — so `solver.py`'s existing narrow, hand-verified placement logic is never silently overridden by a model's output.
3. **(Scope separately)** A design spike for a PDF-dimension ingestion helper (Floorplan-Dimractor-style), explicitly scoped to text-native PDFs only, with output that a human still confirms before it becomes a `zone_geometry.py` boundary — mirroring the existing `orientation.py` human-confirmation pattern.
4. **(Watch, do not build yet)** S.T.I.T.C.H-style wall segmentation — track as a future option only if/when a raster-plan ingestion pipeline becomes a real product requirement; would need its own vectorization + human-confirmation layer before touching the geometry core.
5. **(Defer)** CAD/DXF export — real gap, but a new feature, not an adaptation; needs its own product scoping (which CAD standard, which layer conventions) before implementation.

`docs/build_plan.md` was intentionally **not** modified — none of the above changed any shipped module's status; item 1 is the only one concrete enough to size, and it hasn't been implemented yet.

## 5. Next Steps / Open Questions

- **Decision needed:** should item 1 (HouseExpo regression fixture) be scoped as a follow-up task now? It's the lowest-risk, highest-confidence recommendation in this report.
- **Open question:** does the product roadmap actually need CAD/DXF export? Vastu_Architect having it doesn't create pressure to match it unless a customer/use-case requires it.
- **Open question:** is raster (scanned/photographed) floor-plan ingestion in scope at all for InterVastu, or is the product assumption that plans always arrive as clean vector/dimensioned input? This materially changes how much of planparser/S.T.I.T.C.H is relevant — both exist to handle raster input, which may not be a problem InterVastu has.
- No claims in the original analysis were found to rest on a private, renamed, or deleted repository — all five were publicly readable at the time of this review.
