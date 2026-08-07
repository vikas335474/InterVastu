# InterVastu — Strategy & Gap Analysis

Scope: an unbiased assessment of whether the project's current strategy derives
the best value from the work done, and a register of gaps. Read-only review of
`genesis/engine/`, `ui/`, `scene/`, `render_adapter/`, `docs/`, and
`vastu_rule_schema.json` as of commit `2fd4f93`.

Every claim marked **[verified]** was checked by executing the code or grepping
the source during this review, and the check is shown. Claims about Vastu
tradition are marked with an explicit confidence level — see §6 for the limits
of this report's authority on the tradition itself.

---

## 1. Verdict

**The method is right. The coverage is narrower than the framing suggests.**

The strategy — deterministic geometry first, interpretation strictly downstream,
every invented constant labelled as invented — is not just defensible, it is
better discipline than most commercial Vastu software exhibits. Nothing in the
gap register below argues for changing that approach.

The gap is not *how* the project computes. It is *how much of the domain* it
computes over. The engine today is a rigorous **directional (dik) Vastu audit**.
A practising consultant's deliverable typically also includes entrance-pada
analysis, proportional (Ayadi) calculation, and marma-point checks — none of
which exist here. The schema itself already says this, precisely, in
`known_gaps[2]`: the distinction between marketing "full Vastu compliance"
versus "directional Vastu audit". That note is the single most important
sentence in the repository and it is still unresolved.

Second finding, structural rather than domain: **the project's own epistemic
discipline is not yet wired into its output.** The schema records per-rule
confidence; the engine discards it. The score saturates. Both are verified
below. These are the cheapest high-value fixes available.

### Correction to my earlier advice in this session

I previously told you the spec's "32-Pada perimeter" was not a real classical
construct. That was right about the *geometry* it described (radial slicing) and
wrong about the *intent*. There is a well-attested classical construct of **32
entrance padas** — and it is exactly the perimeter ring of the 81-pada grid:

```
9x9 = 81 padas; border ring = 32; interior = 49      [verified]
```

So the spec was pointing at something real and got the shape wrong. More
importantly: `geometry_engine.pada_grid()` **already computes that ring**. The
substrate is built; the entrance-evaluation layer on top of it is missing. That
moves entrance analysis from "not applicable" to the highest-value gap in this
report (§3, Gap D1).

---

## 2. What is genuinely strong (briefly — this section is not padding)

These are load-bearing and should not be traded away in any future refactor:

| | |
|---|---|
| **Centroid, not bbox centre** | `compute_centre()` uses true occupied-area centroid. This is the correct Brahmasthan for irregular plans and most tools get it wrong. |
| **Hollow-centre detection** | `diagnose_shape()` catches a centroid falling *outside* the footprint via point-in-polygon, independent of offset magnitude. Genuinely sophisticated; classically a severe defect. |
| **Refusal to fabricate** | `ritual_protocol.py` explicitly scopes out the 45-devata map rather than inventing it. `pada_devata_45()` names 9 of 81 cells and flags 72 as `needs_verification`. This restraint is the project's main defensible asset. |
| **Separation of computation from interpretation** | `audit_layout()` never imports `ritual_protocol`. Opt-in, off by default. Correct on engineering, legal, and cultural grounds simultaneously. |
| **Orientation rigour** | Footprint-derived bearing with a mandatory human-confirmation note, rather than trusting a phone compass (15–20° indoor error). |

---

## 3. Gap Register

Severity: **P1** = blocks commercial use · **P2** = materially limits value ·
**P3** = worth doing, not urgent.

### A. Verified internal inconsistencies (cheapest to fix, fix these first)

**A1 — The schema's `confidence` field is dead data. [verified] · P2**

The schema carries 18 `confidence` annotations (`high`/`medium`/`low`) — the
product of real cross-source research, e.g. `Garage` is `low`, `MainEntrance` is
`high`. No engine code reads any of them:

```
grep '"confidence"' genesis/engine/*.py ui/*.py
  -> only furniture *detection* confidence (a different concept). Rule
     confidence is never read.                                    [verified]
```

Consequence: a `low`-confidence Garage-in-NE rule deducts **exactly the same
points** as a `high`-confidence South-entrance rule. The engine's output
therefore projects more uniform certainty than its own source data supports —
the one failure mode this codebase is otherwise obsessive about avoiding.

