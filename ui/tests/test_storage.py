"""Unit tests for storage.py, the SQLite persistence layer (users,
sessions, flats/flat_versions).

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


@pytest.fixture
def user_id(conn):
    return storage.create_user(conn, "vikas", "not-a-real-hash")


SAMPLE_INPUT = {"plot": {"shape": "rectangle"}, "rooms": [{"name": "Kitchen", "zone": "SE"}]}
SAMPLE_RESULT = {"compliance_score": 100, "major_count": 0, "minor_count": 0}


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def test_create_user_and_look_up_by_username(conn):
    user_id = storage.create_user(conn, "alice", "hash123")
    user = storage.get_user_by_username(conn, "alice")
    assert user["id"] == user_id
    assert user["username"] == "alice"
    assert user["password_hash"] == "hash123"


def test_create_user_duplicate_username_raises_value_error(conn):
    storage.create_user(conn, "alice", "hash123")
    with pytest.raises(ValueError):
        storage.create_user(conn, "alice", "different-hash")


def test_get_user_by_username_returns_none_when_missing(conn):
    assert storage.get_user_by_username(conn, "nobody") is None


def test_get_user_by_id_excludes_password_hash(conn):
    user_id = storage.create_user(conn, "alice", "hash123")
    user = storage.get_user_by_id(conn, user_id)
    assert user["username"] == "alice"
    assert "password_hash" not in user


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def test_create_session_and_look_up_user(conn, user_id):
    storage.create_session(conn, user_id, "tok-123")
    user = storage.get_session_user(conn, "tok-123")
    assert user["id"] == user_id
    assert user["username"] == "vikas"


def test_get_session_user_returns_none_for_unknown_token(conn):
    assert storage.get_session_user(conn, "no-such-token") is None


def test_delete_session_revokes_it(conn, user_id):
    storage.create_session(conn, user_id, "tok-123")
    storage.delete_session(conn, "tok-123")
    assert storage.get_session_user(conn, "tok-123") is None


def test_delete_session_is_a_no_op_for_unknown_token(conn):
    storage.delete_session(conn, "never-existed")  # must not raise


# ---------------------------------------------------------------------------
# Flats + versions
# ---------------------------------------------------------------------------

def test_create_flat_creates_version_one(conn, user_id):
    flat_id = storage.create_flat(conn, "My Flat", user_id, SAMPLE_INPUT, SAMPLE_RESULT)
    assert flat_id is not None

    flat = storage.get_flat(conn, flat_id, user_id)
    assert flat["label"] == "My Flat"
    assert len(flat["versions"]) == 1
    assert flat["versions"][0]["version_number"] == 1
    assert flat["versions"][0]["input"] == SAMPLE_INPUT
    assert flat["versions"][0]["result"] == SAMPLE_RESULT


def test_get_flat_returns_none_for_missing_id(conn, user_id):
    assert storage.get_flat(conn, 999, user_id) is None


def test_get_flat_returns_none_for_another_users_flat(conn, user_id):
    other_user_id = storage.create_user(conn, "bob", "hash456")
    flat_id = storage.create_flat(conn, "My Flat", user_id, SAMPLE_INPUT, SAMPLE_RESULT)

    assert storage.get_flat(conn, flat_id, other_user_id) is None
    assert storage.get_flat(conn, flat_id, user_id) is not None


def test_add_version_increments_version_number(conn, user_id):
    flat_id = storage.create_flat(conn, "My Flat", user_id, SAMPLE_INPUT, SAMPLE_RESULT)

    edited_input = {"plot": {"shape": "rectangle"}, "rooms": [{"name": "Kitchen", "zone": "NE"}]}
    edited_result = {"compliance_score": 90, "major_count": 1, "minor_count": 0}
    version = storage.add_version(conn, flat_id, user_id, edited_input, edited_result, note="moved kitchen")

    assert version == 2
    flat = storage.get_flat(conn, flat_id, user_id)
    assert len(flat["versions"]) == 2
    assert flat["versions"][1]["version_number"] == 2
    assert flat["versions"][1]["input"] == edited_input
    assert flat["versions"][1]["note"] == "moved kitchen"

    # Original version is still there, unchanged -- editing never overwrites.
    assert flat["versions"][0]["input"] == SAMPLE_INPUT
    assert flat["versions"][0]["result"] == SAMPLE_RESULT


def test_add_version_to_missing_flat_raises_value_error(conn, user_id):
    with pytest.raises(ValueError):
        storage.add_version(conn, 999, user_id, SAMPLE_INPUT, SAMPLE_RESULT)


def test_add_version_to_another_users_flat_raises_value_error(conn, user_id):
    other_user_id = storage.create_user(conn, "bob", "hash456")
    flat_id = storage.create_flat(conn, "My Flat", user_id, SAMPLE_INPUT, SAMPLE_RESULT)
    with pytest.raises(ValueError):
        storage.add_version(conn, flat_id, other_user_id, SAMPLE_INPUT, SAMPLE_RESULT)


def test_get_version_returns_specific_version(conn, user_id):
    flat_id = storage.create_flat(conn, "My Flat", user_id, SAMPLE_INPUT, SAMPLE_RESULT)
    storage.add_version(conn, flat_id, user_id, SAMPLE_INPUT, {"compliance_score": 80})

    v1 = storage.get_version(conn, flat_id, user_id, 1)
    v2 = storage.get_version(conn, flat_id, user_id, 2)
    assert v1["result"] == SAMPLE_RESULT
    assert v2["result"] == {"compliance_score": 80}


def test_get_version_returns_none_for_missing_version(conn, user_id):
    flat_id = storage.create_flat(conn, "My Flat", user_id, SAMPLE_INPUT, SAMPLE_RESULT)
    assert storage.get_version(conn, flat_id, user_id, 5) is None


def test_get_version_returns_none_for_another_users_flat(conn, user_id):
    other_user_id = storage.create_user(conn, "bob", "hash456")
    flat_id = storage.create_flat(conn, "My Flat", user_id, SAMPLE_INPUT, SAMPLE_RESULT)
    assert storage.get_version(conn, flat_id, other_user_id, 1) is None


def test_list_flats_uses_latest_version_for_summary(conn, user_id):
    flat_id = storage.create_flat(conn, "My Flat", user_id, SAMPLE_INPUT, SAMPLE_RESULT)
    storage.add_version(
        conn, flat_id, user_id, SAMPLE_INPUT,
        {"compliance_score": 70, "major_count": 2, "minor_count": 1},
    )

    summaries = storage.list_flats(conn, user_id)
    assert len(summaries) == 1
    s = summaries[0]
    assert s["id"] == flat_id
    assert s["latest_version"] == 2
    assert s["latest_compliance_score"] == 70
    assert s["latest_major_count"] == 2
    assert s["latest_minor_count"] == 1


def test_list_flats_only_returns_the_calling_users_flats(conn, user_id):
    other_user_id = storage.create_user(conn, "bob", "hash456")
    storage.create_flat(conn, "Flat A", user_id, SAMPLE_INPUT, SAMPLE_RESULT)
    storage.create_flat(conn, "Flat B", other_user_id, SAMPLE_INPUT, SAMPLE_RESULT)

    assert [f["label"] for f in storage.list_flats(conn, user_id)] == ["Flat A"]
    assert [f["label"] for f in storage.list_flats(conn, other_user_id)] == ["Flat B"]


def test_delete_flat_removes_flat_and_versions(conn, user_id):
    flat_id = storage.create_flat(conn, "My Flat", user_id, SAMPLE_INPUT, SAMPLE_RESULT)
    storage.add_version(conn, flat_id, user_id, SAMPLE_INPUT, SAMPLE_RESULT)

    assert storage.delete_flat(conn, flat_id, user_id) is True
    assert storage.get_flat(conn, flat_id, user_id) is None
    # Cascade removed the versions row(s) too -- no orphans left in flat_versions.
    orphans = conn.execute(
        "SELECT COUNT(*) AS n FROM flat_versions WHERE flat_id = ?", (flat_id,)
    ).fetchone()["n"]
    assert orphans == 0


def test_delete_flat_returns_false_for_missing_flat(conn, user_id):
    assert storage.delete_flat(conn, 999, user_id) is False


def test_delete_flat_returns_false_for_another_users_flat(conn, user_id):
    other_user_id = storage.create_user(conn, "bob", "hash456")
    flat_id = storage.create_flat(conn, "My Flat", user_id, SAMPLE_INPUT, SAMPLE_RESULT)

    assert storage.delete_flat(conn, flat_id, other_user_id) is False
    assert storage.get_flat(conn, flat_id, user_id) is not None


# ---------------------------------------------------------------------------
# Projects: shared building-level data (submit -> approve/reject -> reuse)
# ---------------------------------------------------------------------------

SAMPLE_BOUNDARY = [[0, 0], [40, 0], [40, 30], [0, 30]]
SAMPLE_BASE_ROOMS = [{"name": "Kitchen", "polygon": [[0, 0], [10, 0], [10, 10], [0, 10]]}]


def test_submit_new_project_proposal_requires_a_name(conn):
    with pytest.raises(ValueError):
        storage.submit_project_proposal(conn, "vikas", proposed_name=None)


def test_submit_proposal_for_missing_project_raises(conn):
    with pytest.raises(ValueError):
        storage.submit_project_proposal(conn, "vikas", project_id=999, proposed_boundary=SAMPLE_BOUNDARY)


def test_submitting_a_proposal_creates_no_project(conn):
    storage.submit_project_proposal(
        conn, "vikas", proposed_name="Skyline Towers",
        proposed_boundary=SAMPLE_BOUNDARY, proposed_facade_bearing_deg=5.0,
    )
    assert storage.list_projects(conn) == []  # nothing is live until approved


def test_approve_new_project_proposal_creates_project_and_version_one(conn):
    proposal_id = storage.submit_project_proposal(
        conn, "vikas", proposed_name="Skyline Towers", proposed_rera_reference="RERA/MH/123",
        proposed_boundary=SAMPLE_BOUNDARY, proposed_facade_bearing_deg=5.0,
        proposed_base_rooms=SAMPLE_BASE_ROOMS, note="from RERA filing",
    )
    result = storage.approve_project_proposal(conn, proposal_id, reviewed_note="looks right")

    assert result["version_number"] == 1
    project = storage.get_project(conn, result["project_id"])
    assert project["name"] == "Skyline Towers"
    assert project["rera_reference"] == "RERA/MH/123"
    assert len(project["versions"]) == 1
    v1 = project["versions"][0]
    assert v1["boundary"] == SAMPLE_BOUNDARY
    assert v1["facade_bearing_deg"] == 5.0
    assert v1["base_rooms"] == SAMPLE_BASE_ROOMS
    assert v1["source_proposal_id"] == proposal_id

    proposal = storage.get_project_proposal(conn, proposal_id)
    assert proposal["status"] == "approved"
    assert proposal["reviewed_note"] == "looks right"
    assert proposal["reviewed_at"] is not None


def test_approve_edit_proposal_adds_a_new_version_not_a_new_project(conn):
    proposal_id = storage.submit_project_proposal(
        conn, "vikas", proposed_name="Skyline Towers", proposed_boundary=SAMPLE_BOUNDARY,
    )
    created = storage.approve_project_proposal(conn, proposal_id)
    project_id = created["project_id"]

    edited_boundary = [[0, 0], [42, 0], [42, 30], [0, 30]]  # corrected width
    edit_proposal_id = storage.submit_project_proposal(
        conn, "resident_alice", project_id=project_id,
        proposed_boundary=edited_boundary, note="corrected east wall measurement",
    )
    result = storage.approve_project_proposal(conn, edit_proposal_id)

    assert result["project_id"] == project_id  # same project, not a new one
    assert result["version_number"] == 2
    project = storage.get_project(conn, project_id)
    assert len(project["versions"]) == 2
    assert project["versions"][1]["boundary"] == edited_boundary
    # Original version is untouched -- editing never overwrites.
    assert project["versions"][0]["boundary"] == SAMPLE_BOUNDARY


def test_reject_proposal_keeps_the_record_but_creates_nothing(conn):
    proposal_id = storage.submit_project_proposal(
        conn, "vikas", proposed_name="Bad Data Towers", proposed_boundary=SAMPLE_BOUNDARY,
    )
    storage.reject_project_proposal(conn, proposal_id, reviewed_note="boundary looks wrong, please retrace")

    assert storage.list_projects(conn) == []
    proposal = storage.get_project_proposal(conn, proposal_id)
    assert proposal["status"] == "rejected"
    assert proposal["reviewed_note"] == "boundary looks wrong, please retrace"


def test_cannot_approve_or_reject_an_already_decided_proposal(conn):
    proposal_id = storage.submit_project_proposal(
        conn, "vikas", proposed_name="Skyline Towers", proposed_boundary=SAMPLE_BOUNDARY,
    )
    storage.approve_project_proposal(conn, proposal_id)

    with pytest.raises(ValueError):
        storage.approve_project_proposal(conn, proposal_id)
    with pytest.raises(ValueError):
        storage.reject_project_proposal(conn, proposal_id)


def test_approve_missing_proposal_raises(conn):
    with pytest.raises(ValueError):
        storage.approve_project_proposal(conn, 999)


def test_reject_missing_proposal_raises(conn):
    with pytest.raises(ValueError):
        storage.reject_project_proposal(conn, 999)


def test_list_project_proposals_filters_by_status(conn):
    p1 = storage.submit_project_proposal(conn, "vikas", proposed_name="A", proposed_boundary=SAMPLE_BOUNDARY)
    p2 = storage.submit_project_proposal(conn, "vikas", proposed_name="B", proposed_boundary=SAMPLE_BOUNDARY)
    storage.approve_project_proposal(conn, p1)

    pending = storage.list_project_proposals(conn, status="pending")
    approved = storage.list_project_proposals(conn, status="approved")
    everything = storage.list_project_proposals(conn)

    assert [p["id"] for p in pending] == [p2]
    assert [p["id"] for p in approved] == [p1]
    assert len(everything) == 2


def test_list_projects_uses_latest_version(conn):
    proposal_id = storage.submit_project_proposal(
        conn, "vikas", proposed_name="Skyline Towers",
        proposed_boundary=SAMPLE_BOUNDARY, proposed_facade_bearing_deg=5.0,
    )
    created = storage.approve_project_proposal(conn, proposal_id)
    edit_id = storage.submit_project_proposal(
        conn, "vikas", project_id=created["project_id"],
        proposed_boundary=SAMPLE_BOUNDARY, proposed_facade_bearing_deg=9.0,
    )
    storage.approve_project_proposal(conn, edit_id)

    summaries = storage.list_projects(conn)
    assert len(summaries) == 1
    assert summaries[0]["latest_version"] == 2
    assert summaries[0]["latest_facade_bearing_deg"] == 9.0


def test_get_project_returns_none_for_missing_id(conn):
    assert storage.get_project(conn, 999) is None


def test_get_project_version_returns_none_for_missing_version(conn):
    proposal_id = storage.submit_project_proposal(
        conn, "vikas", proposed_name="Skyline Towers", proposed_boundary=SAMPLE_BOUNDARY,
    )
    created = storage.approve_project_proposal(conn, proposal_id)
    assert storage.get_project_version(conn, created["project_id"], 5) is None


def test_open_db_is_idempotent_on_existing_file(tmp_path):
    """Reopening the same file (e.g. server restart) must not error or wipe data."""
    db_path = tmp_path / "persist.db"
    c1 = storage.open_db(db_path)
    user_id = storage.create_user(c1, "vikas", "hash123")
    flat_id = storage.create_flat(c1, "My Flat", user_id, SAMPLE_INPUT, SAMPLE_RESULT)
    c1.close()

    c2 = storage.open_db(db_path)
    flat = storage.get_flat(c2, flat_id, user_id)
    assert flat is not None
    assert flat["label"] == "My Flat"
    c2.close()


def test_open_db_rejects_pre_auth_legacy_schema(tmp_path):
    """A SQLite file from before real accounts existed (flats.owner as a
    free-text label, no users/sessions tables) must fail loudly, not
    silently limp along with half the new schema missing."""
    import sqlite3

    db_path = tmp_path / "legacy.db"
    legacy_conn = sqlite3.connect(db_path)
    legacy_conn.executescript(
        """
        CREATE TABLE flats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT NOT NULL,
            owner TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    legacy_conn.commit()
    legacy_conn.close()

    with pytest.raises(RuntimeError, match="pre-auth schema"):
        storage.open_db(db_path)
