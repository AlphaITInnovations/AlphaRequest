"""Ebene-1: Ticket-Runtime-API (create/patch/advance/reject) mit In-Memory-Store.

Kein echtes MariaDB: der DB-Layer wird durch einen In-Memory-Fake ersetzt, die
Auth-Dependency überschrieben. Getestet wird die Endpunkt-Logik: Zwei-Pass-
Validierung, Pinning der Definition, Phasen-Fortschritt, Terminal-Sperre.
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.dependencies import get_current_user
from backend.main import _install_error_handlers
from backend.api.v1 import process_tickets as pt


DEFN = {
    "schemaVersion": 1, "key": "demo", "name": "Demo-Prozess",
    "fields": [
        {"key": "base.name", "widget": "text"},
        {"key": "base.age", "widget": "number"},
    ],
    "phases": [
        {"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
         "fields": [{"ref": "base.name", "required": True}]},
        {"key": "review", "kind": "review",
         "responsibility": {"kind": "departments", "rule": [{"group": "g_it"}]},
         "fields": [{"ref": "base.name", "mode": "readonly"}]},
    ],
}


class FakeStore:
    def __init__(self):
        self.rows: dict[int, dict] = {}
        self.seq = 0

    def create(self, **kw):
        self.seq += 1
        row = {"id": self.seq, "next_timer_due_at": None, "created_at": "t", "updated_at": "t", **kw}
        row["values"] = json.loads(kw["values_json"])
        row["runtime"] = json.loads(kw["runtime_json"])
        self.rows[self.seq] = row
        return dict(row)

    def get(self, tid):
        r = self.rows.get(tid)
        return dict(r) if r else None

    def update_values(self, tid, values_json, title=None):
        r = self.rows[tid]
        r["values_json"] = values_json
        r["values"] = json.loads(values_json)
        if title is not None:
            r["title"] = title
        return dict(r)

    def update_runtime(self, tid, *, runtime_json, status, next_timer_due_at=None):
        r = self.rows[tid]
        r["runtime_json"] = runtime_json
        r["runtime"] = json.loads(runtime_json)
        r["status"] = status
        r["next_timer_due_at"] = next_timer_due_at
        return dict(r)

    def list_tickets(self, **kw):
        rows = [dict(r) for r in self.rows.values()]
        return rows, len(rows)


class FakeDefs:
    def get_published(self, key):
        return {"version": 1, "definition": DEFN} if key == "demo" else None

    def get_definition(self, key, ver):
        return {"version": ver, "definition": DEFN} if key == "demo" else None


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(pt, "store", FakeStore())
    monkeypatch.setattr(pt, "defstore", FakeDefs())
    app = FastAPI()
    _install_error_handlers(app)
    app.include_router(pt.router)
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "u1", "displayName": "Admin", "permissions": ["admin"]}
    return TestClient(app)


def test_create_rejects_bad_value(client):
    r = client.post("/process-tickets", json={"processKey": "demo", "values": {"base.age": "NaN"}})
    assert r.status_code == 422
    body = r.json()
    assert body["error"]["code"] == "VALIDATION_FAILED"
    assert any(f["path"] == "base.age" for f in body["error"]["fields"])


def test_create_rejects_unknown_process(client):
    r = client.post("/process-tickets", json={"processKey": "ghost"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "PROCESS_NOT_FOUND"


def test_create_ok(client):
    r = client.post("/process-tickets", json={"processKey": "demo", "values": {"base.name": "Max"}})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["status"] == "in_progress"
    assert d["current_phase"] == "start"
    assert d["process_version"] == 1
    assert d["values"] == {"base.name": "Max"}


def test_patch_merges_values(client):
    tid = client.post("/process-tickets", json={"processKey": "demo", "values": {"base.name": "Max"}}).json()["data"]["id"]
    r = client.patch(f"/process-tickets/{tid}", json={"values": {"base.age": 30}})
    assert r.status_code == 200
    assert r.json()["data"]["values"] == {"base.name": "Max", "base.age": 30}


def test_advance_blocked_when_required_missing(client):
    tid = client.post("/process-tickets", json={"processKey": "demo"}).json()["data"]["id"]
    r = client.post(f"/process-tickets/{tid}:advance")
    assert r.status_code == 422
    assert any(f["path"] == "base.name" and f["code"] == "REQUIRED"
               for f in r.json()["error"]["fields"])


def test_full_lifecycle_advance_and_archive(client):
    tid = client.post("/process-tickets", json={"processKey": "demo", "values": {"base.name": "Max"}}).json()["data"]["id"]
    r1 = client.post(f"/process-tickets/{tid}:advance")
    assert r1.status_code == 200
    d1 = r1.json()["data"]
    assert d1["current_phase"] == "review" and d1["status"] == "in_request"
    # Zuständigkeit der review-Phase = Abteilung g_it
    assert d1["responsibility"]["kind"] == "departments"
    assert d1["responsibility"]["departments"][0]["group"] == "g_it"
    r2 = client.post(f"/process-tickets/{tid}:advance")
    assert r2.status_code == 200
    assert r2.json()["data"]["status"] == "archived"
    # danach ist das Ticket terminal → weitere Aktion 409
    r3 = client.post(f"/process-tickets/{tid}:advance")
    assert r3.status_code == 409


def test_reject_then_locked(client):
    tid = client.post("/process-tickets", json={"processKey": "demo", "values": {"base.name": "Max"}}).json()["data"]["id"]
    assert client.post(f"/process-tickets/{tid}:reject").json()["data"]["status"] == "rejected"
    assert client.patch(f"/process-tickets/{tid}", json={"values": {"base.age": 1}}).status_code == 409


def test_list_returns_meta(client):
    client.post("/process-tickets", json={"processKey": "demo", "values": {"base.name": "A"}})
    client.post("/process-tickets", json={"processKey": "demo", "values": {"base.name": "B"}})
    r = client.get("/process-tickets")
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["total"] == 2 and len(body["data"]) == 2
