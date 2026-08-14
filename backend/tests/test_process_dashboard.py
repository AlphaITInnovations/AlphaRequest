"""Ebene-1: Prozess-Aufträge im Dashboard – ohne DB.

Der Store (`backend.database.process_tickets`) und die Definitions-Persistenz
werden durch In-Memory-Fakes ersetzt. Geprüft wird das, was schiefgehen KANN:
  * Sichtbarkeit: der Block zeigt ausschließlich, was may_view freigibt,
  * N+1: gepinnte Definitionen werden je (key, version) genau einmal geladen,
  * Datenschutz: es gelangen keine Feldwerte in die Dashboard-Antwort.

Die Prometheus-Kennzahlen der Prozess-Aufträge hängen nicht mehr am Alt-System
und haben eine eigene Datei: backend/tests/test_process_metrics.py.
"""
import pytest

from backend.api.v1 import dashboard as dash
from backend.services import process_visibility as vis


DEFN = {
    "schemaVersion": 1, "key": "demo", "name": "Demo-Prozess",
    "fields": [{"key": "base.name", "widget": "text"}],
    "phases": [
        {"key": "start", "kind": "start", "label": "Erfassung",
         "responsibility": {"kind": "owner"},
         "fields": [{"ref": "base.name", "mode": "editable"}]},
        {"key": "review", "kind": "review", "label": "Prüfung IT",
         "responsibility": {"kind": "departments", "rule": [{"group": "g_it"}]},
         "fields": [{"ref": "base.name", "mode": "readonly"}]},
    ],
}


def _runtime(index: int) -> dict:
    """Ablaufzustand mit `index` als aktiver Phase (wie process_runtime ihn baut)."""
    phases = [
        {"key": "start", "status": "done" if index > 0 else "open",
         "entered_at": "2026-01-01T00:00:00", "departments": []},
        {"key": "review", "status": "open" if index == 1 else "pending",
         "entered_at": None,
         "departments": [{"group": "g_it", "required": True, "status": "open"}]
                        if index == 1 else []},
    ]
    return {"current_index": index, "epoch": 0, "rejected": False,
            "sla_paused_ms": 0, "phases": phases}


def _row(tid: int, *, owner: str, index: int, status: str = "in_progress",
         version: int = 1, title: str = "Auftrag") -> dict:
    """Listen-Zeile, wie sie der Store liefert: MIT runtime, OHNE values."""
    return {"id": tid, "process_key": "demo", "process_version": version,
            "title": title, "status": status, "priority": "normal",
            "owner_id": owner, "owner_name": owner, "rev": 0,
            "next_timer_due_at": None,
            "created_at": "2026-01-01T08:00:00", "updated_at": "2026-01-02T08:00:00",
            "runtime": _runtime(index)}


class FakeStore:
    """Nur die Lese-Helfer, die das Dashboard braucht."""

    def __init__(self, rows: list[dict]):
        self.rows = rows

    def list_for_owner(self, owner_id, limit=25, *, active_only=True, include_runtime=False):
        return [dict(r) for r in self.rows if r["owner_id"] == owner_id]

    def list_active(self, limit=200, *, include_runtime=True):
        return [dict(r) for r in self.rows
                if r["status"] not in ("archived", "rejected")]


class FakeDefs:
    def __init__(self):
        self.loads = 0

    def get_definition(self, key, version):
        self.loads += 1
        if key != "demo":
            return None
        return {"version": version, "definition": DEFN}


@pytest.fixture(autouse=True)
def no_group_db(monkeypatch):
    """Gruppen-Mitgliedschaft aus dem User-Dict statt aus der DB."""
    monkeypatch.setattr(vis, "user_group_ids", lambda user: set(user.get("groups") or []))


@pytest.fixture
def defs(monkeypatch):
    d = FakeDefs()
    monkeypatch.setattr(dash, "defstore", d)
    return d


def _use_rows(monkeypatch, rows: list[dict]) -> FakeStore:
    store = FakeStore(rows)
    monkeypatch.setattr(dash, "pstore", store)
    return store


def _user(uid: str, *, groups=(), permissions=()) -> dict:
    return {"id": uid, "displayName": uid, "groups": list(groups),
            "permissions": list(permissions)}


# ── Sichtbarkeit ─────────────────────────────────────────────────────────────

def test_involved_nur_was_may_view_freigibt(monkeypatch, defs):
    """u2 ist Mitglied von g_it: nur der Auftrag in der IT-Phase ist sichtbar."""
    _use_rows(monkeypatch, [
        _row(1, owner="u1", index=1, title="bei der IT"),      # Phase „Prüfung IT"
        _row(2, owner="u1", index=0, title="beim Ersteller"),  # Phase „Erfassung"
    ])
    block = dash._process_block(_user("u2", groups=["g_it"]))
    assert [t.id for t in block.involved] == [1]
    assert block.involved[0].phase == "review"
    assert block.involved[0].phase_label == "Prüfung IT"
    assert block.my == []


