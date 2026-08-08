"""Selectable audit depth — and an honest manifest of what each depth covers.

WHY THIS EXISTS
---------------
``vastu_rule_schema.json``'s ``known_gaps[2]`` poses a question this codebase
had left open:

    "flag to product/legal whether the product's marketing claims 'full Vastu
    compliance' (which would require [the Ayadi/mandala layer]) or 'directional
    Vastu audit' (which this schema supports)."

This module resolves it by **not making the claim on the user's behalf**. The
user picks the depth they want, and every result carries a machine-readable
manifest of exactly what that depth did and did not examine.

That framing is deliberate. "Full Vastu" is a marketing phrase with no fixed
technical meaning, and different traditions would fill it differently. What this
module can honestly offer is a named, enumerated scope per mode — so a user who
selects the deeper mode learns what it added *and* what remains outside it,
rather than being sold completeness.

THE ANTI-OVER-CLAIM RULE
------------------------
:data:`UNIVERSAL_EXCLUSIONS` is attached to **every** mode, including the
deepest one. No mode in this module may ever present itself as complete Vastu
analysis, because none of them is: Ayadi Shadvarga, marma sthana, vithi shula,
and multi-storey variation are all absent from this engine, and per-pada
auspiciousness and devata names remain unsourced. If a future mode implements
one of these, it moves from this list to that mode's ``includes`` — the list
shrinking is the only honest way for coverage to grow.
"""

from __future__ import annotations

from typing import Any, Sequence

import geometry_engine as ge

#: Mode key used when a caller does not specify one. The conservative choice:
#: the layer the schema actually supports and a consultant could sign off on.
DEFAULT_MODE: str = "directional"

#: Attached to EVERY mode's manifest — see the anti-over-claim rule above.
#: These are the layers a practising consultant may cover that this engine does
#: not, regardless of selected depth.
UNIVERSAL_EXCLUSIONS: tuple[dict[str, str], ...] = (
    {
        "layer": "Ayadi Shadvarga (proportional calculations)",
        "status": "not implemented",
        "why": (
            "The six-fold proportional system (Aya, Vyaya, Yoni, Nakshatra, "
            "Vara, Tithi) requires multipliers and modulo constants that vary "
            "between classical texts and regional traditions. They must be "
            "sourced and cited, not reconstructed."
        ),
    },
    {
        "layer": "Marma sthana (vulnerable points)",
        "status": "not implemented",
        "why": (
            "Requires beam/column/load-bearing-wall geometry as input. This "
            "engine consumes room polygons only, so the structural elements "
            "the check is about are not available to it."
        ),
    },
    {
        "layer": "Vithi shula (road-thrust analysis)",
        "status": "not implemented",
        "why": (
            "Requires site context (surrounding road geometry) beyond the "
            "flat's own footprint."
        ),
    },
    {
        "layer": "Multi-storey variation",
        "status": "not implemented",
        "why": (
            "Zone rules shift by floor in some traditions. Every audit here "
            "assumes a single storey."
        ),
    },
    {
        "layer": "Per-pada auspiciousness and devata names",
        "status": "computed geometrically, ratings not sourced",
        "why": (
            "Pada LOCATION is exact. Pada MEANING (which pada is auspicious, "
            "which devata presides) varies across texts and is deliberately "
            "not guessed — see geometry_engine.entrance_pada(ratings=) and "
            "pada_devata_45(overrides=) for the injection points."
        ),
    },
    {
        "layer": "Consultant sign-off",
        "status": "outstanding",
        "why": (
            "vastu_rule_schema.json is v0.2.0 draft and its own _meta.status "
            "requires sign-off from a licensed Vastu consultant before "
            "production use. Severity weights and the compliance score are "
            "documented in-code as provisional."
        ),
    },
)

#: The selectable modes. ``includes`` is what the mode genuinely computes;
#: ``adds_over`` names the mode it builds on, so the UI can present them as a
#: ladder rather than as unrelated alternatives.
MODES: dict[str, dict[str, Any]] = {
    "directional": {
        "key": "directional",
        "label": "Directional Vastu audit",
        "tagline": "The 16-zone compass audit the rule schema supports.",
        "adds_over": None,
        "includes": [
            "Room-by-room zone compliance against the 16 compass sectors",
            "Adjacency and compound-constraint checks (e.g. pooja room sharing a toilet wall)",
            "Brahmasthan (true area centroid) obstruction checks",
            "Footprint shape diagnosis: hollow/external centre, cut and missing zones",
            "Object placement rules (bed, stove, desk, seating direction)",
            "Constructive placement suggestions where a solver exists",
        ],
        "description": (
            "Everything in this mode maps to a rule in vastu_rule_schema.json. "
            "It is the layer this project can defend end to end, and the layer "
            "a consultant would review first."
        ),
    },
    "full_mandala": {
        "key": "full_mandala",
        "label": "Extended mandala audit",
        "tagline": "Adds the Vastu Purusha Mandala pada grid on top of the directional audit.",
        "adds_over": "directional",
        "includes": [
            "Everything in the directional audit",
            "81-pada (9x9 Paramasayika) mandala grid with exact per-cell occupancy",
            "Which padas each room occupies, and by how much",
            "Main entrance located on the 32-cell perimeter pada ring by boundary intersection",
            "45-devata overlay (9 of 81 cells named from sourced references; 72 flagged for verification)",
        ],
        "description": (
            "The geometry here is exact and deterministic. The INTERPRETATION "
            "of it — which pada is auspicious, which devata presides — is not "
            "included, because it is not sourced. This mode tells you precisely "
            "where things sit on the mandala; it does not tell you what that "
            "means. Treat it as a higher-resolution measurement, not a verdict."
        ),
    },
}


