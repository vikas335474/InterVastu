# InterVastu

## `orientation.py` — facade-orientation detection

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

## `zone_geometry.py` — deterministic zone-assignment layer

Assigns each room in a flat to one of the 16 Vastu compass sectors relative
to the flat's true geometric centre (Brahmasthan), computed as the
occupied-area polygon centroid rather than a bounding-box centre. See the
module docstring for the full coordinate/bearing conventions.
