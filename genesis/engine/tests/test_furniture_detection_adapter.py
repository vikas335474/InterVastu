"""Unit tests for furniture_detection_adapter.py.

Coordinate convention (confirmed against solver.py's own wall/quadrant
geometry, facade_bearing=0.0): for an axis-aligned rectangle, the y=0 edge
faces S, the y=max edge faces N, the x=0 edge faces W, and the x=max edge
faces E. Every fixture below places a detection bounding box a small,
fixed distance from one edge so its centroid is unambiguously "flush"
against that wall.
"""

import pytest

import furniture_detection_adapter as fda


MASTER_BEDROOM = [(0, 0), (12, 0), (12, 14), (0, 14)]  # same shape as test_solver.py
KITCHEN = [(0, 0), (10, 0), (10, 8), (0, 8)]
LIVING_ROOM = [(0, 0), (10, 0), (10, 12), (0, 12)]


def _bed(bbox, confidence=0.9, cls="bed"):
    return {"class": cls, "bbox": bbox, "confidence": confidence}


# ---------------------------------------------------------------------------
# Bed -> MasterBedroom / GuestBedroom / ChildrenBedroom
# ---------------------------------------------------------------------------

def test_bed_flush_south_wall_satisfies_preferred_direction():
    detection = _bed([3, 0, 9, 2])  # centroid (6, 1) -> flush against S wall
    result = fda.check_detected_furniture("MasterBedroom", MASTER_BEDROOM, [detection])

    assert result["room"] == "MasterBedroom"
    assert len(result["checks"]) == 1
    check = result["checks"][0]
    assert check["object"] == "bed"
    assert check["matched_class"] == "bed"
    assert check["facing_quadrant"] == "S"
    assert check["satisfies_rule"] is True
    assert check["note"] is None
    assert check["source"] == "ml_detection"
    assert check["detection_confidence"] == pytest.approx(0.9)
    assert all(len(v) == 0 for v in result["skipped"].values())


def test_bed_flush_north_wall_is_forbidden_direction():
    detection = _bed([3, 12, 9, 14])  # centroid (6, 13) -> flush against N wall
    result = fda.check_detected_furniture("MasterBedroom", MASTER_BEDROOM, [detection])

    check = result["checks"][0]
    assert check["facing_quadrant"] == "N"
    assert check["satisfies_rule"] is False
    assert "forbidden" in check["note"]


@pytest.mark.parametrize("room_name", ["GuestBedroom", "ChildrenBedroom"])
def test_bed_rule_generalises_to_guest_and_children_bedrooms(room_name):
    detection = _bed([3, 0, 9, 2], cls="bed2")
    result = fda.check_detected_furniture(room_name, MASTER_BEDROOM, [detection])

    assert len(result["checks"]) == 1
    check = result["checks"][0]
    assert check["room"] == room_name
    assert check["matched_class"] == "bed2"
    assert check["satisfies_rule"] is True


# ---------------------------------------------------------------------------
# Stove -> Kitchen
# ---------------------------------------------------------------------------

def test_stove_flush_east_wall_satisfies_preferred_direction():
    detection = {"class": "stove", "bbox": [8, 3, 10, 5], "confidence": 0.8}
    result = fda.check_detected_furniture("Kitchen", KITCHEN, [detection])

    check = result["checks"][0]
    assert check["object"] == "stove"
    assert check["facing_quadrant"] == "E"
    assert check["satisfies_rule"] is True


# ---------------------------------------------------------------------------
# Sofa -> LivingRoom (heavy_furniture)
# ---------------------------------------------------------------------------

def test_sofa_flush_south_wall_satisfies_preferred_direction():
    detection = {"class": "sofa1", "bbox": [3, 0, 7, 2], "confidence": 0.95}
    result = fda.check_detected_furniture("LivingRoom", LIVING_ROOM, [detection])

    check = result["checks"][0]
    assert check["object"] == "heavy_furniture"
    assert check["facing_quadrant"] == "S"
    assert check["satisfies_rule"] is True


