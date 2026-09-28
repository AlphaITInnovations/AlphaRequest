"""CSV-Export/-Import des globalen Archivs (Admin-Werkzeuge).

Export = der ganze gefilterte Satz inkl. Rohwerten (values/runtime) → nur Admin.
Import = additiver Restore: Original-Nummern behalten, vorhandene ÜBERSPRINGEN,
kaputte/unbekannte Zeilen als „fehlerhaft" melden statt anzulegen; commit=false ist
eine Vorschau (schreibt nichts). Der Store wird durch eine Attrappe ersetzt (keine
DB); geprüft wird die Endpunkt-Logik, nicht die SQL-Filterung."""
import csv
import io
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.dependencies import get_current_user
from backend.main import _install_error_handlers
from backend.api.v1 import process_tickets as pt
from backend.services import process_access as acc

ADMIN = {"id": "u_admin", "displayName": "Admin", "permissions": ["admin"]}
HEADER = pt._ARCHIVE_CSV_HEADER


def _full_row(tid, owner="Anna", status="archived"):
    """Vollzeile wie store.export_global_archive sie liefert (inkl. values/runtime)."""
    return {"id": tid, "process_key": "demo", "process_version": 1, "title": f"Titel {tid}",
            "status": status, "priority": "normal", "owner_id": f"u{tid}", "owner_name": owner,
            "created_at": "2026-01-01T09:00:00", "updated_at": "2026-02-01T09:00:00",
            "values": {"name": f"Öäü {tid}"},
            "runtime": {"phases": [{"key": "start"}, {"key": "ende"}], "current_index": 1}}


class _Store:
    def __init__(self, rows=None, existing=None):
        self.rows = rows or []
        self.existing = set(existing or [])
        self.export_calls: list = []
        self.created: list = []

    def export_global_archive(self, **kw):
        self.export_calls.append(kw)
        return [dict(r) for r in self.rows]

    def get(self, tid):
        return {"id": tid} if tid in self.existing else None

    def create_with_id(self, **kw):
        self.created.append(kw)
        self.existing.add(kw["id"])
        return {"id": kw["id"]}


def _client(monkeypatch, *, rows=None, existing=None, is_admin=True,
            known=(("demo", 1),)):
    store = _Store(rows=rows, existing=existing)
    monkeypatch.setattr(pt, "store", store)
    monkeypatch.setattr(acc, "is_admin", lambda u: is_admin)
    monkeypatch.setattr(pt, "record_audit", lambda **kw: None)
    monkeypatch.setattr(pt.defstore, "get_definition",
                        lambda pk, ver: object() if (pk, ver) in known else None)
    app = FastAPI()
    _install_error_handlers(app)
    app.include_router(pt.router)
    app.dependency_overrides[get_current_user] = lambda: ADMIN
    return TestClient(app), store


