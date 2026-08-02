"""Unit tests for the OPTIONAL ritual_protocol enrichment layer.

These verify the authentic directional-deity mapping, the always-present
disclaimer, and — importantly — that enrichment is purely additive: it
attaches content only to defects with a resolvable "direction", never
changes severity/score fields, and never guesses a deity for an unknown or
missing direction.
"""

import pytest

import ritual_protocol as rp


# ---------------------------------------------------------------------------
# 1. Directional deity map: authentic lokapalas, all directions covered.
# ---------------------------------------------------------------------------

def test_all_directions_have_a_deity_and_mantra():
    for direction in rp.DIRECTIONS:
        block = rp.ritual_for_direction(direction)
        assert block["deity"]
        assert block["primary_mantra"].startswith("Om")
        # Every block opens with the Ganesha obstacle-removal invocation.
        assert block["opening_mantra"]["mantra"] == "Om Gam Ganapataye Namah"
        # And every block carries the disclaimer, unconditionally.
        assert block["disclaimer"]
        assert "not a validated" in block["disclaimer"].lower()


@pytest.mark.parametrize("direction,deity_substr,mantra", [
    ("NE", "Ishana", "Om Namah Shivaya"),
    ("SE", "Agni", "Om Agnaye Namah"),
    ("S", "Yama", "Om Yamaya Namah"),
    ("SW", "Nirriti", "Om Nirritaye Namah"),
    ("W", "Varuna", "Om Varunaya Namah"),
    ("NW", "Vayu", "Om Vayave Namah"),
    ("N", "Kubera", "Om Kuberaya Namah"),
    ("center", "Brahma", "Om Brahmane Namah"),
])
def test_specific_directional_deities(direction, deity_substr, mantra):
    block = rp.ritual_for_direction(direction)
    assert deity_substr in block["deity"]
    assert block["primary_mantra"] == mantra


def test_unknown_direction_raises_rather_than_guessing():
    with pytest.raises(ValueError):
        rp.ritual_for_direction("NNE")  # a 16-sector label, not an octant
    with pytest.raises(ValueError):
        rp.ritual_for_direction("nowhere")


# ---------------------------------------------------------------------------
# 2. Enrichment is additive and never fabricates a direction.
# ---------------------------------------------------------------------------

def test_enrichment_attaches_ritual_to_directional_defects():
    defects = [
        {"rule_type": "hollow_center", "severity": "major", "direction": "center"},
        {"rule_type": "missing_zone", "severity": "major", "direction": "NE"},
    ]
    out = rp.enrich_defects_with_ritual(defects)

    assert out[0]["ritual"]["direction"] == "center"
    assert "Brahma" in out[0]["ritual"]["deity"]
    assert out[1]["ritual"]["direction"] == "NE"
    # Severity is untouched by enrichment.
    assert out[0]["severity"] == "major" and out[1]["severity"] == "major"


def test_enrichment_skips_defects_without_a_direction():
    defects = [
        {"rule_type": "zone", "severity": "minor"},               # no direction
        {"rule_type": "missing_zone", "severity": "minor", "direction": "X"},  # bad dir
    ]
    out = rp.enrich_defects_with_ritual(defects)
    assert "ritual" not in out[0]
    assert "ritual" not in out[1]


def test_enrichment_does_not_mutate_input_by_default():
    defects = [{"rule_type": "hollow_center", "direction": "center"}]
    out = rp.enrich_defects_with_ritual(defects)
    assert "ritual" not in defects[0]      # original untouched
    assert "ritual" in out[0]              # copy enriched


def test_enrichment_in_place_mutates():
    defects = [{"rule_type": "hollow_center", "direction": "center"}]
    out = rp.enrich_defects_with_ritual(defects, in_place=True)
    assert out[0] is defects[0]
    assert "ritual" in defects[0]