Fix: surface confidence per violation, and either weight the score by it or (more
conservative, and more in keeping with the project's stance) report a score
*band* for medium/low-confidence findings rather than a point value.

**A2 — The compliance score saturates and is not normalised. [verified] · P2**

```
 5 major violations -> score 50
10 major violations -> score  0
20 major violations -> score  0
40 major violations -> score  0                                   [verified]
```

Past 10 major violations the score is constant. A mildly non-compliant flat and
a catastrophically non-compliant one are indistinguishable at the number the
customer sees first. It also has no denominator: 3 violations across 4 rooms and
3 across 20 rooms score identically.

`vastu_audit.py`'s docstring is admirably honest that the weights are invented —
but the *shape* of the function (unbounded linear deduction against a fixed
base) is a separate, unflagged problem from the *weights*. Fix: normalise
against applicable-rule count, and either compress the tail or report
`major/minor` counts as the headline with the score secondary.

**A3 — `pada_grid()` is laid over the bounding box, not the plot. [verified] · P3**

On the Unit 12 L-shape, 6 of 81 cells fall entirely outside the built footprint
and 32 are partially cut **[verified]**. For a rectangular flat this is exact;
for an irregular one it is a methodological choice the code makes silently.
Classically the mandala is inscribed on the *plot*, and how to apply it to an
irregular footprint is genuinely disputed among practitioners — which is
precisely why it should be surfaced as a documented choice (as this project does
everywhere else) rather than left implicit. I introduced this; the README section
I wrote does not flag it. It should.

### B. Engineering & delivery

**B1 — There is no CI. [verified] · P1 for any shipping product**

No `.github/` directory exists. 336 Python tests plus the Node suites run only
when someone remembers. PR #17 shows `total_count: 0` checks — directly observed
this session. For a project whose entire value proposition is *determinism*, the
absence of an automated gate on that determinism is the sharpest
strategy-to-execution mismatch in the repo. This is also the cheapest item here:
a single workflow file running `pytest` plus the Node tests.

**B2 — Not an installable package · P2**

`ui/server.py` does `sys.path.insert()` to reach the engine. No `pyproject.toml`.
`requirements.txt` pins only `>=`, no lockfile. This is why deployment needed
care, and it makes the engine hard to consume from anywhere but this repo layout
— which matters if the engine is genuinely "the moat" (per `build_plan.md`) and
should eventually be callable as a library or service.

**B3 — The Python↔Node contract is untested across the boundary · P2**

`scene/` consumes `solver.py`'s output shape, but nothing verifies that contract
end-to-end. A field rename in `solver.py` breaks the 3D pipeline silently, and
both suites stay green. A single golden-JSON fixture shared by both sides would
close this.

**B4 — Persistence/deployment mismatch · P2 (in progress this session)**

SQLite on ephemeral hosting loses accounts and saved flats. Already analysed;
the decision is pending and correctly framed as a cost question, not a technical
one.

### C. Product & commercial

**C1 — The schema is still `v0.2.0` draft, unsigned. [verified] · P1 — gates everything**

`_meta.status`: *"Requires sign-off from a licensed Vastu consultant before
production use."* Every remedy string, every severity, every point weight
inherits this. No amount of additional engineering changes this blocker, and
each new feature built on the unsigned schema increases the surface a consultant
must eventually review. **This is the critical path.** The highest-value next
action in the entire project is probably not code.

**C2 — Remedy language has not had legal review · P1**

Flagged in `known_gaps[3]`. Consumer-protection exposure on "this will fix your
dosha" phrasing in a paid product. The text is already carefully hedged, which
helps, but hedging authored by the engineer is not the same as review by counsel.

**C3 — The compliance-claim question is unresolved · P1**

`known_gaps[2]` asks whether the product markets "full Vastu compliance" (which
would require the Ayadi/mandala layer) or "directional Vastu audit" (which the
schema supports). This is a positioning decision that determines how much of §D
is mandatory versus optional. It should be answered before more engine work, not
after.

### D. Vastu domain coverage — the substantive gap

Confidence key: **[High]** = well-attested across classical texts and mainstream
practice · **[Medium]** = real but variable across traditions.

**D1 — Entrance evaluation at 32-pada resolution. [High] · P1 — highest value in this report**

The schema evaluates `MainEntrance` at 16-zone resolution only (`preferred:
[N, NE, E]`, `forbidden: [S]`) **[verified]**. Practising consultants evaluate
the main door against the **32 perimeter padas**, each carrying its own
auspiciousness — several padas *within* an otherwise-favourable direction are
traditionally inauspicious, and this per-pada distinction is a substantial part
of what a paid residential Vastu consultation actually delivers.

Compounding this, the current representation is weak: the fixture models the
entrance as a 1×2 ft marker rectangle whose *centroid bearing* is taken from the
plot centre **[verified]**. A door is a segment on the perimeter, not an area
with a bearing — the classical question is *which perimeter pada the opening
falls in*, which is a different computation.

Why this ranks first: highest practitioner value, and the geometric substrate
already exists — `pada_grid()` computes the 32-cell ring today. What is missing
is (a) mapping a door opening to its pada by boundary intersection rather than
centroid bearing, and (b) a **sourced** auspiciousness rating per pada. (b) is
consultant work, not engineering, and belongs in the same sign-off pass as C1.

**D2 — Ayadi Shadvarga (proportional calculations). [High] · P2**

The six-fold proportional system (Aya, Vyaya, Yoni, Nakshatra, Vara, Tithi)
derives auspiciousness from arithmetic on the building's perimeter and
dimensions. Explicitly flagged as absent in `known_gaps[2]`.

This deserves attention precisely because it is the *most computable* layer in
classical Vastu — pure deterministic arithmetic on numbers the engine already
has. It is an unusually good fit for this codebase's philosophy. **Caution:** the
exact multipliers and modulo constants vary between texts and regional
traditions. They must be sourced from a named authority and cited, not
reconstructed — this is exactly the kind of thing that looks precise and is
therefore dangerous to guess. I am not supplying constants in this report for
that reason.

**D3 — Marma sthana (vulnerable points). [High] · P2**

Classical texts are emphatic that structural elements (beams, columns, load
walls) should not fall on the mandala's marma points — the intersections of its
diagonals and principal grid lines. This is highly geometric, deterministic, and
squarely in the engine's existing competence.

It is also *newly reachable*: marma points are defined on the pada grid, which
now exists. Prerequisite is wall/column geometry as input — currently the engine
consumes room polygons but not structural elements, so this needs an input-model
extension first.

**D4 — The 45-devata map is a scaffold, not yet a feature. [Medium] · P3**

`pada_devata_45()` names 9 of 81 cells; 72 are `needs_verification=True`. This
was the right call on honesty grounds and I would not change it. But it should be
understood as *infrastructure awaiting sourcing*, not delivered capability — it
produces no interpretive value until the roster is filled by someone qualified.
Its `overrides` parameter is the intended path.

**D5 — Vithi shula / road-thrust analysis. [Medium] · P3**

T-junction road thrust onto a plot is a standard element of site-level
consultation. Requires site context (road geometry) that the engine does not
currently ingest — genuinely out of scope for a flat-interior tool, and listed
here only for completeness of the domain map.

**D6 — Multi-storey variation. [Medium] · P3**

Flagged in `known_gaps[1]`. Zone rules shift by floor in some traditions. The
engine is implicitly single-storey. Worth an explicit statement of that
assumption in the UI rather than silence.

---

## 4. Recommended sequence

Ordered by value ÷ effort, not by interest:

1. **Add CI** (B1). Hours. Protects everything else. Do this first.
2. **Answer C3** — "full compliance" or "directional audit"? One decision,
   determines whether D1/D2 are mandatory or optional. No code.
3. **Engage the consultant** (C1). Long lead time — start it in parallel with
   everything below, not after. Bundle D1's pada ratings into the same
   engagement so one review covers both.
4. **Fix A1 + A2.** Small, self-contained, and they make the output honest about
   its own uncertainty — the project's core differentiator.
5. **Then D1 (entrance padas)**, once ratings are sourced. Highest domain value,
   substrate already built.
6. **Then D2 (Ayadi)** — only with cited constants.
7. B2/B3 opportunistically; D3–D6 as roadmap.

---

## 5. What I would explicitly not do

- **Do not add more Vastu surface area before C1 resolves.** Every feature built
  on an unsigned schema enlarges the eventual review.
- **Do not fill the 45-devata roster from general knowledge** (including mine).
  `overrides` exists for sourced input; that is the correct channel.
- **Do not "improve" the score by adding precision** — more decimal places on an
  invented weighting is worse, not better. Fix its *shape* (A2) and its *honesty*
  (A1), not its resolution.
- **Do not chase feature parity with Vastu_Architect's DXF export** absent a
  customer asking. Already correctly concluded in
  `external_analysis_validation.md` §3.6.

---

## 6. Limits of this report

On **code and architecture**, claims marked [verified] were executed or grepped
during this review; treat them as checked facts about commit `2fd4f93`.

On **Vastu tradition**, I am not a licensed consultant and this report does not
substitute for the sign-off `_meta.status` requires. What I can state reliably is
which *constructs exist* in the classical corpus and mainstream practice, and
therefore what a domain-complete product would cover — that is what §D maps. I
have deliberately not supplied specific pada names, Ayadi constants, or
auspiciousness ratings, because those vary across texts and traditions and
supplying them from memory would reproduce exactly the failure mode this project
has otherwise avoided. Where a gap needs sourced numbers, the report says so and
stops.

The project's own position — that this content requires consultant sign-off
before production use — remains correct, and nothing in this review weakens it.