def test_sofa_flush_north_wall_is_forbidden_direction():
    detection = {"class": "sofa2", "bbox": [3, 10, 7, 12], "confidence": 0.95}
    result = fda.check_detected_furniture("LivingRoom", LIVING_ROOM, [detection])

    check = result["checks"][0]
    assert check["facing_quadrant"] == "N"
    assert check["satisfies_rule"] is False
    assert "forbidden" in check["note"]


# ---------------------------------------------------------------------------
# Skip categories -- every input detection must land in checks or skipped,
# never silently vanish.
# ---------------------------------------------------------------------------

def test_low_confidence_detection_is_skipped_not_dropped():
    detection = _bed([3, 0, 9, 2], confidence=0.2)
    result = fda.check_detected_furniture("MasterBedroom", MASTER_BEDROOM, [detection])

    assert result["checks"] == []
    assert result["skipped"]["low_confidence"] == [detection]


def test_unsupported_class_is_skipped():
    detection = {"class": "toilet", "bbox": [0, 0, 2, 2], "confidence": 0.9}
    result = fda.check_detected_furniture("MasterBedroom", MASTER_BEDROOM, [detection])

    assert result["checks"] == []
    assert result["skipped"]["unsupported_class"] == [detection]


def test_unsupported_room_is_skipped():
    detection = _bed([3, 0, 9, 2])
    result = fda.check_detected_furniture("StudyRoom", MASTER_BEDROOM, [detection])

    assert result["checks"] == []
    assert result["skipped"]["unsupported_room"] == [detection]


def test_freestanding_item_not_flush_to_any_wall_is_skipped():
    # centroid (6, 7) is 6 ft from the nearest wall in a 12x14 room --
    # well beyond the default 2 ft wall-flush margin.
    detection = _bed([5, 6, 7, 8])
    result = fda.check_detected_furniture("MasterBedroom", MASTER_BEDROOM, [detection])

    assert result["checks"] == []
    assert result["skipped"]["not_wall_flush"] == [detection]


def test_malformed_bbox_is_skipped():
    detection = {"class": "bed", "bbox": [1, 2, 3], "confidence": 0.9}
    result = fda.check_detected_furniture("MasterBedroom", MASTER_BEDROOM, [detection])

    assert result["checks"] == []
    assert result["skipped"]["malformed"] == [detection]


def test_every_detection_is_accounted_for_exactly_once():
    detections = [
        _bed([3, 0, 9, 2]),                                    # accepted
        _bed([3, 0, 9, 2], confidence=0.1),                    # low_confidence
        {"class": "toilet", "bbox": [0, 0, 2, 2], "confidence": 0.9},  # unsupported_class
        _bed([5, 6, 7, 8]),                                    # not_wall_flush
        {"class": "bed", "bbox": [1, 2, 3], "confidence": 0.9},  # malformed
    ]
    result = fda.check_detected_furniture("MasterBedroom", MASTER_BEDROOM, detections)

    total_accounted = len(result["checks"]) + sum(len(v) for v in result["skipped"].values())
    assert total_accounted == len(detections)
    assert result["reliability_note"] == fda.ML_DETECTION_RELIABILITY_NOTE


# ---------------------------------------------------------------------------
# solver.nearest_wall -- the new public helper this adapter is built on.
# ---------------------------------------------------------------------------

def test_solver_nearest_wall_matches_known_quadrant_convention():
    import solver as sv

    assert sv.nearest_wall(MASTER_BEDROOM, (6, 0.05), facade_bearing=0.0)["wall"]["quadrant"] == "S"
    assert sv.nearest_wall(MASTER_BEDROOM, (6, 13.95), facade_bearing=0.0)["wall"]["quadrant"] == "N"
    assert sv.nearest_wall(MASTER_BEDROOM, (0.05, 7), facade_bearing=0.0)["wall"]["quadrant"] == "W"
    assert sv.nearest_wall(MASTER_BEDROOM, (11.95, 7), facade_bearing=0.0)["wall"]["quadrant"] == "E"