def test_ohne_beteiligung_und_ohne_rechte_leer(monkeypatch, defs):
    _use_rows(monkeypatch, [_row(1, owner="u1", index=1)])
    block = dash._process_block(_user("fremd", groups=["g_hr"]))
    assert block.my == [] and block.involved == [] and block.counts == {}


def test_aufsicht_sieht_alle_aktiven(monkeypatch, defs):
    _use_rows(monkeypatch, [_row(1, owner="u1", index=1), _row(2, owner="u1", index=0)])
    block = dash._process_block(_user("pruefer", permissions=["view"]))
    assert sorted(t.id for t in block.involved) == [1, 2]


def test_eigene_stehen_unter_my(monkeypatch, defs):
    _use_rows(monkeypatch, [
        _row(1, owner="u1", index=0),
        _row(2, owner="u2", index=1),
    ])
    _beobachtet(monkeypatch, [])
    block = dash._process_block(_user("u1", groups=["g_it"]))
    assert [t.id for t in block.my] == [1]
    assert block.my[0].is_owner is True
    # #2 liegt bei g_it → beteiligt.
    assert [t.id for t in block.involved] == [2]
    assert block.involved[0].is_owner is False


def test_terminale_auftraege_erscheinen_nicht(monkeypatch, defs):
    _use_rows(monkeypatch, [_row(1, owner="u1", index=1, status="archived")])
    block = dash._process_block(_user("u2", groups=["g_it"], permissions=["view"]))
    assert block.involved == []


# ── Zähler ───────────────────────────────────────────────────────────────────

def test_counts_nur_ueber_sichtbare_auftraege(monkeypatch, defs):
    _use_rows(monkeypatch, [
        _row(1, owner="u2", index=1, status="in_request"),
        _row(2, owner="u2", index=1, status="in_request"),
        _row(3, owner="u1", index=0, status="in_progress"),   # für u2 unsichtbar
    ])
    block = dash._process_block(_user("u2", groups=["g_it"]))
    # #1/#2 gehören u2 (my), #3 ist unsichtbar → in_progress kommt NICHT vor.
    assert block.counts == {"in_request": 2}


# ── N+1: Definitionen ────────────────────────────────────────────────────────

def test_definition_wird_je_pin_nur_einmal_geladen(monkeypatch, defs):
    rows = [_row(i, owner="u1", index=1) for i in range(1, 6)]
    _use_rows(monkeypatch, rows)
    block = dash._process_block(_user("u2", groups=["g_it"]))
    assert len(block.involved) == 5
    assert defs.loads == 1, f"{defs.loads} Ladevorgänge für 5 Zeilen derselben Version"


def test_je_version_ein_ladevorgang(monkeypatch, defs):
    _use_rows(monkeypatch, [
        _row(1, owner="u1", index=1, version=1),
        _row(2, owner="u1", index=1, version=1),
        _row(3, owner="u1", index=1, version=2),
    ])
    dash._process_block(_user("u2", groups=["g_it"]))
    assert defs.loads == 2


def test_kaputter_pin_kippt_das_dashboard_nicht(monkeypatch, defs):
    class Broken:
        def __init__(self):
            self.loads = 0

        def get_definition(self, key, version):
            self.loads += 1
            raise RuntimeError("DB weg")

    broken = Broken()
    monkeypatch.setattr(dash, "defstore", broken)
    _use_rows(monkeypatch, [_row(1, owner="u1", index=1), _row(2, owner="u1", index=1)])
    # Ohne Definition greift Default-Deny (keine Zuständigkeit ableitbar).
    block = dash._process_block(_user("u2", groups=["g_it"]))
    assert block.involved == []
    # …und auch der Fehlversuch wird gecacht (ein Versuch je Pin, kein N+1).
    assert broken.loads == 1


# ── Keine Feldwerte im Dashboard ─────────────────────────────────────────────

def test_keine_feldwerte_in_der_antwort(monkeypatch, defs):
    """Selbst wenn der Store Werte mitliefert, dürfen sie nicht ausgegeben werden."""
    row = _row(1, owner="u1", index=1)
    row["values"] = {"base.name": "GEHEIM"}
    row["values_json"] = '{"base.name": "GEHEIM"}'
    _use_rows(monkeypatch, [row])
    block = dash._process_block(_user("u1", groups=["g_it"]))
    payload = block.model_dump_json()
    assert "GEHEIM" not in payload
    assert "values" not in payload and "runtime" not in payload
    # Ausgegeben werden nur Kopfdaten.
    assert set(block.my[0].model_dump()) == {
        "id", "process_key", "process_version", "title", "status", "priority",
        "phase", "phase_label", "is_owner", "created_at", "updated_at"}


def test_store_fehler_liefert_leeren_block(monkeypatch, defs):
    class Boom:
        def list_for_owner(self, *a, **k):
            raise RuntimeError("Tabelle fehlt")

        def list_active(self, *a, **k):
            raise RuntimeError("Tabelle fehlt")

    monkeypatch.setattr(dash, "pstore", Boom())
    block = dash._process_block_safe(_user("u1"))
    assert block.my == [] and block.involved == [] and block.counts == {}


