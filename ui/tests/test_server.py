"""Integration tests for the /flats persistence endpoints in server.py.

Each test gets a fresh temp SQLite file (server.DB_PATH is monkeypatched
before the client is built) so tests never share state or touch the real
ui/vastu_ui.db.
"""

import pytest
from fastapi.testclient import TestClient

import server


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DB_PATH", str(tmp_path / "test.db"))
    return TestClient(server.app)


COMPLIANT_LAYOUT = {
    "label": "Unit 12",
    "owner": "vikas",
    "plot": {"shape": "rectangle", "brahmasthan_obstructed": False},
    "rooms": [{"name": "Kitchen", "zone": "SE"}],
}


def test_create_flat_persists_and_returns_audit_result(client):
    resp = client.post("/flats", json=COMPLIANT_LAYOUT)
    assert resp.status_code == 200
    body = resp.json()
    assert body["flat_id"] is not None
    assert body["version"] == 1
    assert body["result"]["compliance_score"] == 100
    assert body["result"]["major_count"] == 0


def test_create_flat_requires_label_and_owner(client):
    bad = {"plot": {}, "rooms": []}
    resp = client.post("/flats", json=bad)
    assert resp.status_code == 400


def test_get_flat_returns_saved_flat_with_versions(client):
    created = client.post("/flats", json=COMPLIANT_LAYOUT).json()
    flat_id = created["flat_id"]

    resp = client.get(f"/flats/{flat_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["label"] == "Unit 12"
    assert body["owner"] == "vikas"
    assert len(body["versions"]) == 1


def test_get_flat_404_for_missing_id(client):
    resp = client.get("/flats/999")
    assert resp.status_code == 404


def test_add_version_creates_second_version_and_reaudits(client):
    created = client.post("/flats", json=COMPLIANT_LAYOUT).json()
    flat_id = created["flat_id"]

    edited = {
        "plot": {"shape": "rectangle", "brahmasthan_obstructed": False},
        "rooms": [{"name": "Kitchen", "zone": "NE"}],  # forbidden, major
        "note": "moved kitchen to NE by mistake",
    }
    resp = client.post(f"/flats/{flat_id}/versions", json=edited)
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == 2
    assert body["result"]["major_count"] == 1

    # Original version 1 is untouched -- history is preserved for comparison.
    v1 = client.get(f"/flats/{flat_id}/versions/1").json()
    assert v1["result"]["major_count"] == 0
    v2 = client.get(f"/flats/{flat_id}/versions/2").json()
    assert v2["result"]["major_count"] == 1
    assert v2["note"] == "moved kitchen to NE by mistake"


def test_add_version_404_for_missing_flat(client):
    resp = client.post("/flats/999/versions", json=COMPLIANT_LAYOUT)
    assert resp.status_code == 404


def test_get_version_404_for_missing_version(client):
    created = client.post("/flats", json=COMPLIANT_LAYOUT).json()
    flat_id = created["flat_id"]
    resp = client.get(f"/flats/{flat_id}/versions/99")
    assert resp.status_code == 404


def test_list_flats_reflects_latest_version_score(client):
    created = client.post("/flats", json=COMPLIANT_LAYOUT).json()
    flat_id = created["flat_id"]
    client.post(f"/flats/{flat_id}/versions", json={
        "plot": {"shape": "rectangle"},
        "rooms": [{"name": "Kitchen", "zone": "NE"}],
    })

    resp = client.get("/flats")
    assert resp.status_code == 200
    flats = resp.json()
    assert len(flats) == 1
    assert flats[0]["latest_version"] == 2
    assert flats[0]["latest_major_count"] == 1


def test_delete_flat_removes_it(client):
    created = client.post("/flats", json=COMPLIANT_LAYOUT).json()
    flat_id = created["flat_id"]

    resp = client.delete(f"/flats/{flat_id}")
    assert resp.status_code == 200
    assert client.get(f"/flats/{flat_id}").status_code == 404


def test_delete_flat_404_for_missing_flat(client):
    resp = client.delete("/flats/999")
    assert resp.status_code == 404


def test_stateless_audit_endpoint_still_works_and_saves_nothing(client):
    resp = client.post("/audit", json={"plot": {}, "rooms": []})
    assert resp.status_code == 200
    assert resp.json()["compliance_score"] == 100
    assert client.get("/flats").json() == []


def test_schema_info_endpoint_unaffected_by_persistence_changes(client):
    resp = client.get("/schema-info")
    assert resp.status_code == 200
    assert "room_types" in resp.json()
