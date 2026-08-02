"""OPTIONAL ritual/activation content for directional Vastu remedies.

=========================================================================
READ THIS BEFORE ENABLING — this module is deliberately NOT wired into the
default audit path (unlike vastu_audit's geometric checks).
=========================================================================

What this is
------------
A static, data-driven lookup that pairs each of the eight compass octants
plus the centre (Brahmasthan) with its traditional presiding deity and a
commonly-used mantra, and wraps a physical remedy in the classical
"Prana Pratishtha" (consecration/activation) sequence. It is the
culturally-authentic counterpart to the *physical* remedies in
``vastu_audit.SHAPE_DEFECT_REMEDIES`` — a copper pyramid placed in the NE,
for example, is traditionally paired with the Ishana/Shiva mantra.

Why it is authentic (and why that is NOT the same as validated)
---------------------------------------------------------------
The directional deity map below is the classical Vastu Purusha Mandala set
of directional lokapalas (Ishana/NE, Agni/SE, Yama/S, Nirriti/SW,
Varuna/W, Vayu/NW, Kubera/N, Indra-Surya/E, Brahma/centre) and the mantras
are widely-attested. So — unlike invented numeric "floor-band" scoring,
which this project deliberately refused to add — this content reflects a
real tradition rather than fabricated pseudo-precision.

That authenticity is a statement about *tradition*, not *efficacy*. These
are religious/ritual practices. This module makes NO claim that performing
them changes any physical, financial, or health outcome, and any product
surface that shows them MUST NOT imply otherwise (the schema's own
``known_gaps`` already flags remedy-efficacy language as a legal review
item; ritual content raises that bar, not lowers it).

Why it is OPT-IN, not automatic
-------------------------------
Auto-prescribing specific Hindu rituals (which deity to invoke, how many
repetitions, on which day) to every user presumes a religious framework the
user may not share. Enabling this in a shipped product is a PRODUCT +
LEGAL + CULTURAL decision, not an engineering default — so:

  * nothing here runs unless a caller explicitly asks for it
    (``vastu_audit.audit_layout`` never imports this module);
  * ``enrich_defects_with_ritual`` only attaches content to defects that
    already carry an unambiguous ``"direction"`` tag;
  * every returned block carries an explicit ``disclaimer``.

Scope
-----
Only the 8 directional lokapalas + centre are encoded. The full 45-devata
(32 external + 13 internal pada) Vastu Purusha Mandala, and per-pada deity
mapping, are intentionally out of scope — a larger, more contested construct
that would need dedicated consultant sourcing before it belonged here.

Transliteration note
--------------------
Mantras are given in Roman transliteration only. Several are attested in
more than one spelling; the alternates listed are the common variants, not
an exhaustive or canonical set. A consultant/priest review is the right
place to finalise exact wording, count, and pronunciation for a paid
product.
"""

from __future__ import annotations

from typing import Any, Iterable

#: Recognised direction keys: the 8 octants plus "center".
DIRECTIONS: tuple[str, ...] = ("N", "NE", "E", "SE", "S", "SW", "W", "NW", "center")

#: Standard obstacle-removal opening, prepended to every activation
#: regardless of direction (classical practice: invoke Ganesha first).
OPENING_MANTRA: dict[str, Any] = {
    "deity": "Ganesha",
    "mantra": "Om Gam Ganapataye Namah",
    "repetitions": 21,
    "purpose": "Traditional obstacle-removal invocation performed first, before the direction-specific mantra.",
}

#: Direction -> presiding deity + mantra(s). See module docstring for
#: provenance and the efficacy/authenticity distinction.
DIRECTION_DEITIES: dict[str, dict[str, Any]] = {
    "center": {
        "deity": "Brahma (Vastu Purusha at the Brahmasthan)",
        "primary_mantra": "Om Brahmane Namah",
        "alternate_mantras": ["Om Vastu Purushaya Namah"],
        "element": "Akasha (space)",
    },
    "NE": {
        "deity": "Ishana (a form of Shiva)",
        "primary_mantra": "Om Namah Shivaya",
        "alternate_mantras": ["Om Ishanaya Namah"],
        "element": "Jala (water) / sacred zone",
    },
    "E": {
        "deity": "Indra / Surya",
        "primary_mantra": "Om Suryaya Namah",
        "alternate_mantras": ["Om Indraya Namah"],
        "element": "Air / light",
    },
    "SE": {
        "deity": "Agni",
        "primary_mantra": "Om Agnaye Namah",
        "alternate_mantras": [],
        "element": "Agni (fire)",
    },
    "S": {
        "deity": "Yama",
        "primary_mantra": "Om Yamaya Namah",
        "alternate_mantras": [],
        "element": "Earth / fire-adjacent",
    },
    "SW": {
        "deity": "Nirriti",
        "primary_mantra": "Om Nirritaye Namah",
        "alternate_mantras": ["Om"],  # a plain Om is often used here for grounding
        "element": "Prithvi (earth)",
    },
    "W": {
        "deity": "Varuna",
        "primary_mantra": "Om Varunaya Namah",
        "alternate_mantras": [],
        "element": "Water",
    },
    "NW": {
        "deity": "Vayu",
        "primary_mantra": "Om Vayave Namah",
        "alternate_mantras": [],
        "element": "Vayu (air)",
    },
    "N": {
        "deity": "Kubera",
        "primary_mantra": "Om Kuberaya Namah",
        "alternate_mantras": [],
        "element": "Water / wealth",
    },
}