def test_antwort_enthaelt_nur_noch_prozess_und_fachabteilungen():
    """Nach dem Rückbau des Alt-Systems trägt die Antwort genau zwei Schlüssel:
    den Prozess-Block und die Fachabteilungen des Nutzers. Die Klammer `process`
    bleibt bewusst stehen, damit `data.process.*` im Frontend gültig bleibt."""
    keys = set(dash.DashboardResponse.model_fields)
    assert keys == {"my_departments", "process"}
    # Die Alt-Schlüssel sind weg – sonst liest das Frontend leere Listen als „nichts zu tun".
    assert not ({"orders", "watched_orders", "department_board",
                 "allowed_ticket_types"} & keys)


# ── Beobachtet vs. beteiligt ─────────────────────────────────────────────────

def _beobachtet(monkeypatch, ids):
    """Beobachtungen dieser Person vorgeben (sonst DB-Zugriff)."""
    monkeypatch.setattr(dash, "_watched_ticket_ids", lambda uid: set(ids))


def test_beobachteter_auftrag_erscheint_ueberhaupt(monkeypatch, defs):
    """Vorher fehlte er VOLLSTÄNDIG: may_view wurde ohne Beobachter-IDs gerufen –
    man konnte einen Auftrag abonnieren und bekam ihn nie zu sehen."""
    _use_rows(monkeypatch, [_row(1, owner="u1", index=1, title="bei der IT")])
    _beobachtet(monkeypatch, [1])
    block = dash._process_block(_user("u_fremd"))          # keine Gruppe, keine Rechte
    assert [t.id for t in block.watched] == [1]
    assert block.involved == [] and block.my == []


def test_ohne_beobachtung_bleibt_fremdes_unsichtbar(monkeypatch, defs):
    _use_rows(monkeypatch, [_row(1, owner="u1", index=1)])
    _beobachtet(monkeypatch, [])
    block = dash._process_block(_user("u_fremd"))
    assert block.watched == [] and block.involved == []


def test_beobachtet_und_beteiligt_sind_getrennt(monkeypatch, defs):
    """Ein Auftrag steht in GENAU einer der beiden Listen – sonst wären die Zahlen
    nicht einzeln lesbar."""
    _use_rows(monkeypatch, [
        _row(1, owner="u1", index=1, title="beobachtet UND zuständig"),
        _row(2, owner="u1", index=1, title="nur zuständig"),
    ])
    _beobachtet(monkeypatch, [1])
    block = dash._process_block(_user("u2", groups=["g_it"]))
    assert [t.id for t in block.watched] == [1]
    assert [t.id for t in block.involved] == [2]


def test_eigene_auftraege_findet_man_unter_beobachtet(monkeypatch, defs):
    """Wer anlegt, wird automatisch Beobachter:in – und genau darüber findet man
    den eigenen Auftrag wieder, auch wenn er längst bei einer Fachabteilung liegt.
    Ohne das wäre er nach dem Wegfall der Kachel „Von mir angelegt" auf der
    Übersicht unsichtbar."""
    _use_rows(monkeypatch, [_row(1, owner="u1", index=1, title="jetzt bei der IT")])
    _beobachtet(monkeypatch, [1])
    block = dash._process_block(_user("u1"))
    assert [t.id for t in block.watched] == [1]
    assert block.involved == []


def test_counts_zaehlen_einen_auftrag_nur_einmal(monkeypatch, defs):
    """Ein eigener Auftrag steht in `my` UND (als Beobachtung) in `watched` –
    der Zähler darf ihn deshalb nicht doppelt führen."""
    _use_rows(monkeypatch, [_row(1, owner="u1", index=1, status="in_request")])
    _beobachtet(monkeypatch, [1])
    block = dash._process_block(_user("u1"))
    assert block.counts == {"in_request": 1}


def test_counts_zaehlen_auch_beobachtete(monkeypatch, defs):
    _use_rows(monkeypatch, [_row(1, owner="u1", index=1, status="in_request")])
    _beobachtet(monkeypatch, [1])
    block = dash._process_block(_user("u_fremd"))
    assert block.counts == {"in_request": 1}


def test_fehler_beim_laden_der_beobachtungen_kippt_nichts(monkeypatch, defs):
    """fail-closed: es fehlt höchstens eine Liste, es erscheint nichts Fremdes."""
    _use_rows(monkeypatch, [_row(1, owner="u1", index=1)])

    def boom(uid):
        raise RuntimeError("Tabelle fehlt")
    monkeypatch.setattr(dash, "_watched_ticket_ids", boom)
    block = dash._process_block_safe(_user("u2", groups=["g_it"]))
    # Der geschützte Pfad liefert im Fehlerfall einen leeren Block.
    assert block.watched == []
