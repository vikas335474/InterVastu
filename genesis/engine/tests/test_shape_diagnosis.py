"""Unit tests for :func:`zone_geometry.diagnose_shape` — the footprint-level
dual-centre (hollow / high-offset) check and cut/missing-zone detection.

The headline case (test 2) is the one a bounding box hides and a naive
centroid-only check under-reports: a U-shaped flat whose true centroid falls
in open space OUTSIDE the footprint, even though its centroid<->bbox-centre
offset is small. Both facts are asserted together so a future refactor can't
quietly collapse the two independent conditions back into one.
"""

import pytest

import zone_geometry as zg


# ---------------------------------------------------------------------------
# 1. A plain rectangle has no shape defect at all.
# ---------------------------------------------------------------------------

def test_rectangle_has_no_shape_defect():
    boundary = [(0, 0), (40, 0), (40, 30), (0, 30)]
    d = zg.diagnose_shape(boundary)

    # Centroid == bbox centre == geometric middle.
    assert d["centroid"] == {"x": 20.0, "y": 15.0}
    assert d["bbox_center"] == {"x": 20.0, "y": 15.0}
    assert d["center_offset_ft"] == pytest.approx(0.0)
    assert d["center_offset_fraction"] == pytest.approx(0.0)
    assert d["high_center_offset"] is False
    assert d["centroid_inside_boundary"] is True
    assert d["hollow_center"] is False
    assert d["footprint_fill_fraction"] == pytest.approx(1.0)
    assert d["missing_zones"] == []


# ---------------------------------------------------------------------------
# 2. U-shaped flat: HOLLOW CENTRE with a SMALL offset (the two conditions are
#    independent — this is the whole reason the dual check exists).
# ---------------------------------------------------------------------------

def test_u_shape_has_external_centroid_despite_small_offset():
    # 30x30 outer square with a rectangular notch cut from the top middle
    # (x 10..20, y 10..30). Opening faces "up" (+y).
    boundary = [
        (0, 0), (30, 0), (30, 30), (20, 30),
        (20, 10), (10, 10), (10, 30), (0, 30),
    ]
    d = zg.diagnose_shape(boundary, north_offset_deg=0.0)

    # By symmetry the centroid is on the x=15 line, pulled DOWN by the notch.
    assert d["centroid"]["x"] == pytest.approx(15.0)
    assert d["centroid"]["y"] < 15.0  # below the bbox centre

    # The offset from the bbox centre is SMALL — a magnitude-only check would
    # miss this defect entirely.
    assert d["center_offset_fraction"] < zg.DEFAULT_CENTER_OFFSET_FRACTION_THRESHOLD
    assert d["high_center_offset"] is False

    # ...but the centroid is nonetheless OUTSIDE the footprint (it sits in the
    # notch), which is the critical hollow-centre defect.
    assert d["centroid_inside_boundary"] is False
    assert d["hollow_center"] is True

    # The notch is reported as a missing N zone (it sits due north of centre).
    assert [mz["octant"] for mz in d["missing_zones"]] == ["N"]
    assert d["missing_zones"][0]["area_fraction"] == pytest.approx(200.0 / 900.0)


# ---------------------------------------------------------------------------
# 3. L-shaped flat: centroid stays INSIDE but the offset is large, and the
#    cut corner is reported as a missing ordinal zone.
# ---------------------------------------------------------------------------

def test_l_shape_high_offset_and_missing_corner():
    # 40x40 square with the top-right quadrant (x 20..40, y 20..40) removed.
    boundary = [(0, 0), (40, 0), (40, 20), (20, 20), (20, 40), (0, 40)]
    # north_offset 0 => plan +y is true north, +x is true east, so the cut
    # top-right corner is to the NE of centre.
    d = zg.diagnose_shape(boundary, north_offset_deg=0.0)

    assert d["centroid_inside_boundary"] is True
    assert d["hollow_center"] is False
    # A quadrant removed from a square shifts the centroid strongly SW.
    assert d["high_center_offset"] is True

    octants = [mz["octant"] for mz in d["missing_zones"]]
    assert octants == ["NE"]
    assert d["missing_zones"][0]["area_fraction"] == pytest.approx(400.0 / 1600.0)


# ---------------------------------------------------------------------------
# 4. north_offset rotates the reported missing octant.
# ---------------------------------------------------------------------------

def test_missing_octant_rotates_with_north_offset():
    boundary = [(0, 0), (40, 0), (40, 20), (20, 20), (20, 40), (0, 40)]
    # Rotate the whole compass frame by 90 deg: plan +y now points true East,
    # so the cut that was NE becomes SE.
    d = zg.diagnose_shape(boundary, north_offset_deg=90.0)
    assert [mz["octant"] for mz in d["missing_zones"]] == ["SE"]


# ---------------------------------------------------------------------------
# 5. Sub-threshold slivers (tracing tolerance) are NOT reported.
# ---------------------------------------------------------------------------

def test_tiny_notch_below_threshold_is_ignored():
    # A 40x30 rectangle with a 1x1 nick out of one corner: 1 / 1200 of the
    # bbox, far below the 3% default missing-zone threshold.
    boundary = [(0, 0), (40, 0), (40, 30), (1, 30), (1, 29), (0, 29)]
    d = zg.diagnose_shape(boundary)
    assert d["missing_zones"] == []


def test_threshold_parameters_are_honoured():
    boundary = [(0, 0), (40, 0), (40, 30), (1, 30), (1, 29), (0, 29)]
    # Drop the threshold below the sliver's fraction and it now shows up.
    d = zg.diagnose_shape(boundary, missing_zone_area_fraction_threshold=1e-6)
    assert len(d["missing_zones"]) == 1
