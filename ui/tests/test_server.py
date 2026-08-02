"""Integration tests for auth (/auth/*) and the /flats persistence
endpoints in server.py.

Each test gets a fresh temp SQLite file (server.DB_PATH is monkeypatched
before the client is built) so tests never share state or touch the real
ui/vastu_ui.db. FastAPI's TestClient keeps a cookie jar per instance, so
logging in once on a client is enough for subsequent requests on that same
client to carry the session cookie automatically.
"""

import pytest
from fastapi.testclient import TestClient

import server


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DB_PATH", str(tmp_path / "test.db"))
    # TestClient talks to the app over plain http (base_url "http://testserver"),
    # so a cookie marked Secure would never be stored/replayed by the client's
    # cookie jar -- disable that flag for tests the same way a real local-dev
    # run would via VASTU_UI_INSECURE_COOKIES=1.
    monkeypatch.setattr(server, "COOKIE_SECURE", False)
    return TestClient(server.app)


@pytest.fixture
def auth_client(client):
    """A client already registered + logged in as a fresh user."""
    resp = client.post("/auth/register", json={"username": "vikas", "password": "correct-horse-battery"})
    assert resp.status_code == 200
    return client


COMPLIANT_LAYOUT = {
    "label": "Unit 12",
    "plot": {"shape": "rectangle", "brahmasthan_obstructed": False},
    "rooms": [{"name": "Kitchen", "zone": "SE"}],
}


# ---------------------------------------------------------------------------
# Auth: register / login / logout / me
# ---------------------------------------------------------------------------

