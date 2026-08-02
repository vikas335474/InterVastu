"""Structural regression tests for :mod:`zone_geometry`, driven by a sample
of real (non-synthetic) floor-plan boundaries from the HouseExpo dataset.

See ``genesis/engine/fixtures/houseexpo_sample/README.md`` for exactly what
these fixtures are, their provenance/license, and how they were selected.

WHAT THIS DOES NOT TEST
------------------------
HouseExpo carries no Vastu ground truth, no compass/orientation metadata,
and its room-category labels (Kitchen, Bedroom, Office, Lobby, ...) are
generic room types, not Vastu zones or even India-specific layouts. Nothing
here asserts that a particular zone assignment, shape diagnosis, or
Brahmasthan check is *correct* in the Vastu sense -- that is exactly what
the hand-built, Vastu-labelled fixtures (Unit 12, ``test_zone_geometry.py``)
are for.

WHAT THIS DOES TEST
--------------------
Only structural/robustness invariants that must hold for ANY valid input,
run across 40 real, often irregular or noisy boundaries the hand-built
fixtures don't cover (including 3 that are self-intersecting per Shapely's
own ``is_valid`` check, deliberately kept to exercise the ``buffer(0)``
repair path in ``zone_geometry._to_polygon`` on real rather than synthetic
invalid input):

  * ``diagnose_shape()`` and ``analyze_zones()`` never raise on any fixture.
  * Every field that is documented to always be present, is present, and
    has the documented type/range (booleans are booleans, zones are one of
    ``SECTORS``/``OCTANTS`` or ``None``, fractions are non-negative, ...).
  * A couple of cross-field consistency invariants that follow directly
    from the module's own docstrings (e.g. ``hollow_center`` is exactly the
    negation of ``centroid_inside_boundary``).

Room polygons are approximated from HouseExpo's per-room-category bounding
boxes (HouseExpo does not provide full room polygons), which is sufficient
for these structural checks -- ``zone_geometry`` makes no assumption that a
room polygon is the room's *true* outline.
"""

import json
from pathlib import Path

import pytest

import zone_geometry as zg

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "houseexpo_sample"


def _load_houseexpo_fixtures():
    paths = sorted(FIXTURES_DIR.glob("*.json"))
    if not paths:
        pytest.skip(f"no HouseExpo sample fixtures found in {FIXTURES_DIR}")
    fixtures = []
    for path in paths:
        data = json.loads(path.read_text())
        boundary = [tuple(v) for v in data["verts"]]
        rooms = []
        for category, boxes in data["room_category"].items():
            for i, (minx, miny, maxx, maxy) in enumerate(boxes):
                polygon = [(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy)]
                rooms.append((f"{category}_{i}", polygon))
        fixtures.append(pytest.param(boundary, rooms, id=data["id"]))
    return fixtures


HOUSEEXPO_FIXTURES = _load_houseexpo_fixtures()


def test_houseexpo_sample_has_expected_fixture_count():
    # Pinned so a future accidental deletion/truncation of the sample
    # directory fails loudly here rather than silently shrinking coverage.
    assert len(HOUSEEXPO_FIXTURES) == 40


@pytest.mark.parametrize("boundary, rooms", HOUSEEXPO_FIXTURES)
def test_diagnose_shape_never_raises_and_is_well_formed(boundary, rooms):
    result = zg.diagnose_shape(boundary)

    # --- presence + type of every documented field ---------------------
    assert isinstance(result["centroid"]["x"], float)
    assert isinstance(result["centroid"]["y"], float)
    assert isinstance(result["bbox_center"]["x"], float)
    assert isinstance(result["bbox_center"]["y"], float)
    assert isinstance(result["center_offset_ft"], float)
    assert result["center_offset_ft"] >= 0.0
    assert isinstance(result["center_offset_fraction"], float)
    assert result["center_offset_fraction"] >= 0.0
    assert isinstance(result["high_center_offset"], bool)
    assert isinstance(result["centroid_inside_boundary"], bool)
    assert isinstance(result["hollow_center"], bool)

    # --- cross-field consistency, straight from the module docstring ---
    assert result["hollow_center"] is (not result["centroid_inside_boundary"])

    fill_fraction = result["footprint_fill_fraction"]
    assert fill_fraction is not None  # bbox_area > 0 for every real house
    assert 0.0 < fill_fraction <= 1.0

    for entry in result["missing_zones"]:
        assert entry["octant"] in zg.OCTANTS
        assert all(z in zg.SECTORS for z in entry["zones"])
        assert entry["area_ft2"] >= 0.0
        assert 0.0 <= entry["area_fraction"] <= 1.0


@pytest.mark.parametrize("boundary, rooms", HOUSEEXPO_FIXTURES)
def test_analyze_zones_never_raises_and_is_well_formed(boundary, rooms):
    result = zg.analyze_zones(boundary, rooms, north_offset_deg=0.0)

    assert isinstance(result["centre"]["x"], float)
    assert isinstance(result["centre"]["y"], float)
    assert len(result["rooms"]) == len(rooms)

    for record in result["rooms"]:
        # A room whose centroid coincides exactly with the plot centre is
        # the one documented exception: zone/bearing/margin/confidence are
        # all None rather than a guessed direction.
        if record["zone"] is None:
            assert record["bearing_deg"] is None
            assert record["zone_confidence"] is None
            assert record["boundary_margin_deg"] is None
            continue

        assert record["zone"] in zg.SECTORS
        assert record["zone_confidence"] in ("low", "high")
        assert 0.0 <= record["bearing_deg"] < 360.0
        assert 0.0 <= record["boundary_margin_deg"] <= zg.SECTOR_HALF_WIDTH_DEG

        assert isinstance(record["contains_centre_point"], bool)
        assert isinstance(record["overlaps_brahmasthan_region"], bool)
        assert 0.0 <= record["region_overlap_fraction"] <= 1.0
        if record["nearest_distance_ft"] is not None:
            assert 0.0 <= record["nearest_distance_ft"] < zg.NEAR_MISS_FT
