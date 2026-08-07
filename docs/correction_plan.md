# Correction Plan — acting on `vastu_coverage_gap_analysis.md`

Companion to `docs/vastu_coverage_gap_analysis.md`. That document identifies
gaps; this one says what is being done about each, in what order, and — for the
items not being done — exactly what unblocks them.

## Feasibility rule used here

A phase is **executable now** only if it needs no input this codebase cannot
source itself. Anything requiring a licensed consultant's judgement (severity
weights, pada auspiciousness ratings, Ayadi constants) is **blocked by
definition** and is scoped, not built — consistent with the project's existing
refusal to guess at domain content.

Everything executed below is **additive**: no existing field changes value, no
existing test was rewritten to accommodate a change. `compliance_score` in
particular is left numerically identical, because `ui/index.html`, `storage.py`,
and nine tests read it directly.

| Phase | Gap | Status | Blocked by |
|---|---|---|---|
| 1 | B1 — no CI | **Executed** | — |
| 2 | A1 — confidence is dead data | **Executed** | — |
| 3 | A2 — score saturates, no denominator | **Executed** | — |
| 4 | A3 — pada grid bbox choice undocumented | **Executed** | — |
| 5 | D1 — entrance pada (geometry half) | **Executed** | ratings need consultant |
| 6 | C1/C2/C3 — sign-off, legal, positioning | Not started | human decisions |
| 7 | D2 — Ayadi Shadvarga | Scoped only | cited constants |
| 8 | D3 — marma sthana | Scoped only | structural-element input model |
| 9 | B2/B3 — packaging, cross-language contract | Deferred | — |

---

## Phase 1 — CI (gap B1)

**Problem.** No `.github/` existed. 336 Python tests plus two Node suites ran
only when someone remembered. PR #17 showed zero checks.

**Done.** `.github/workflows/ci.yml` with two jobs:

- `python` — installs `requirements.txt`, runs `pytest genesis/engine ui`.
- `node` — runs `render_adapter`'s suite (zero runtime deps) and `scene`'s
  suite with Playwright's Chromium installed.

Python is the gating job: it covers the deterministic engine, which is the part
whose whole value proposition is that it does not drift.

---

## Phase 2 — Confidence surfacing (gap A1)

**Problem.** The schema carries 18 `confidence` annotations. No engine code read
any of them, so a `low`-confidence Garage rule deducted identically to a
`high`-confidence entrance rule.

**Done, additively.**

- `audit_room()` now attaches `"confidence"` to every zone/adjacency violation,
  read from the rule's own `confidence` field (`None` when the schema does not
  state one — never guessed).
- `audit_layout()` gains `compliance_score_range`: `{"low", "high",
  "is_uncertain"}`. `low` is the existing score (all violations stand). `high` is
  the score if every violation resting on a non-`high`-confidence rule were
  discounted. A wide band means the result leans on rules the schema itself
  flags as contested.

`compliance_score` is unchanged. The band is reported *beside* it, not instead
of it.

**Deliberately not done:** weighting the score arithmetically by confidence.
That would bury a research signal inside an already-invented weighting. A band
keeps the uncertainty legible.

---

## Phase 3 — Score honesty (gap A2)

**Problem.** `compute_score` saturates: 10 major violations and 40 major
violations both score 0. No denominator, so 3 violations across 4 rooms scored
like 3 across 20.

**Done, additively.** `audit_layout()` now also reports:

- `total_deductions` — the **uncapped** deduction total, so severity beyond the
  floor is preserved rather than silently clipped.
- `score_saturated` — `True` when deductions exceeded `BASE_SCORE`, making the
  clip visible instead of hidden.
- `rooms_evaluated` — the denominator that was missing, so violation density is
  derivable by any caller.

**Deliberately not done:** changing `compliance_score`'s formula. The weights
are unvalidated (`SEVERITY_POINTS`, flagged in-module since v0.1); recalibrating
the curve underneath invented weights adds false precision without adding
information. These fields make the deficiency *measurable* — which is the
prerequisite for a consultant fixing it properly later.

---

## Phase 4 — Pada grid bbox choice (gap A3)

**Problem.** `pada_grid()` lays the mandala over the rotated boundary's bounding
box. Exact for rectangles; for the Unit 12 L-shape, 6 of 81 cells fall entirely
outside the footprint and 32 are partially cut. Classically the mandala is
inscribed on the plot, and its application to irregular footprints is genuinely
disputed among practitioners. The code made this choice silently.

**Done.** Documented as an explicit, named product choice in `pada_grid()`'s
docstring and the README — matching how `zone_geometry.py` already handles its
own threshold choices. `boundary_occupancy_fraction` already lets a caller
discount out-of-footprint cells; that is now stated rather than implied.

---

## Phase 5 — Entrance pada, geometry half (gap D1)

**Problem.** The schema evaluates `MainEntrance` at 16-zone resolution only.
Practitioners evaluate the main door against the 32 perimeter padas. The current
fixture models the entrance as a marker rectangle and takes its *centroid
bearing from the plot centre* — but a door is a segment on the perimeter, and
the classical question is which perimeter pada the opening falls in.

**Split deliberately.** Geometry is computable here; auspiciousness ratings are
not.

**Done —** `geometry_engine.entrance_pada()`:

- Takes a door opening (a segment, or a small polygon) and locates it on the
  81-pada grid's 32-cell perimeter ring by **boundary intersection**, not
  centroid bearing.
- Returns the pada's ring index (0–31, north-west corner origin, clockwise),
  its `(row, col)`, its compass side, and the overlap fraction when an opening
  straddles two padas — straddling is reported, not rounded away.
- Ratings are **injectable** via `ratings=`, exactly like `pada_devata_45`'s
  `overrides=`. Unrated padas return `rating: None, needs_verification: True`.

**Not done, and cannot be here:** the auspiciousness rating per pada. Those
vary across texts and traditions; supplying them from memory is precisely the
failure this project has avoided. They belong in the same consultant engagement
as C1 (schema sign-off) — the `ratings=` parameter is the intended delivery
channel, so no code change is needed when they arrive.

---

## Phases 6–9 — not executed, and why

**6. C1 / C2 / C3 — consultant sign-off, legal review, positioning.** Not
engineering work. C3 (does the product claim "full Vastu compliance" or
"directional Vastu audit"?) is one decision that determines whether phases 7–8
are mandatory or optional, and it costs nothing but an answer. It remains the
highest-value open item in the project.

**7. D2 — Ayadi Shadvarga.** The best remaining fit for this engine: pure
deterministic arithmetic on dimensions it already holds. Blocked on sourced,
citable multipliers and modulo constants, which vary by text and region.
Scoped, not guessed.

**8. D3 — marma sthana.** Now geometrically reachable (marma points are defined
on the pada grid, which exists). Blocked on an input-model extension: the engine
consumes room polygons but not beams/columns/load-bearing walls, which is what
the check is *about*. That extension deserves its own design pass.

**9. B2 / B3 — packaging, cross-language contract test.** Real but lower value
than everything above, and B2 (making the engine an installable package) would
disturb the deployment work currently in flight. Deferred deliberately, not
forgotten.