def resolve_mode(mode: str | None) -> str:
    """Return a valid mode key, falling back to :data:`DEFAULT_MODE`.

    An unrecognised mode falls back rather than raising: this value arrives
    from a JSON payload over the wire, and an unknown string should degrade to
    the conservative audit rather than 500 the whole request. The resolved mode
    is always echoed back in the manifest, so a caller can see it was changed.

    The ``isinstance`` guard is load-bearing, not defensive noise: a JSON body
    can legitimately carry ``{"audit_mode": {}}`` or ``[]``, and testing an
    unhashable value against a dict raises ``TypeError``. Non-string input is
    simply not a mode name and falls back like any other unknown value.
    """
    if not isinstance(mode, str):
        return DEFAULT_MODE
    return mode if mode in MODES else DEFAULT_MODE


def coverage_manifest(mode: str) -> dict[str, Any]:
    """Describe what ``mode`` examined and what it did not.

    The ``excluded`` list always contains :data:`UNIVERSAL_EXCLUSIONS`,
    whatever the mode — see this module's anti-over-claim rule.
    """
    resolved = resolve_mode(mode)
    spec = MODES[resolved]
    return {
        "mode": resolved,
        "label": spec["label"],
        "tagline": spec["tagline"],
        "description": spec["description"],
        "adds_over": spec["adds_over"],
        "included": list(spec["includes"]),
        "excluded": [dict(item) for item in UNIVERSAL_EXCLUSIONS],
        "claim_note": (
            "This is a scoped analysis, not a certificate of Vastu compliance. "
            "The 'excluded' list applies to every mode offered here, including "
            "this one."
        ),
    }


def run_mandala_layer(
    boundary: Sequence[Any],
    rooms: Sequence[dict[str, Any]],
    north_offset_deg: float,
    entrance_room_names: Sequence[str] = ("MainEntrance",),
) -> dict[str, Any]:
    """Compute the extended-mode geometry: pada grid, devata overlay, entrance.

    Every sub-layer is independently fault-isolated. A malformed room polygon
    must not take down the pada grid, and a missing/interior entrance must not
    take down either — each failure is reported in its own ``*_error`` key so
    the caller can render partial results rather than losing the whole mode.

    Parameters
    ----------
    boundary
        The flat's boundary polygon. Required — without it there is no plot to
        inscribe a mandala on, and this function returns an ``error`` instead.
    rooms
        Room dicts as the UI supplies them (``name`` plus optional
        ``polygon``). Rooms without a polygon are skipped, not an error.
    north_offset_deg
        Plan's north offset, same convention as :mod:`zone_geometry`.
    entrance_room_names
        Which room names are treated as the main entrance for perimeter-pada
        location. Defaults to the schema's ``MainEntrance`` key.

    Returns
    -------
    dict
        ``{"pada_grid", "devata_overlay", "entrance"}``, any of which may
        instead be an error marker. Never raises for bad input.
    """
    if not boundary:
        return {"error": "no boundary polygon supplied; the mandala layer needs a plot outline"}

    named_polygons = [
        (room.get("name") or f"room_{i}", room["polygon"])
        for i, room in enumerate(rooms)
        if room.get("polygon")
    ]

    layer: dict[str, Any] = {}

    try:
        layer["pada_grid"] = ge.pada_grid(boundary, named_polygons, north_offset_deg)
    except (ValueError, TypeError) as exc:
        layer["pada_grid_error"] = str(exc)

    try:
        layer["devata_overlay"] = ge.pada_devata_45(boundary, named_polygons, north_offset_deg)
    except (ValueError, TypeError) as exc:
        layer["devata_overlay_error"] = str(exc)

    entrance = next(
        (r for r in rooms if r.get("name") in entrance_room_names and r.get("polygon")),
        None,
    )
    if entrance is None:
        layer["entrance_note"] = (
            "No room named "
            + " or ".join(entrance_room_names)
            + " with a polygon was supplied, so no entrance pada was located. "
            "Add the entrance as a small marker shape on the boundary wall to "
            "enable this check."
        )
    else:
        try:
            layer["entrance"] = ge.entrance_pada(
                boundary, entrance["polygon"], north_offset_deg
            )
        except (ValueError, TypeError) as exc:
            layer["entrance_error"] = str(exc)

    return layer