def test_register_creates_user_and_logs_in(client):
    resp = client.post("/auth/register", json={"username": "vikas", "password": "correct-horse-battery"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "vikas"
    assert "vastu_session" in resp.cookies

    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "vikas"


def test_register_rejects_short_password(client):
    resp = client.post("/auth/register", json={"username": "vikas", "password": "short"})
    assert resp.status_code == 400


def test_register_rejects_invalid_username(client):
    resp = client.post("/auth/register", json={"username": "a", "password": "correct-horse-battery"})
    assert resp.status_code == 400


def test_register_rejects_duplicate_username(client):
    client.post("/auth/register", json={"username": "vikas", "password": "correct-horse-battery"})
    resp = client.post("/auth/register", json={"username": "vikas", "password": "another-password"})
    assert resp.status_code == 409


def test_login_with_correct_credentials_succeeds(client):
    client.post("/auth/register", json={"username": "vikas", "password": "correct-horse-battery"})
    client.post("/auth/logout")

    resp = client.post("/auth/login", json={"username": "vikas", "password": "correct-horse-battery"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "vikas"


def test_login_with_wrong_password_fails(client):
    client.post("/auth/register", json={"username": "vikas", "password": "correct-horse-battery"})
    resp = client.post("/auth/login", json={"username": "vikas", "password": "wrong-password"})
    assert resp.status_code == 401


def test_login_with_unknown_username_fails(client):
    resp = client.post("/auth/login", json={"username": "nobody", "password": "whatever123"})
    assert resp.status_code == 401


def test_me_requires_login(client):
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_logout_invalidates_session(auth_client):
    assert auth_client.get("/auth/me").status_code == 200
    auth_client.post("/auth/logout")
    assert auth_client.get("/auth/me").status_code == 401


# ---------------------------------------------------------------------------
# /flats* endpoints require login
# ---------------------------------------------------------------------------

def test_flats_endpoints_require_login(client):
    assert client.get("/flats").status_code == 401
    assert client.post("/flats", json=COMPLIANT_LAYOUT).status_code == 401
    assert client.get("/flats/1").status_code == 401
    assert client.post("/flats/1/versions", json=COMPLIANT_LAYOUT).status_code == 401
    assert client.get("/flats/1/versions/1").status_code == 401
    assert client.delete("/flats/1").status_code == 401


def test_create_flat_persists_and_returns_audit_result(auth_client):
    resp = auth_client.post("/flats", json=COMPLIANT_LAYOUT)
    assert resp.status_code == 200
    body = resp.json()
    assert body["flat_id"] is not None
    assert body["version"] == 1
    assert body["result"]["compliance_score"] == 100
    assert body["result"]["major_count"] == 0


def test_create_flat_requires_label(auth_client):
    bad = {"plot": {}, "rooms": []}
    resp = auth_client.post("/flats", json=bad)
    assert resp.status_code == 400


def test_get_flat_returns_saved_flat_with_versions(auth_client):
    created = auth_client.post("/flats", json=COMPLIANT_LAYOUT).json()
    flat_id = created["flat_id"]

    resp = auth_client.get(f"/flats/{flat_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["label"] == "Unit 12"
    assert len(body["versions"]) == 1


def test_get_flat_404_for_missing_id(auth_client):
    resp = auth_client.get("/flats/999")
    assert resp.status_code == 404


def test_flats_are_scoped_to_the_owning_user(client):
    client.post("/auth/register", json={"username": "alice", "password": "correct-horse-battery"})
    created = client.post("/flats", json=COMPLIANT_LAYOUT).json()
    flat_id = created["flat_id"]
    client.post("/auth/logout")

    client.post("/auth/register", json={"username": "bob", "password": "another-horse-battery"})
    # bob can't see or touch alice's flat -- same 404 as a nonexistent id.
    assert client.get(f"/flats/{flat_id}").status_code == 404
    assert client.get("/flats").json() == []
    assert client.delete(f"/flats/{flat_id}").status_code == 404


def test_add_version_creates_second_version_and_reaudits(auth_client):
    created = auth_client.post("/flats", json=COMPLIANT_LAYOUT).json()
    flat_id = created["flat_id"]

    edited = {
        "plot": {"shape": "rectangle", "brahmasthan_obstructed": False},
        "rooms": [{"name": "Kitchen", "zone": "NE"}],  # forbidden, major
        "note": "moved kitchen to NE by mistake",
    }
    resp = auth_client.post(f"/flats/{flat_id}/versions", json=edited)
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == 2
    assert body["result"]["major_count"] == 1

    # Original version 1 is untouched -- history is preserved for comparison.
    v1 = auth_client.get(f"/flats/{flat_id}/versions/1").json()
    assert v1["result"]["major_count"] == 0
    v2 = auth_client.get(f"/flats/{flat_id}/versions/2").json()
    assert v2["result"]["major_count"] == 1
    assert v2["note"] == "moved kitchen to NE by mistake"


def test_add_version_404_for_missing_flat(auth_client):
    resp = auth_client.post("/flats/999/versions", json=COMPLIANT_LAYOUT)
    assert resp.status_code == 404


def test_get_version_404_for_missing_version(auth_client):
    created = auth_client.post("/flats", json=COMPLIANT_LAYOUT).json()
    flat_id = created["flat_id"]
    resp = auth_client.get(f"/flats/{flat_id}/versions/99")
    assert resp.status_code == 404


def test_list_flats_reflects_latest_version_score(auth_client):
    created = auth_client.post("/flats", json=COMPLIANT_LAYOUT).json()
    flat_id = created["flat_id"]
    auth_client.post(f"/flats/{flat_id}/versions", json={
        "plot": {"shape": "rectangle"},
        "rooms": [{"name": "Kitchen", "zone": "NE"}],
    })

    resp = auth_client.get("/flats")
    assert resp.status_code == 200
    flats = resp.json()
    assert len(flats) == 1
    assert flats[0]["latest_version"] == 2
    assert flats[0]["latest_major_count"] == 1


def test_delete_flat_removes_it(auth_client):
    created = auth_client.post("/flats", json=COMPLIANT_LAYOUT).json()
    flat_id = created["flat_id"]

    resp = auth_client.delete(f"/flats/{flat_id}")
    assert resp.status_code == 200
    assert auth_client.get(f"/flats/{flat_id}").status_code == 404


def test_delete_flat_404_for_missing_flat(auth_client):
    resp = auth_client.delete("/flats/999")
    assert resp.status_code == 404


def test_stateless_audit_endpoint_works_without_login_and_saves_nothing(client):
    resp = client.post("/audit", json={"plot": {}, "rooms": []})
    assert resp.status_code == 200
    assert resp.json()["compliance_score"] == 100


def test_schema_info_endpoint_works_without_login(client):
    resp = client.get("/schema-info")
    assert resp.status_code == 200
    assert "room_types" in resp.json()


# ---------------------------------------------------------------------------
# Placement suggestions (suggestions.py wiring)
# ---------------------------------------------------------------------------

LAYOUT_WITH_POLYGON = {
    "label": "Unit 12",
    "plot": {"shape": "rectangle"},
    "rooms": [{
        "name": "MasterBedroom",
        "zone": "SW",
        "polygon": [[0, 0], [12, 0], [12, 14], [0, 14]],
    }],
    "facade_bearing_deg": 0.0,
}


def test_audit_endpoint_includes_suggestion_for_room_with_polygon(client):
    resp = client.post("/audit", json=LAYOUT_WITH_POLYGON)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["suggestions"]) == 1
    assert body["suggestions"][0]["room"] == "MasterBedroom"
    assert body["suggestions"][0]["placements"][0]["object"] == "bed"


def test_audit_endpoint_has_empty_suggestions_when_no_polygons(client):
    resp = client.post("/audit", json={"plot": {}, "rooms": [{"name": "Kitchen", "zone": "SE"}]})
    assert resp.status_code == 200
    assert resp.json()["suggestions"] == []


def test_create_flat_saves_and_returns_suggestions(auth_client):
    resp = auth_client.post("/flats", json=LAYOUT_WITH_POLYGON)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["result"]["suggestions"]) == 1
    assert body["input"]["facade_bearing_deg"] == 0.0


def test_saved_flat_round_trips_facade_bearing_and_polygon(auth_client):
    created = auth_client.post("/flats", json=LAYOUT_WITH_POLYGON).json()
    flat_id = created["flat_id"]

    flat = auth_client.get(f"/flats/{flat_id}").json()
    saved_input = flat["versions"][0]["input"]
    assert saved_input["facade_bearing_deg"] == 0.0
    assert saved_input["rooms"][0]["polygon"] == [[0, 0], [12, 0], [12, 14], [0, 14]]


def test_suggestion_error_for_room_too_small_is_not_a_500(client):
    layout = {
        "plot": {},
        "rooms": [{"name": "MasterBedroom", "zone": "SW", "polygon": [[0, 0], [2, 0], [2, 2], [0, 2]]}],
    }
    resp = client.post("/audit", json=layout)
    assert resp.status_code == 200
    assert resp.json()["suggestions"][0]["error_type"] == "solver_error"


@pytest.mark.parametrize(
    "bad_polygon",
    [
        "not a polygon",
        123,
        [[0, 0], [1, 1]],  # only 2 vertices
        [[0, 0], [1, 0], ["x", "y"]],  # non-numeric coordinates
    ],
)
def test_malformed_polygon_over_http_is_not_a_500(client, bad_polygon):
    """The blocking fix this covers: a malformed polygon arriving straight
    off the wire (not just clean Python-side fixtures) must never 500 the
    whole /audit response -- it must come back as a structured per-room
    suggestion_error, same status code as a clean request."""
    layout = {
        "plot": {},
        "rooms": [{"name": "MasterBedroom", "zone": "SW", "polygon": bad_polygon}],
    }
    resp = client.post("/audit", json=layout)
    assert resp.status_code == 200
    body = resp.json()
    assert body["suggestions"][0]["error_type"] == "invalid_geometry"
    # The rest of the zone/adjacency audit still ran normally -- one bad
    # polygon doesn't take the whole response down.
    assert "compliance_score" in body


def test_malformed_polygon_in_one_room_does_not_break_other_rooms_over_http(client):
    layout = {
        "plot": {},
        "rooms": [
            {"name": "MasterBedroom", "zone": "SW", "polygon": "garbage"},
            {"name": "Kitchen", "zone": "SE", "polygon": [[0, 0], [10, 0], [10, 8], [0, 8]]},
        ],
    }
    resp = client.post("/audit", json=layout)
    assert resp.status_code == 200
    suggestions_by_room = {s["room"]: s for s in resp.json()["suggestions"]}
    assert suggestions_by_room["MasterBedroom"]["error_type"] == "invalid_geometry"
    assert "placements" in suggestions_by_room["Kitchen"]


def test_furniture_dimensions_override_is_honored(client):
    layout = {
        "plot": {},
        "rooms": [{"name": "MasterBedroom", "zone": "SW", "polygon": [[0, 0], [4, 0], [4, 5], [0, 5]]}],
        "furniture_dimensions": {"MasterBedroom": [3.0, 4.0]},
    }
    resp = client.post("/audit", json=layout)
    assert resp.status_code == 200
    assert "placements" in resp.json()["suggestions"][0]


# ---------------------------------------------------------------------------
# Projects: shared building-level data + the admin gate
# ---------------------------------------------------------------------------

SAMPLE_BOUNDARY = [[0, 0], [40, 0], [40, 30], [0, 30]]


@pytest.fixture
def admin_client(client, monkeypatch):
    """Same client, with VASTU_ADMIN_TOKEN configured -- individual tests
    still choose whether to send the matching header."""
    monkeypatch.setenv("VASTU_ADMIN_TOKEN", "s3cret")
    return client


def test_submit_proposal_requires_submitted_by(client):
    resp = client.post("/projects/proposals", json={"proposed_name": "Skyline Towers"})
    assert resp.status_code == 400


def test_submit_new_project_proposal_needs_no_admin_token(client):
    resp = client.post("/projects/proposals", json={
        "submitted_by": "vikas", "proposed_name": "Skyline Towers",
        "proposed_boundary": SAMPLE_BOUNDARY, "proposed_facade_bearing_deg": 5.0,
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"


def test_submitted_proposal_visible_by_id_without_admin_token(client):
    proposal_id = client.post("/projects/proposals", json={
        "submitted_by": "vikas", "proposed_name": "Skyline Towers", "proposed_boundary": SAMPLE_BOUNDARY,
    }).json()["proposal_id"]

    resp = client.get(f"/projects/proposals/{proposal_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"


def test_admin_endpoints_fail_closed_when_token_unconfigured(client, monkeypatch):
    monkeypatch.delenv("VASTU_ADMIN_TOKEN", raising=False)
    resp = client.get("/projects/proposals")
    assert resp.status_code == 503


def test_admin_endpoints_reject_wrong_token(admin_client):
    resp = admin_client.get("/projects/proposals", headers={"X-Admin-Token": "wrong"})
    assert resp.status_code == 403


def test_admin_endpoints_reject_missing_token(admin_client):
    resp = admin_client.get("/projects/proposals")
    assert resp.status_code == 403


def test_approving_new_project_proposal_requires_admin_token(client):
    proposal_id = client.post("/projects/proposals", json={
        "submitted_by": "vikas", "proposed_name": "Skyline Towers", "proposed_boundary": SAMPLE_BOUNDARY,
    }).json()["proposal_id"]

    resp = client.post(f"/projects/proposals/{proposal_id}/approve", json={})
    assert resp.status_code == 503  # no admin token configured at all in this test


def test_full_project_lifecycle_submit_approve_list_and_reuse(admin_client):
    submit = admin_client.post("/projects/proposals", json={
        "submitted_by": "vikas", "proposed_name": "Skyline Towers",
        "proposed_rera_reference": "RERA/MH/123",
        "proposed_boundary": SAMPLE_BOUNDARY, "proposed_facade_bearing_deg": 5.0,
        "proposed_base_rooms": [{"name": "Kitchen", "polygon": [[0, 0], [8, 0], [8, 8], [0, 8]]}],
        "note": "from the RERA-published layout",
    })
    proposal_id = submit.json()["proposal_id"]

    # Not live yet -- nothing in the public project list.
    assert admin_client.get("/projects").json() == []

    approve = admin_client.post(
        f"/projects/proposals/{proposal_id}/approve",
        json={"reviewed_note": "matches the filing"},
        headers={"X-Admin-Token": "s3cret"},
    )
    assert approve.status_code == 200
    project_id = approve.json()["project_id"]
    assert approve.json()["version_number"] == 1

    # Now it's live and publicly browsable/reusable, no token required to read.
    projects = admin_client.get("/projects").json()
    assert len(projects) == 1
    assert projects[0]["id"] == project_id
    assert projects[0]["name"] == "Skyline Towers"

    project = admin_client.get(f"/projects/{project_id}").json()
    assert project["versions"][0]["boundary"] == SAMPLE_BOUNDARY
    assert project["versions"][0]["source_proposal_id"] == proposal_id


def test_edit_proposal_approval_adds_version_not_new_project(admin_client):
    p1 = admin_client.post("/projects/proposals", json={
        "submitted_by": "vikas", "proposed_name": "Skyline Towers", "proposed_boundary": SAMPLE_BOUNDARY,
    }).json()["proposal_id"]
    project_id = admin_client.post(
        f"/projects/proposals/{p1}/approve", json={}, headers={"X-Admin-Token": "s3cret"}
    ).json()["project_id"]

    corrected_boundary = [[0, 0], [42, 0], [42, 30], [0, 30]]
    p2 = admin_client.post("/projects/proposals", json={
        "submitted_by": "resident_alice", "project_id": project_id,
        "proposed_boundary": corrected_boundary, "note": "measured east wall myself, it's 2ft wider",
    }).json()["proposal_id"]
    result = admin_client.post(
        f"/projects/proposals/{p2}/approve", json={}, headers={"X-Admin-Token": "s3cret"}
    ).json()
    assert result["project_id"] == project_id
    assert result["version_number"] == 2

    projects = admin_client.get("/projects").json()
    assert len(projects) == 1  # still one project, now on version 2


def test_reject_proposal_with_admin_token(admin_client):
    proposal_id = admin_client.post("/projects/proposals", json={
        "submitted_by": "vikas", "proposed_name": "Bad Data Towers", "proposed_boundary": SAMPLE_BOUNDARY,
    }).json()["proposal_id"]

    resp = admin_client.post(
        f"/projects/proposals/{proposal_id}/reject",
        json={"reviewed_note": "boundary doesn't match the filing, please retrace"},
        headers={"X-Admin-Token": "s3cret"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"
    assert admin_client.get("/projects").json() == []

    proposal = admin_client.get(f"/projects/proposals/{proposal_id}").json()
    assert proposal["status"] == "rejected"
    assert "retrace" in proposal["reviewed_note"]


def test_get_project_404_for_missing_id(client):
    resp = client.get("/projects/999")
    assert resp.status_code == 404


def test_get_project_version_404_for_missing_version(admin_client):
    proposal_id = admin_client.post("/projects/proposals", json={
        "submitted_by": "vikas", "proposed_name": "Skyline Towers", "proposed_boundary": SAMPLE_BOUNDARY,
    }).json()["proposal_id"]
    project_id = admin_client.post(
        f"/projects/proposals/{proposal_id}/approve", json={}, headers={"X-Admin-Token": "s3cret"}
    ).json()["project_id"]

    resp = admin_client.get(f"/projects/{project_id}/versions/99")
    assert resp.status_code == 404