def _csv(rows):
    """Baut eine ;-CSV mit dem Standard-Kopf; jede row ist ein Dict je Spalte."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(HEADER)
    for r in rows:
        w.writerow([r.get(h, "") for h in HEADER])
    return buf.getvalue()


def _row_dict(tid, pk="demo", ver=1, values=None, runtime=None, **over):
    d = {"id": tid, "process_key": pk, "process_version": ver, "title": f"T{tid}",
         "status": "archived", "priority": "normal", "owner_id": f"u{tid}",
         "owner_name": "Anna", "current_phase": "start",
         "created_at": "2026-01-01T09:00:00", "updated_at": "2026-02-01T09:00:00",
         "values_json": json.dumps(values if values is not None else {"a": "b"}),
         "runtime_json": json.dumps(runtime if runtime is not None else {"phases": []})}
    d.update(over)
    return d


# ── Export ────────────────────────────────────────────────────────────────────

def test_export_requires_admin(monkeypatch):
    c, _ = _client(monkeypatch, is_admin=False)
    assert c.get("/process-tickets/archive.csv").status_code == 403


def test_export_emits_bom_header_and_full_data(monkeypatch):
    c, store = _client(monkeypatch, rows=[_full_row(1), _full_row(2)])
    r = c.get("/process-tickets/archive.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    text = r.content.decode("utf-8")
    assert text.startswith("﻿")                       # BOM für Excel
    body = text.lstrip("﻿")
    reader = list(csv.DictReader(io.StringIO(body), delimiter=";"))
    assert [row["id"] for row in reader] == ["1", "2"]
    # Volldaten müssen mitkommen (sonst kein Restore) …
    assert json.loads(reader[0]["values_json"]) == {"name": "Öäü 1"}
    # … und der aktuelle Phasen-Schlüssel aus der Runtime (current_index=1 → "ende").
    assert reader[0]["current_phase"] == "ende"


def test_export_passes_filters_through(monkeypatch):
    c, store = _client(monkeypatch, rows=[])
    c.get("/process-tickets/archive.csv?created_by=anna&status=archived,rejected"
          "&date_field=created&date_from=2026-01-01&date_to=2026-03-01&sort=created_asc&q=x")
    kw = store.export_calls[-1]
    assert kw["created_by"] == "anna" and kw["q"] == "x"
    assert kw["status"] == ["archived", "rejected"]
    assert kw["date_field"] == "created" and kw["sort"] == "created_asc"


# ── Import ──────────────────────────────────────────────────────────────────

def test_import_requires_admin(monkeypatch):
    c, _ = _client(monkeypatch, is_admin=False)
    r = c.post("/process-tickets/archive:import-csv", json={"csv": _csv([]), "commit": True})
    assert r.status_code == 403


def test_import_dry_run_writes_nothing(monkeypatch):
    c, store = _client(monkeypatch, rows=[])
    csv_text = _csv([_row_dict(1), _row_dict(2)])
    r = c.post("/process-tickets/archive:import-csv", json={"csv": csv_text, "commit": False})
    d = r.json()["data"]
    assert d["committed"] is False
    assert d["counts"] == {"created": 2, "skipped": 0, "failed": 0}
    assert store.created == []                              # Vorschau schreibt nicht


def test_import_skips_existing_numbers(monkeypatch):
    c, store = _client(monkeypatch, existing={2})
    csv_text = _csv([_row_dict(1), _row_dict(2), _row_dict(3)])
    r = c.post("/process-tickets/archive:import-csv", json={"csv": csv_text, "commit": True})
    d = r.json()["data"]
    assert d["counts"] == {"created": 2, "skipped": 1, "failed": 0}
    assert [c["id"] for c in store.created] == [1, 3]       # #2 übersprungen, nie überschrieben
    assert d["skipped"][0]["id"] == 2


def test_import_dedups_duplicate_ids_within_file(monkeypatch):
    # Zwei Zeilen mit derselben (noch nicht vorhandenen) Nummer: die zweite wird
    # übersprungen – und zwar identisch in Vorschau UND Commit (Gleichlauf).
    for commit in (False, True):
        c, store = _client(monkeypatch)
        csv_text = _csv([_row_dict(50), _row_dict(50), _row_dict(51)])
        r = c.post("/process-tickets/archive:import-csv", json={"csv": csv_text, "commit": commit})
        d = r.json()["data"]
        assert d["counts"] == {"created": 2, "skipped": 1, "failed": 0}, f"commit={commit}"
        assert d["skipped"][0]["id"] == 50
        if commit:
            assert [x["id"] for x in store.created] == [50, 51]   # #50 nur EINMAL angelegt


def test_import_flags_bad_rows(monkeypatch):
    c, store = _client(monkeypatch)
    rows = [
        _row_dict("abc"),                                  # ungültige Nummer
        _row_dict(5, ver="x"),                             # ungültige Version
        _row_dict(6, pk="unbekannt"),                      # Definition fehlt
        _row_dict(7, values_json="{kaputt"),               # kaputtes JSON
        _row_dict(8, values_json="[]"),                    # JSON, aber kein Objekt
        _row_dict(9),                                      # ok
    ]
    r = c.post("/process-tickets/archive:import-csv", json={"csv": _csv(rows), "commit": True})
    d = r.json()["data"]
    assert d["counts"] == {"created": 1, "skipped": 0, "failed": 5}
    assert [c["id"] for c in store.created] == [9]
    # Fehlerhafte tragen ihre Quell-Zeile (Kopf = Zeile 1; ok-Zeile #9 = Zeile 7).
    assert {f["line"] for f in d["failed"]} == {2, 3, 4, 5, 6}


def test_import_preserves_id_and_data_on_commit(monkeypatch):
    c, store = _client(monkeypatch)
    csv_text = _csv([_row_dict(42, values={"k": "v"}, runtime={"current_index": 0})])
    c.post("/process-tickets/archive:import-csv", json={"csv": csv_text, "commit": True})
    assert len(store.created) == 1
    got = store.created[0]
    assert got["id"] == 42 and got["process_key"] == "demo"
    assert json.loads(got["values_json"]) == {"k": "v"}
    assert json.loads(got["runtime_json"]) == {"current_index": 0}
    assert got["created_at"] == "2026-01-01T09:00:00"      # originalgetreuer Restore


def test_export_then_import_round_trip(monkeypatch):
    # Export aus einem befüllten Store …
    c, src = _client(monkeypatch, rows=[_full_row(11), _full_row(12)])
    text = c.get("/process-tickets/archive.csv").content.decode("utf-8")
    # … und dieselbe Datei in einen LEEREN Store importieren (commit).
    c2, dst = _client(monkeypatch)
    r = c2.post("/process-tickets/archive:import-csv", json={"csv": text, "commit": True})
    d = r.json()["data"]
    assert d["counts"] == {"created": 2, "skipped": 0, "failed": 0}
    assert [row["id"] for row in dst.created] == [11, 12]
    assert json.loads(dst.created[0]["values_json"]) == {"name": "Öäü 11"}