#: The classical activation sequence (Prana Pratishtha), applied to any
#: recommended yantra/pyramid.
ACTIVATION_SEQUENCE: tuple[str, ...] = (
    "Personal and space purification (clean self and the area).",
    "Physical cleansing of the yantra/pyramid.",
    "Apply tilak on the central bindu.",
    "Offerings: ghee diya, incense, and fresh flowers.",
    "Core activation: chant the direction mantra 108 times (21-27 if time is limited), "
    "focusing on the bindu.",
    "Short aarti and gratitude, then install the item in its place.",
)

#: Repetition guidance for the direction mantra.
REPETITION_GUIDANCE: dict[str, Any] = {
    "full": 108,
    "short": "21-27",
    "daily_maintenance": "11 or 21 repetitions while keeping the area clean",
}

#: Timing guidance shown to the user.
AUSPICIOUS_TIMING: str = (
    "Traditionally performed on a Thursday or Monday morning during Shukla "
    "Paksha (the waxing-moon fortnight)."
)

#: Attached to every ritual block. Kept explicit so no product surface can
#: render the content without the disclaimer travelling with it.
RITUAL_DISCLAIMER: str = (
    "Traditional religious/ritual practice, provided as cultural context "
    "for the paired physical remedy. Not a validated intervention and not a "
    "substitute for structural correction; no outcome is claimed. Optional, "
    "and only meaningful to those who observe the tradition. Exact wording, "
    "counts, and timing should be confirmed with a consultant/priest."
)


def ritual_for_direction(direction: str) -> dict[str, Any]:
    """Return the full ritual/activation block for one direction.

    ``direction`` must be one of :data:`DIRECTIONS` (the 8 octants or
    ``"center"``). Raises ``ValueError`` for anything else rather than
    guessing a deity for an unrecognised direction.
    """
    if direction not in DIRECTION_DEITIES:
        raise ValueError(
            f"unknown direction {direction!r}; expected one of {DIRECTIONS}"
        )
    d = DIRECTION_DEITIES[direction]
    return {
        "direction": direction,
        "deity": d["deity"],
        "element": d["element"],
        "opening_mantra": dict(OPENING_MANTRA),
        "primary_mantra": d["primary_mantra"],
        "alternate_mantras": list(d["alternate_mantras"]),
        "activation_sequence": list(ACTIVATION_SEQUENCE),
        "repetitions": dict(REPETITION_GUIDANCE),
        "auspicious_timing": AUSPICIOUS_TIMING,
        "disclaimer": RITUAL_DISCLAIMER,
    }


def enrich_defects_with_ritual(
    defects: Iterable[dict[str, Any]],
    *,
    in_place: bool = False,
) -> list[dict[str, Any]]:
    """Attach a ``"ritual"`` block to each defect that carries a resolvable
    ``"direction"`` tag (see the ``direction`` fields added by
    ``vastu_audit``'s shape-defect and Brahmasthan checks).

    Defects without a ``"direction"``, or with one not in
    :data:`DIRECTION_DEITIES`, are returned unchanged (no ``"ritual"`` key) —
    this is not an error; most zone/adjacency violations don't carry a clean
    single-direction tag, and it is better to omit ritual content than to
    guess a deity.

    This function is pure content-attachment: it never changes severity,
    score, or any existing field. ``in_place=False`` (default) returns
    shallow copies so the caller's originals are untouched.
    """
    enriched: list[dict[str, Any]] = []
    for defect in defects:
        direction = defect.get("direction")
        if direction in DIRECTION_DEITIES:
            target = defect if in_place else dict(defect)
            target["ritual"] = ritual_for_direction(direction)
            enriched.append(target)
        else:
            enriched.append(defect if in_place else dict(defect))
    return enriched
