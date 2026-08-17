"""Ebene-1: System-Prozesse – automatisch beim Start, in der Oberfläche gesperrt.

Geprüft wird der Grund, aus dem es dieses Paket gibt: nach dem Deploy war die
Anwendung unbenutzbar, bis jemand von Hand ein Seed-Skript auf dem Server
ausführte. Also:

  * `ensure_system_processes` legt das Basis-Ticket beim ersten Start an und
    veröffentlicht es, tut beim zweiten Lauf NICHTS und macht aus einer
    geänderten Auslieferung eine NEUE Version (die alte bleibt stehen, sonst
    verlieren gepinnte Aufträge ihre Definition);
  * ein kaputter Seed warnt und verhindert den Start nicht;
  * jede Mutation an einem System-Prozess antwortet mit 403
    SYSTEM_PROCESS_READONLY – `:duplicate` auf einen anderen Key aber nicht;
  * `POST /processes:seed` ersetzt den Shell-Zugang für die übrigen neun.

Kein echtes MariaDB: Store und Gruppen-DB sind Attrappen.
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.v1 import processes as papi
from backend.core.dependencies import get_current_user
from backend.main import _install_error_handlers
from backend.schemas.process_definition import ProcessDefinition
from backend.seeds import PROCESS_SEED_DIR
from backend.services import process_delete as pdel
from backend.services import seed_definitions as sd

SYSTEM_KEY = "basis-ticket"
ADMIN = {"id": "u_admin", "displayName": "Admin", "permissions": ["admin"]}
MANAGER = {"id": "u_mgr", "displayName": "Verwaltung", "permissions": ["manage"]}


# ── Attrappen ────────────────────────────────────────────────────────────────

class FakeStore:
    """Ersatz für backend.database.process_definitions – nur die Wege, die
    ensure_system_processes benutzt, aber mit denselben Invarianten (höchstens
    eine veröffentlichte Version je Key, Versionen wachsen monoton)."""

    ProcessNotFound = sd.defstore.ProcessNotFound
    ProcessKeyExists = sd.defstore.ProcessKeyExists

    def __init__(self):
        self.zeilen: dict[str, list[dict]] = {}
        self.aufrufe: list[tuple] = []

    def _rows(self, key) -> list[dict]:
        return self.zeilen.setdefault(key, [])

    def _row(self, key, version) -> dict:
        for z in self._rows(key):
            if z["version"] == version:
                return z
        raise self.ProcessNotFound(f"{key} v{version}")

    # -- Lesen (wie die echten Projektionen: Liste OHNE definition, absteigend) --
    def list_versions(self, key):
        return [{k: v for k, v in z.items() if k != "definition"}
                for z in sorted(self._rows(key), key=lambda z: -z["version"])]

    def get_published(self, key):
        for z in self._rows(key):
            if z["status"] == "published":
                return dict(z)
        return None

    # -- Schreiben --
    def create_process(self, key, name, definition_json, by, by_name):
        if self._rows(key):
            raise self.ProcessKeyExists(key)
        self.aufrufe.append(("create", key, 1))
        self._rows(key).append({"key": key, "version": 1, "status": "draft", "name": name,
                                "definition": json.loads(definition_json),
                                "created_by": by, "created_by_name": by_name})
        return dict(self._rows(key)[-1])

    def create_or_get_draft(self, key, by, by_name):
        offen = [z for z in self._rows(key) if z["status"] == "draft"]
        if offen:
            return dict(offen[-1])
        pub = self.get_published(key)
        if not pub:
            raise self.ProcessNotFound(key)
        neu = {**pub, "version": max(z["version"] for z in self._rows(key)) + 1,
               "status": "draft", "base_version": pub["version"],
               "created_by": by, "created_by_name": by_name}
        self._rows(key).append(neu)
        self.aufrufe.append(("draft", key, neu["version"]))
        return dict(neu)

    def update_draft(self, key, version, name, definition_json, if_match=None):
        z = self._row(key, version)
        assert z["status"] == "draft", "nur Entwürfe sind schreibbar"
        z["name"] = name
        z["definition"] = json.loads(definition_json)
        self.aufrufe.append(("update", key, version))
        return dict(z)

    def publish(self, key, version):
        ziel = self._row(key, version)
        for z in self._rows(key):
            if z["status"] == "published":
                z["status"] = "archived"
        ziel["status"] = "published"
        self.aufrufe.append(("publish", key, version))
        return dict(ziel)


class FakeGroups:
    """Ersatz für backend.database.groups (nur was der Seeder benutzt)."""

    def __init__(self, namen):
        self.groups = [{"id": f"gid-{i}", "name": n} for i, n in enumerate(namen)]
        self.ensure_aufrufe: list[tuple] = []

    def get_groups(self):
        return [dict(g) for g in self.groups]

    def ensure_required_groups(self, required_names, hidden_names=None):
        self.ensure_aufrufe.append((list(required_names), list(hidden_names or [])))
        return []


@pytest.fixture
def store(monkeypatch) -> FakeStore:
    s = FakeStore()
    monkeypatch.setattr(sd, "defstore", s)
    return s


def _seed_datei(monkeypatch, tmp_path, inhalt, key=SYSTEM_KEY):
    """Ersetzt die Auslieferung durch eine eigene Datei.

    Der Name folgt der Konvention (`prozess-<key>.json`) – genau daran findet
    `system_seed_path` die Datei auch dann, wenn ihr Inhalt kaputt ist.
    """
    pfad = tmp_path / f"prozess-{key}.json"
    pfad.write_text(inhalt if isinstance(inhalt, str)
                    else json.dumps(inhalt, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(sd, "process_seed_files", lambda: [pfad])
    return pfad


def _ausgeliefert() -> dict:
    return json.loads((PROCESS_SEED_DIR / f"prozess-{SYSTEM_KEY}.json")
                      .read_text(encoding="utf-8"))


# ── Die ausgelieferte Definition selbst ──────────────────────────────────────

def test_ausgeliefertes_basis_ticket_ist_selbsttragend():
    """Der Grund, warum es beim Start automatisch gehen DARF und die anderen
    neun nicht: keine Gruppen-Auflösung nötig, für jede:n anlegbar."""
    roh = _ausgeliefert()
    assert sd.is_system_process(roh["key"])
    # Keine Gruppen-Referenz – die leere Menge bekannter IDs ist die Prüfung.
    assert sd.check_group_refs(roh, set()) == []
    assert sd.find_stray_placeholders(roh) == []
    assert roh["createPermissions"]["everyone"] is True
    # Die Zuständigkeit steht in einem FELD des Auftrags, nicht in der Definition.
    bearbeitung = roh["phases"][1]
    assert bearbeitung["responsibility"]["kind"] == "group_from_field"
    assert bearbeitung["responsibility"]["fromField"] == "ticket.fachabteilung"


def test_nur_das_basis_ticket_ist_system_prozess():
    assert sd.SYSTEM_PROCESS_KEYS == frozenset({SYSTEM_KEY})
    assert sd.is_system_process(SYSTEM_KEY) is True
    assert sd.is_system_process("hardware") is False
    assert sd.is_system_process(None) is False
    assert sd.is_system_process("") is False


# ── ensure_system_processes ──────────────────────────────────────────────────

def test_leere_datenbank_legt_an_und_veroeffentlicht(store):
    (o,) = sd.ensure_system_processes()
    assert (o.key, o.aktion, o.version) == (SYSTEM_KEY, "created", 1)

    pub = store.get_published(SYSTEM_KEY)
    assert pub and pub["version"] == 1
    # Anlegbar ab dem ersten Start – das war der ganze Zweck.
    assert pub["definition"]["createPermissions"]["everyone"] is True
    assert pub["created_by"] == sd.SYSTEM_ACTOR
    assert store.aufrufe == [("create", SYSTEM_KEY, 1), ("publish", SYSTEM_KEY, 1)]


def test_zweiter_lauf_tut_nichts(store):
    sd.ensure_system_processes()
    bisher = list(store.aufrufe)

    (o,) = sd.ensure_system_processes()
    assert o.aktion == "unchanged" and o.version == 1
    assert store.aufrufe == bisher          # keine zweite Version, kein Publish
    assert len(store.list_versions(SYSTEM_KEY)) == 1


def test_reine_umformatierung_erzeugt_keine_neue_version(store, monkeypatch, tmp_path):
    """Verglichen wird der INHALT. Sonst legte jeder Start eine neue Version an,
    sobald jemand die JSON umformatiert oder ein Feld verschiebt."""
    sd.ensure_system_processes()
    umformatiert = json.dumps(_ausgeliefert(), indent=4, sort_keys=True, ensure_ascii=False)
    _seed_datei(monkeypatch, tmp_path, umformatiert)

    (o,) = sd.ensure_system_processes()
    assert o.aktion == "unchanged"
    assert len(store.list_versions(SYSTEM_KEY)) == 1


def test_geaenderte_auslieferung_erzeugt_eine_neue_version(store, monkeypatch, tmp_path):
    """Ein Update ist eine NEUE Version, kein Überschreiben: Aufträge pinnen ihre
    Version und müssen ihre Definition weiter lesen können."""
    sd.ensure_system_processes()
    alt = dict(store.get_published(SYSTEM_KEY)["definition"])

    neu = _ausgeliefert()
    neu["name"] = "Basis-Ticket (überarbeitet)"
    _seed_datei(monkeypatch, tmp_path, neu)

    (o,) = sd.ensure_system_processes()
    assert o.aktion == "updated" and o.version == 2

    versionen = {v["version"]: v["status"] for v in store.list_versions(SYSTEM_KEY)}
    assert versionen == {1: "archived", 2: "published"}
    # v1 ist unverändert lesbar – genau das braucht ein laufender Auftrag.
    assert store._row(SYSTEM_KEY, 1)["definition"] == alt
    pub = store.get_published(SYSTEM_KEY)
    assert pub["name"] == "Basis-Ticket (überarbeitet)"
    assert pub["definition"]["name"] == "Basis-Ticket (überarbeitet)"


def test_offener_entwurf_wird_veroeffentlicht_statt_uebergangen(store):
    """Hinterlässt ein abgebrochener Lauf einen Entwurf ohne veröffentlichte
    Version, ist der Prozess nicht anlegbar – der nächste Start muss ihn
    fertigmachen, nicht daneben eine weitere Baustelle aufmachen."""
    roh = ProcessDefinition.model_validate(_ausgeliefert()).model_dump(by_alias=True)
    store.create_process(SYSTEM_KEY, "Basis-Ticket", json.dumps(roh), "x", "X")
    store.aufrufe.clear()

    (o,) = sd.ensure_system_processes()
    assert o.aktion == "created" and o.version == 1
    assert store.get_published(SYSTEM_KEY)["version"] == 1
    assert len(store.list_versions(SYSTEM_KEY)) == 1


def test_kaputte_json_warnt_statt_abzubrechen(store, monkeypatch, tmp_path):
    """Ein Fehlschlag hier darf den Anwendungsstart nicht verhindern."""
    _seed_datei(monkeypatch, tmp_path, "{ das ist kein JSON")

    (o,) = sd.ensure_system_processes()      # wirft NICHT
    assert o.aktion == "error" and o.key == SYSTEM_KEY
    assert store.aufrufe == [] and store.list_versions(SYSTEM_KEY) == []


def test_gruppen_referenz_macht_den_prozess_untauglich(store, monkeypatch, tmp_path):
    """Gruppen-IDs sind pro Installation verschieden. Ein System-Prozess, der eine
    braucht, ist keiner – lieber nichts einspielen als etwas dauerhaft Kaputtes."""
    kaputt = _ausgeliefert()
    kaputt["phases"][1]["responsibility"] = {"kind": "group",
                                             "group": "HIER_GRUPPEN_ID_IT_EINSETZEN"}
    _seed_datei(monkeypatch, tmp_path, kaputt)

    (o,) = sd.ensure_system_processes()
    assert o.aktion == "error"
    assert "selbsttragend" in o.meldung
    assert store.aufrufe == []


def test_fehlende_ausgelieferte_datei_ist_eine_warnung(store, monkeypatch):
    monkeypatch.setattr(sd, "process_seed_files", lambda: [])
    (o,) = sd.ensure_system_processes()
    assert o.aktion == "error" and store.aufrufe == []


def test_seed_datei_wird_auch_bei_anderem_namen_gefunden(monkeypatch, tmp_path):
    """Die Konvention ist der schnelle Weg, der Inhalt der verlässliche."""
    pfad = tmp_path / "irgendwas.json"
    pfad.write_text(json.dumps({"key": SYSTEM_KEY}), encoding="utf-8")
    kaputt = tmp_path / "prozess-hardware.json"
    kaputt.write_text("{kaputt", encoding="utf-8")
    monkeypatch.setattr(sd, "process_seed_files", lambda: [kaputt, pfad])

    assert sd.system_seed_path(SYSTEM_KEY) == pfad
    assert sd.system_seed_path("gibt-es-nicht") is None


# ── API: Nicht-Änderbarkeit ──────────────────────────────────────────────────

def _defn(key: str) -> dict:
    """Kleinste valide Definition – der Body muss durch das Schema kommen,
    sonst antwortete FastAPI mit 422 und die Sperre wäre nicht geprüft."""
    return {
        "schemaVersion": 1, "key": key, "name": "Test",
        "fields": [{"key": "base.name", "widget": "text"}],
        "phases": [
            {"key": "erstellung", "kind": "start", "responsibility": {"kind": "owner"},
             "fields": [{"ref": "base.name", "required": True}]},
            {"key": "bearbeitung", "kind": "task", "responsibility": {"kind": "owner"},
             "fields": [{"ref": "base.name", "mode": "readonly"}]},
        ],
    }


class FakeDefs:
    """Ersatz für den Store IN DER API. Antwortet auf alles freundlich – wenn ein
    gesperrter Endpunkt hier ankommt, fällt das als 200 statt 403 auf."""

    ProcessNotFound = papi.db.ProcessNotFound
    ProcessKeyExists = papi.db.ProcessKeyExists
    ProcessInvalidState = papi.db.ProcessInvalidState
    ProcessVersionInUse = papi.db.ProcessVersionInUse
    ProcessVersionConflict = papi.db.ProcessVersionConflict

    def __init__(self):
        self.schreibzugriffe: list[str] = []

    def _row(self, key, version=1, status="published"):
        return {"id": 1, "key": key, "version": version, "status": status,
                "name": "Test", "definition_json": json.dumps(_defn(key)),
                "definition": _defn(key), "rev": 0, "etag": "0"}

    def get_published(self, key):
        return self._row(key)

    def get_definition(self, key, version):
        return self._row(key, version=version)

    def list_versions(self, key):
        return [self._row(key)]

    def process_overview(self, key):
        return {"key": key, "name": "Test", "tickets": 0,
                "versions": [{"version": 1, "status": "published", "rev": 0, "tickets": 0}],
                "fingerprint": "1:published:0:0"}

    def create_process(self, key, name, definition_json, by, by_name):
        self.schreibzugriffe.append(f"create:{key}")
        return self._row(key, status="draft")

    def create_or_get_draft(self, key, by, by_name):
        self.schreibzugriffe.append(f"draft:{key}")
        return self._row(key, version=2, status="draft")

    def update_draft(self, key, version, name, definition_json, if_match=None):
        self.schreibzugriffe.append(f"update:{key}")
        return self._row(key, version=version, status="draft")

    def publish(self, key, version):
        self.schreibzugriffe.append(f"publish:{key}")
        return self._row(key, version=version)

    def duplicate(self, src_key, new_key, definition_json, name, by, by_name):
        self.schreibzugriffe.append(f"duplicate:{new_key}")
        return self._row(new_key, status="draft")

    def delete_version(self, key, version):
        self.schreibzugriffe.append(f"delete:{key}")

    def delete_process(self, key):
        self.schreibzugriffe.append(f"delete_process:{key}")
        return 1

    def list_published_catalog(self, include_definition=False):
        return [self._row(SYSTEM_KEY), self._row("hardware")]

    def is_disabled(self, key):
        return False

    def disabled_keys(self):
        return set()


@pytest.fixture
def api(monkeypatch):
    defs = FakeDefs()
    monkeypatch.setattr(papi, "db", defs)
    monkeypatch.setattr(papi, "record_audit", lambda **kw: None)
    monkeypatch.setattr(papi, "get_group_ids_for_user", lambda uid: [])
    monkeypatch.setattr(papi.config, "FRONTEND_URL", "https://app.example.org")
    monkeypatch.setattr(pdel.config, "ADMIN_MAIL", "admin@example.org")

    state = {"user": dict(ADMIN)}
    app = FastAPI()
    _install_error_handlers(app)
    app.include_router(papi.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    return TestClient(app), state, defs


def _gesperrt(client, methode: str, pfad: str, **kw):
    r = getattr(client, methode)(f"/api/v1{pfad}", **kw)
    assert r.status_code == 403, (pfad, r.status_code, r.text)
    assert r.json()["error"]["code"] == "SYSTEM_PROCESS_READONLY", pfad
    return r


def test_entwurf_anlegen_ist_gesperrt(api):
    client, _s, defs = api
    _gesperrt(client, "post", f"/processes/{SYSTEM_KEY}/versions")
    _gesperrt(client, "post", "/processes", json=_defn(SYSTEM_KEY))
    assert defs.schreibzugriffe == []


def test_entwurf_speichern_ist_gesperrt(api):
    client, _s, defs = api
    _gesperrt(client, "put", f"/processes/{SYSTEM_KEY}/versions/1", json=_defn(SYSTEM_KEY))
    assert defs.schreibzugriffe == []


def test_veroeffentlichen_ist_gesperrt(api):
    client, _s, defs = api
    _gesperrt(client, "post", f"/processes/{SYSTEM_KEY}/versions/1:publish")
    assert defs.schreibzugriffe == []


def test_version_loeschen_ist_gesperrt(api):
    client, _s, defs = api
    _gesperrt(client, "delete", f"/processes/{SYSTEM_KEY}/versions/1")
    assert defs.schreibzugriffe == []


def test_loeschung_anfordern_ist_gesperrt(api):
    client, _s, defs = api
    _gesperrt(client, "post", f"/processes/{SYSTEM_KEY}:request-delete",
              json={"includeTickets": True})
    assert defs.schreibzugriffe == []


def test_loeschung_bestaetigen_ist_gesperrt(api):
    """Der Key steht im TOKEN – ein Token aus der Zeit vor der Aufnahme in
    SYSTEM_PROCESS_KEYS darf nicht an der Sperre vorbeikommen."""
    client, _s, defs = api
    token = pdel.make_token(SYSTEM_KEY, defs.process_overview(SYSTEM_KEY),
                            requested_by="u_admin", include_tickets=True)
    _gesperrt(client, "post", "/processes:confirm-delete", json={"token": token})
    assert defs.schreibzugriffe == []


def test_import_auf_einen_system_key_ist_gesperrt(api):
    client, _s, defs = api
    _gesperrt(client, "post", "/processes:import",
              json={"targetKey": SYSTEM_KEY, "definition": _defn("egal")})
    assert defs.schreibzugriffe == []


def test_duplizieren_auf_einen_anderen_key_ist_erlaubt(api):
    """Aus dem Basis-Ticket eine eigene, änderbare Fassung machen ist der
    vorgesehene Weg – nur das ZIEL darf kein System-Key sein."""
    client, _s, defs = api
    r = client.post(f"/api/v1/processes/{SYSTEM_KEY}:duplicate",
                    json={"newKey": "eigenes-ticket"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["key"] == "eigenes-ticket"
    assert r.json()["data"]["is_system"] is False
    assert defs.schreibzugriffe == ["duplicate:eigenes-ticket"]


def test_duplizieren_auf_einen_system_key_ist_gesperrt(api):
    client, _s, defs = api
    _gesperrt(client, "post", "/processes/hardware:duplicate", json={"newKey": SYSTEM_KEY})
    assert defs.schreibzugriffe == []


def test_lesen_und_exportieren_bleiben_erlaubt(api):
    client, *_ = api
    assert client.get(f"/api/v1/processes/{SYSTEM_KEY}").status_code == 200
    assert client.get(f"/api/v1/processes/{SYSTEM_KEY}/versions").status_code == 200
    assert client.get(f"/api/v1/processes/{SYSTEM_KEY}/versions/1").status_code == 200
    assert client.get(f"/api/v1/processes/{SYSTEM_KEY}/versions/1:export").status_code == 200


def test_is_system_steht_auf_jedem_rueckgabe_pfad(api):
    """Die Oberfläche soll die Knöpfe gar nicht erst anbieten – dafür muss die
    Angabe überall mitkommen, nicht nur im Katalog."""
    client, *_ = api
    katalog = {p["key"]: p["is_system"] for p in client.get("/api/v1/processes").json()["data"]}
    assert katalog == {SYSTEM_KEY: True, "hardware": False}

    for pfad in (f"/processes/{SYSTEM_KEY}",
                 f"/processes/{SYSTEM_KEY}/versions/1"):
        assert client.get(f"/api/v1{pfad}").json()["data"]["is_system"] is True
    (v,) = client.get(f"/api/v1/processes/{SYSTEM_KEY}/versions").json()["data"]
    assert v["is_system"] is True
    assert client.get("/api/v1/processes/hardware").json()["data"]["is_system"] is False


# ── API: POST /processes:seed ────────────────────────────────────────────────

@pytest.fixture
def seed_api(api, monkeypatch):
    """Wie `api`, aber mit Attrappen HINTER dem Seeder-Lauf (Gruppen + Store)."""
    client, state, _defs = api
    groups = FakeGroups([n.lower() for n in sd.required_group_names()])
    store = FakeStore()
    monkeypatch.setattr(sd, "groupsdb", groups)
    monkeypatch.setattr(sd, "defstore", store)
    monkeypatch.setattr(sd.backfill, "load_legacy_permissions", lambda: ({}, {}))
    return client, state, groups, store


def _seed(client, **body):
    return client.post("/api/v1/processes:seed", json=body or {})


def test_trockenlauf_ist_der_standard_und_schreibt_nichts(seed_api):
    client, _state, groups, store = seed_api
    r = _seed(client)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["commit"] is False
    assert store.aufrufe == [] and groups.ensure_aufrufe == []
    assert d["created"] == 9 and d["skipped"] == 1 and d["errors"] == 0
    assert all(o["action"] == "would_create"
               for o in d["outcomes"] if o["key"] != SYSTEM_KEY)

    # Auch ganz ohne Body – ein leerer Aufruf darf nicht versehentlich schreiben.
    r = client.post("/api/v1/processes:seed")
    assert r.status_code == 200 and r.json()["data"]["commit"] is False
    assert store.aufrufe == []


def test_bericht_traegt_dieselben_angaben_wie_das_skript(seed_api):
    client, *_ = seed_api
    d = _seed(client).json()["data"]
    assert d["required_groups"] == sd.required_group_names()
    assert d["missing_groups"] == [] and d["created_groups"] == []
    o = next(o for o in d["outcomes"] if o["key"] == "hardware")
    assert o["file"] == "prozess-hardware.json"
    assert o["message"] and o["action"] == "would_create"
    assert o["warnings"] == [] and o["ineffective_groups"] == []


def test_fehlende_pflichtgruppen_stehen_im_trockenlauf(api, monkeypatch):
    """Der Trockenlauf soll SAGEN, was --commit anlegen würde."""
    client, _state, _defs = api
    monkeypatch.setattr(sd, "groupsdb", FakeGroups([]))
    monkeypatch.setattr(sd, "defstore", FakeStore())
    monkeypatch.setattr(sd.backfill, "load_legacy_permissions", lambda: ({}, {}))
    d = _seed(client).json()["data"]
    assert sorted(d["missing_groups"]) == sorted(sd.required_group_names())
    assert d["errors"] == 0


def test_commit_spielt_die_neun_ein(seed_api):
    client, _state, _groups, store = seed_api
    d = _seed(client, commit=True).json()["data"]
    assert d["commit"] is True and d["created"] == 9 and d["errors"] == 0
    angelegt = [k for _a, k, _v in store.aufrufe if _a == "create"]
    assert len(angelegt) == 9 and SYSTEM_KEY not in angelegt


def test_system_prozess_wird_uebersprungen_mit_notiz(seed_api):
    client, _state, _groups, store = seed_api
    d = _seed(client, commit=True).json()["data"]
    o = next(o for o in d["outcomes"] if o["key"] == SYSTEM_KEY)
    assert o["action"] == "skipped" and "System-Prozess" in o["message"]
    # Als Merkmal, nicht nur als Satz: die Oberfläche soll die Zeile
    # kennzeichnen können, ohne Text zu durchsuchen.
    assert o["is_system"] is True
    assert [o["is_system"] for o in d["outcomes"] if o["key"] == "hardware"] == [False]
    assert [k for _a, k, _v in store.aufrufe if k == SYSTEM_KEY] == []


def test_seed_nur_fuer_admins(seed_api):
    client, state, _groups, store = seed_api
    state["user"] = dict(MANAGER)
    r = _seed(client, commit=True)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "ADMIN_REQUIRED"
    assert store.aufrufe == []


def test_seed_wird_auditiert(seed_api, monkeypatch):
    client, *_ = seed_api
    eintraege: list[dict] = []
    monkeypatch.setattr(papi, "record_audit", lambda **kw: eintraege.append(kw))
    _seed(client, commit=True)
    (e,) = eintraege
    assert e["action"] == "processes_seeded" and e["actor_id"] == "u_admin"
    assert e["details"]["commit"] is True and e["details"]["created"] == 9


def test_kaputte_installation_wird_als_konflikt_gemeldet(api, monkeypatch):
    """Mehrdeutige Gruppennamen sind ein Zustand der Installation, kein
    Serverfehler – und der Knopf muss das sagen dürfen."""
    client, _state, _defs = api

    def boom(*a, **k):
        raise sd.SeedError("Mehrdeutige Gruppennamen")
    monkeypatch.setattr(sd, "seed_processes", boom)
    r = _seed(client, commit=True)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "PROCESS_SEED_FAILED"
    assert "Mehrdeutige" in r.json()["error"]["message"]
