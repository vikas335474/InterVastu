"""Unit tests for storage.py, the SQLite persistence layer.

Each test opens a fresh on-disk SQLite file in a pytest tmp_path so tests
never share or leak state (and never touch the real ui/vastu_ui.db).
"""

import pytest

import storage


@pytest.fixture
def conn(tmp_path):
    c = storage.open_db(tmp_path / "test.db")
    yield c
    c.close()


SAMPLE_INPUT = {"plot": {"shape": "rectangle"}, "rooms": [{"name": "Kitchen", "zone": "SE"}]}
SAMPLE_RESULT = {"compliance_score": 100, "major_count": 0, "minor_count": 0}


def test_create_flat_creates_version_one(conn):
    flat_id = storage.create_flat(conn, "My Flat", "vikas", SAMPLE_INPUT, SAMPLE_RESULT)
    assert flat_id is not None

    flat = storage.get_flat(conn, flat_id)
    assert flat["label"] == "My Flat"
    assert flat["owner"] == "vikas"
    assert len(flat["versions"]) == 1
    assert flat["versions"][0]["version_number"] == 1
    assert flat["versions"][0]["input"] == SAMPLE_INPUT
    assert flat["versions"][0]["result"] == SAMPLE_RESULT


def test_get_flat_returns_none_for_missing_id(conn):
    assert storage.get_flat(conn, 999) is None


def test_add_version_increments_version_number(conn):
    flat_id = storage.create_flat(conn, "My Flat", "vikas", SAMPLE_INPUT, SAMPLE_RESULT)

    edited_input = {"plot": {"shape": "rectangle"}, "rooms": [{"name": "Kitchen", "zone": "NE"}]}
    edited_result = {"compliance_score": 90, "major_count": 1, "minor_count": 0}
    version = storage.add_version(conn, flat_id, edited_input, edited_result, note="moved kitchen")

    assert version == 2
    flat = storage.get_flat(conn, flat_id)
    assert len(flat["versions"]) == 2
    assert flat["versions"][1]["version_number"] == 2
    assert flat["versions"][1]["input"] == edited_input
    assert flat["versions"][1]["note"] == "moved kitchen"

    # Original version is still there, unchanged -- editing never overwrites.
    assert flat["versions"][0]["input"] == SAMPLE_INPUT
    assert flat["versions"][0]["result"] == SAMPLE_RESULT


def test_add_version_to_missing_flat_raises_value_error(conn):
    with pytest.raises(ValueError):
        storage.add_version(conn, 999, SAMPLE_INPUT, SAMPLE_RESULT)


def test_get_version_returns_specific_version(conn):
    flat_id = storage.create_flat(conn, "My Flat", "vikas", SAMPLE_INPUT, SAMPLE_RESULT)
    storage.add_version(conn, flat_id, SAMPLE_INPUT, {"compliance_score": 80})

    v1 = storage.get_version(conn, flat_id, 1)
    v2 = storage.get_version(conn, flat_id, 2)
    assert v1["result"] == SAMPLE_RESULT
    assert v2["result"] == {"compliance_score": 80}


def test_get_version_returns_none_for_missing_version(conn):
    flat_id = storage.create_flat(conn, "My Flat", "vikas", SAMPLE_INPUT, SAMPLE_RESULT)
    assert storage.get_version(conn, flat_id, 5) is None


def test_list_flats_uses_latest_version_for_summary(conn):
    flat_id = storage.create_flat(conn, "My Flat", "vikas", SAMPLE_INPUT, SAMPLE_RESULT)
    storage.add_version(
        conn, flat_id, SAMPLE_INPUT,
        {"compliance_score": 70, "major_count": 2, "minor_count": 1},
    )

    summaries = storage.list_flats(conn)
    assert len(summaries) == 1
    s = summaries[0]
    assert s["id"] == flat_id
    assert s["latest_version"] == 2
    assert s["latest_compliance_score"] == 70
    assert s["latest_major_count"] == 2
    assert s["latest_minor_count"] == 1


def test_list_flats_covers_multiple_flats_and_owners(conn):
    storage.create_flat(conn, "Flat A", "alice", SAMPLE_INPUT, SAMPLE_RESULT)
    storage.create_flat(conn, "Flat B", "bob", SAMPLE_INPUT, SAMPLE_RESULT)

    summaries = storage.list_flats(conn)
    owners = {s["owner"] for s in summaries}
    assert owners == {"alice", "bob"}


def test_delete_flat_removes_flat_and_versions(conn):
    flat_id = storage.create_flat(conn, "My Flat", "vikas", SAMPLE_INPUT, SAMPLE_RESULT)
    storage.add_version(conn, flat_id, SAMPLE_INPUT, SAMPLE_RESULT)

    assert storage.delete_flat(conn, flat_id) is True
    assert storage.get_flat(conn, flat_id) is None
    # Cascade removed the versions row(s) too -- no orphans left in flat_versions.
    orphans = conn.execute(
        "SELECT COUNT(*) AS n FROM flat_versions WHERE flat_id = ?", (flat_id,)
    ).fetchone()["n"]
    assert orphans == 0


def test_delete_flat_returns_false_for_missing_flat(conn):
    assert storage.delete_flat(conn, 999) is False


def test_open_db_is_idempotent_on_existing_file(tmp_path):
    """Reopening the same file (e.g. server restart) must not error or wipe data."""
    db_path = tmp_path / "persist.db"
    c1 = storage.open_db(db_path)
    flat_id = storage.create_flat(c1, "My Flat", "vikas", SAMPLE_INPUT, SAMPLE_RESULT)
    c1.close()

    c2 = storage.open_db(db_path)
    flat = storage.get_flat(c2, flat_id)
    assert flat is not None
    assert flat["label"] == "My Flat"
    c2.close()
