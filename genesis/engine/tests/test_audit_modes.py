"""Unit tests for :mod:`audit_modes`.

The load-bearing test here is
``test_every_mode_carries_the_universal_exclusions``: the whole point of this
module is that no mode — however deep — can present itself as complete Vastu
analysis. That property is asserted across every mode, so adding a new mode
without its exclusions fails the suite.
"""

import json
from pathlib import Path

import pytest

import audit_modes as am

FIXTURE = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "flat_unit12_polygons.json").read_text()
)


# ---------------------------------------------------------------------------
# Mode resolution
# ---------------------------------------------------------------------------

def test_default_mode_is_the_conservative_one():
    assert am.DEFAULT_MODE == "directional"
    assert am.DEFAULT_MODE in am.MODES


@pytest.mark.parametrize("value", [None, "", "nonsense", "FULL_MANDALA", 42, [], {}])
def test_unrecognised_mode_degrades_rather_than_raising(value):
    # This arrives from a JSON payload over the wire; an unknown string must
    # not 500 the request.
    assert am.resolve_mode(value) == am.DEFAULT_MODE


@pytest.mark.parametrize("key", list(am.MODES))
def test_known_modes_resolve_to_themselves(key):
    assert am.resolve_mode(key) == key


# ---------------------------------------------------------------------------
# Coverage manifest — the anti-over-claim guarantee
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", list(am.MODES))
def test_every_mode_carries_the_universal_exclusions(key):
    """No mode may present itself as complete. This is the module's core promise."""
    manifest = am.coverage_manifest(key)
    excluded_layers = {e["layer"] for e in manifest["excluded"]}
    for universal in am.UNIVERSAL_EXCLUSIONS:
        assert universal["layer"] in excluded_layers, (
            f"mode {key!r} dropped the universal exclusion {universal['layer']!r}"
        )


@pytest.mark.parametrize("key", list(am.MODES))
def test_manifest_never_claims_completeness(key):
    manifest = am.coverage_manifest(key)
    assert manifest["excluded"], "a mode with no stated exclusions reads as a completeness claim"
    assert "not a certificate" in manifest["claim_note"].lower()


def test_ayadi_and_consultant_signoff_are_excluded_even_in_the_deepest_mode():
    layers = {e["layer"] for e in am.coverage_manifest("full_mandala")["excluded"]}
    assert any("Ayadi" in l for l in layers)
    assert any("sign-off" in l for l in layers)


def test_manifest_of_unknown_mode_falls_back_and_says_so():
    manifest = am.coverage_manifest("nonsense")
    assert manifest["mode"] == am.DEFAULT_MODE


def test_extended_mode_declares_what_it_builds_on():
    assert am.MODES["directional"]["adds_over"] is None
    assert am.MODES["full_mandala"]["adds_over"] == "directional"


# ---------------------------------------------------------------------------
# Mandala layer
# ---------------------------------------------------------------------------

def test_mandala_layer_on_the_real_fixture():
    layer = am.run_mandala_layer(
        FIXTURE["boundary"], FIXTURE["rooms"], FIXTURE["north_offset_deg"]
    )
    assert len(layer["pada_grid"]["cells"]) == 81
    assert layer["devata_overlay"]["order"] == 9
    assert layer["entrance"]["ring_size"] == 32
    assert layer["entrance"]["primary"]["side"]  # a compass side was resolved


def test_mandala_layer_without_boundary_reports_error_not_exception():
    layer = am.run_mandala_layer(None, FIXTURE["rooms"], 0.0)
    assert "error" in layer
    assert "boundary" in layer["error"]


def test_mandala_layer_without_entrance_room_explains_how_to_enable_it():
    rooms = [r for r in FIXTURE["rooms"] if r["name"] != "MainEntrance"]
    layer = am.run_mandala_layer(FIXTURE["boundary"], rooms, FIXTURE["north_offset_deg"])
    assert "entrance" not in layer
    assert "entrance_note" in layer
    assert "MainEntrance" in layer["entrance_note"]
    # The rest of the layer must still be computed.
    assert len(layer["pada_grid"]["cells"]) == 81


def test_malformed_room_polygon_does_not_take_down_the_whole_layer():
    rooms = list(FIXTURE["rooms"]) + [{"name": "Broken", "polygon": [[0, 0], [1, 1]]}]
    layer = am.run_mandala_layer(FIXTURE["boundary"], rooms, FIXTURE["north_offset_deg"])
    # Sub-layers are independently isolated: a degenerate polygon fails the
    # grid/overlay but must not stop the entrance from being located.
    assert "entrance" in layer
    assert "pada_grid" in layer or "pada_grid_error" in layer


def test_rooms_without_polygons_are_skipped_not_errors():
    rooms = [{"name": "NoPolygon", "zone": "N"}] + list(FIXTURE["rooms"])
    layer = am.run_mandala_layer(FIXTURE["boundary"], rooms, FIXTURE["north_offset_deg"])
    assert len(layer["pada_grid"]["cells"]) == 81
    occupancy_names = set()
    for cell in layer["pada_grid"]["cells"]:
        occupancy_names.update(cell["room_occupancy"])
    assert "NoPolygon" not in occupancy_names


def test_interior_entrance_polygon_is_reported_as_an_error_not_guessed():
    # An entrance marker that doesn't touch the perimeter is a real input
    # error; it must surface rather than being snapped to a nearest pada.
    rooms = [{"name": "MainEntrance", "polygon": [[18, 18], [19, 18], [19, 19], [18, 19]]}]
    layer = am.run_mandala_layer(FIXTURE["boundary"], rooms, FIXTURE["north_offset_deg"])
    assert "entrance" not in layer
    assert "entrance_error" in layer
