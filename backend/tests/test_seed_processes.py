"""Ebene-1: Seeder für die ausgelieferten Prozess-Definitionen (DB-frei).

Die echten Seeds unter `backend/seeds/processes/` werden mitgeprüft – sie sind
der kritische Pfad: ohne sie gibt es nach dem Cutover keinen anlegbaren Prozess.
Gruppen-DB und Definitions-Store sind durch In-Memory-Attrappen ersetzt.
"""
import json

import pytest

from backend.schemas.process_definition import ProcessDefinition
from backend.seeds import PROCESS_SEED_DIR, process_seed_files
from backend.services import seed_definitions as sd


# ── Attrappen ────────────────────────────────────────────────────────────────

class FakeGroups:
    """Ersatz für backend.database.groups (nur was der Seeder benutzt)."""

    def __init__(self, namen):
        self.groups = [{"id": f"gid-{i}", "name": n} for i, n in enumerate(namen)]
        self.ensure_aufrufe: list[tuple] = []

    def get_groups(self):
        return [dict(g) for g in self.groups]

    def ensure_required_groups(self, required_names, hidden_names=None):
        self.ensure_aufrufe.append((list(required_names), list(hidden_names or [])))
        vorhanden = {g["name"].strip().lower() for g in self.groups}
        neu = []
        for name in required_names:
            if name.strip().lower() in vorhanden:
                continue
            self.groups.append({"id": f"gid-neu-{len(self.groups)}", "name": name})
            vorhanden.add(name.strip().lower())
            neu.append(name)
        return neu


class FakeStore:
    """Ersatz für backend.database.process_definitions."""

    ProcessKeyExists = sd.defstore.ProcessKeyExists

    def __init__(self, vorhanden: dict | None = None):
        self.versionen = vorhanden or {}
        self.created: list[tuple] = []
        self.published: list[tuple] = []

    def list_versions(self, key):
        return list(self.versionen.get(key, []))

    def create_process(self, key, name, definition_json, by, by_name):
        self.created.append((key, name, definition_json, by, by_name))
        self.versionen.setdefault(key, []).append({"version": 1, "status": "draft"})
        return {"key": key, "version": 1}

    def publish(self, key, version):
        self.published.append((key, version))
        return {"key": key, "version": version}


@pytest.fixture
def umgebung(monkeypatch):
    """Alle Pflichtgruppen vorhanden – bewusst KLEINGESCHRIEBEN, damit jede
    Auflösung case-insensitiv erfolgen muss."""
    groups = FakeGroups([n.lower() for n in sd.required_group_names()])
    store = FakeStore()
    monkeypatch.setattr(sd, "groupsdb", groups)
    monkeypatch.setattr(sd, "defstore", store)
    return groups, store


def _nur(monkeypatch, tmp_path, defn: dict, dateiname="prozess-test.json"):
    """Ersetzt die Seed-Liste durch genau eine selbst gebaute Definition."""
    pfad = tmp_path / dateiname
    pfad.write_text(json.dumps(defn, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(sd, "process_seed_files", lambda: [pfad])
    return pfad


def _minimal(**extra) -> dict:
    d = {
        "schemaVersion": 1, "key": "test-prozess", "name": "Test",
        "fields": [{"key": "base.name", "widget": "text"}],
        "phases": [
            {"key": "erstellung", "kind": "start", "responsibility": {"kind": "owner"},
             "fields": [{"ref": "base.name", "required": True}]},
            {"key": "bearbeitung", "kind": "task",
             "responsibility": {"kind": "group", "group": "HIER_GRUPPEN_ID_IT_EINSETZEN"},
             "fields": [{"ref": "base.name", "mode": "readonly"}]},
        ],
    }
    d.update(extra)
    return d


# ── Die ausgelieferten Seeds ─────────────────────────────────────────────────

def test_es_sind_zehn_seeds_und_sie_liegen_unter_backend():
    dateien = process_seed_files()
    assert len(dateien) == 10, [p.name for p in dateien]
    # Pfad relativ zu __file__, nicht zum cwd – im Container ist das cwd /app.
    assert PROCESS_SEED_DIR.parts[-3:] == ("backend", "seeds", "processes")


def test_alle_seeds_validieren_nach_der_aufloesung():
    index = {n.lower(): f"gid-{i}" for i, n in enumerate(sd.required_group_names())}
    mapping = sd.build_placeholder_mapping(index)
    bekannt = set(index.values())

    geprueft = 0
    for pfad in process_seed_files():
        roh = json.loads(pfad.read_text(encoding="utf-8"))
        aufgeloest = sd.replace_placeholders(roh, mapping)
        assert sd.check_group_refs(aufgeloest, bekannt) == [], pfad.name
        assert sd.find_stray_placeholders(aufgeloest) == [], pfad.name
        ProcessDefinition.model_validate(aufgeloest)
        geprueft += 1
    assert geprueft == 10


def test_platzhalter_abbildung_deckt_alle_vorkommen_ab():
    """Kein Seed darf einen Platzhalter enthalten, den die Konstante nicht kennt."""
    bekannt = set(sd.PLACEHOLDER_GROUP_NAMES)
    gefunden: set[str] = set()
    for pfad in process_seed_files():
        text = pfad.read_text(encoding="utf-8")
        gefunden |= set(sd._PLACEHOLDER_RE.findall(text))
    assert gefunden <= bekannt, gefunden - bekannt
    # …und umgekehrt keine tote Zuordnung mitschleppen.
    assert bekannt == gefunden


# ── Auflösung ────────────────────────────────────────────────────────────────

def test_aufloesung_ist_case_insensitiv():
    index = sd.build_group_index([{"id": "gid-it", "name": "  iT  "}])
    mapping = sd.build_placeholder_mapping(index)
    assert mapping["HIER_GRUPPEN_ID_IT_EINSETZEN"] == "gid-it"


def test_mehrdeutige_gruppennamen_sind_ein_fehler():
    with pytest.raises(sd.SeedError, match="Mehrdeutige"):
        sd.build_group_index([{"id": "a", "name": "IT"}, {"id": "b", "name": "it"}])


def test_kein_text_replace_in_prosa_feldern():
    """Ein Platzhalter, der in einem Hilfetext ERWÄHNT wird, bleibt Text."""
    roh = {"help": "Trage hier HIER_GRUPPEN_ID_IT_EINSETZEN ein",
           "group": "HIER_GRUPPEN_ID_IT_EINSETZEN"}
    out = sd.replace_placeholders(roh, {"HIER_GRUPPEN_ID_IT_EINSETZEN": "gid-it"})
    assert out["group"] == "gid-it"
    assert out["help"] == "Trage hier HIER_GRUPPEN_ID_IT_EINSETZEN ein"


# ── Fail-closed ──────────────────────────────────────────────────────────────

#: Ein Platzhalter, den PLACEHOLDER_GROUP_NAMES nicht kennt – genau der Fall,
#: der beim Ergänzen eines Seeds ohne Pflege der Konstante entsteht.
UNBEKANNT = "HIER_GRUPPEN_ID_UNBEKANNT_EINSETZEN"


def test_unaufgeloester_platzhalter_in_zustaendigkeit_bricht_ab(umgebung, monkeypatch, tmp_path):
    _, store = umgebung
    defn = _minimal()
    defn["phases"][1]["responsibility"]["group"] = UNBEKANNT
    _nur(monkeypatch, tmp_path, defn)

    report = sd.seed_processes(commit=True, with_permissions=False)
    assert report.fehler == 1 and store.created == []
    (o,) = report.outcomes
    assert "unaufgelöster Platzhalter" in o.meldung
    assert "responsibility.group" in o.meldung


def test_unaufgeloester_platzhalter_in_visibletogroups_bricht_ab(umgebung, monkeypatch, tmp_path):
    """Ein Platzhalter dort macht ein vertrauliches Feld für NIEMANDEN sichtbar."""
    _, store = umgebung
    defn = _minimal()
    defn["fields"][0]["visibility"] = {"confidential": True, "visibleToGroups": [UNBEKANNT]}
    _nur(monkeypatch, tmp_path, defn)

    report = sd.seed_processes(commit=True, with_permissions=False)
    assert report.fehler == 1 and store.created == []
    assert "visibleToGroups" in report.outcomes[0].meldung
    assert "unaufgelöster Platzhalter" in report.outcomes[0].meldung


def test_fehlgeschlagenes_gruppen_anlegen_bricht_ab(umgebung, monkeypatch, tmp_path):
    """Wenn eine Pflichtgruppe trotz --commit nicht entsteht, wird nicht geseedet."""
    groups, store = umgebung
    _nur(monkeypatch, tmp_path, _minimal())
    groups.groups = [g for g in groups.groups if g["name"].lower() != "it"]
    monkeypatch.setattr(groups, "ensure_required_groups", lambda *a, **k: [])

    report = sd.seed_processes(commit=True, with_permissions=False)
    assert report.fehler == 1 and store.created == []
    assert "unaufgelöster Platzhalter" in report.outcomes[0].meldung


def test_unbekannte_gruppen_id_bricht_ab(umgebung, monkeypatch, tmp_path):
    _, store = umgebung
    defn = _minimal()
    defn["phases"][1]["responsibility"]["group"] = "gibt-es-nicht"
    _nur(monkeypatch, tmp_path, defn)

    report = sd.seed_processes(commit=True, with_permissions=False)
    assert report.fehler == 1 and store.created == []
    assert "existiert nicht" in report.outcomes[0].meldung


def test_ungueltige_definition_wird_nicht_eingespielt(umgebung, monkeypatch, tmp_path):
    _, store = umgebung
    defn = _minimal()
    defn["phases"][0]["fields"][0]["ref"] = "gibt.es.nicht"
    _nur(monkeypatch, tmp_path, defn)

    report = sd.seed_processes(commit=True, with_permissions=False)
    assert report.fehler == 1 and store.created == []
    assert "validiert nicht" in report.outcomes[0].meldung


# ── Idempotenz und Trockenlauf ───────────────────────────────────────────────

def test_vorhandener_key_wird_uebersprungen_auch_als_entwurf(umgebung, monkeypatch, tmp_path):
    _, store = umgebung
    store.versionen["test-prozess"] = [{"version": 1, "status": "draft"}]
    _nur(monkeypatch, tmp_path, _minimal())

    report = sd.seed_processes(commit=True, with_permissions=False)
    assert report.uebersprungen == 1 and report.fehler == 0
    assert store.created == [] and store.published == []
    assert "existiert bereits" in report.outcomes[0].meldung


def test_trockenlauf_schreibt_nichts(umgebung):
    groups, store = umgebung
    report = sd.seed_processes(commit=False, with_permissions=False)
    assert store.created == [] and store.published == []
    assert groups.ensure_aufrufe == []
    assert report.erstellt == 10     # inklusive Basis-Ticket, ohne jede Konfiguration
    assert report.uebersprungen == 0
    assert all(o.aktion == "would_create" for o in report.outcomes)


def test_trockenlauf_meldet_fehlende_gruppen_ohne_sie_anzulegen(monkeypatch):
    groups = FakeGroups([])
    store = FakeStore()
    monkeypatch.setattr(sd, "groupsdb", groups)
    monkeypatch.setattr(sd, "defstore", store)

    report = sd.seed_processes(commit=False, with_permissions=False)
    assert sorted(report.fehlende_gruppen) == sorted(sd.required_group_names())
    assert groups.groups == [] and groups.ensure_aufrufe == []
    assert report.fehler == 0        # Struktur ist prüfbar, nur die IDs sind noch offen


# ── Commit ───────────────────────────────────────────────────────────────────

def test_commit_legt_alle_zehn_an_und_veroeffentlicht(umgebung):
    _, store = umgebung
    report = sd.seed_processes(commit=True, with_permissions=False)

    assert report.fehler == 0
    assert len(store.created) == 10 and len(store.published) == 10
    assert {k for k, *_ in store.created} == {
        "basis-ticket", "einstellung", "hardware", "hotelbuchung",
        "marketing-stellenanzeige", "niederlassung-anmelden",
        "niederlassung-schliessen", "niederlassung-umzug",
        "zugang-beantragen", "zugang-sperren"}
    # Gespeichert wird die AUFGELÖSTE Definition, kein Platzhalter.
    for _, _, definition_json, *_ in store.created:
        assert "HIER_GRUPPEN_ID" not in definition_json


def test_basis_ticket_braucht_keine_konfiguration_mehr(umgebung):
    """Früher übersprungen (--basis-group / SEED_BASIS_TICKET_GROUP), heute nicht:
    die zuständige Fachabteilung steht in einem FELD des Auftrags, nicht in der
    Definition – es gibt also keinen Platzhalter mehr aufzulösen."""
    _, store = umgebung
    report = sd.seed_processes(commit=True, with_permissions=False, only={"basis-ticket"})

    (o,) = report.outcomes
    assert o.aktion == "created" and report.fehler == 0
    defn = json.loads(store.created[0][2])
    assert "HIER_" not in store.created[0][2]
    # Jede:r durfte Basis-Tickets anlegen – das muss der Seed mitbringen.
    assert defn["createPermissions"]["everyone"] is True
    bearbeitung = defn["phases"][1]
    assert bearbeitung["responsibility"]["kind"] == "group_from_field"
    assert bearbeitung["responsibility"]["fromField"] == "ticket.fachabteilung"


def test_commit_legt_fehlende_pflichtgruppen_versteckt_an(monkeypatch):
    groups = FakeGroups([])
    store = FakeStore()
    monkeypatch.setattr(sd, "groupsdb", groups)
    monkeypatch.setattr(sd, "defstore", store)

    report = sd.seed_processes(commit=True, with_permissions=False)
    assert sorted(report.angelegte_gruppen) == sorted(sd.required_group_names())
    (_, hidden), = groups.ensure_aufrufe
    assert hidden == sd.AUTO_ASSIGNED_GROUP_NAMES
    assert report.fehler == 0 and len(store.created) == 10


def test_nur_ein_prozess_mit_only(umgebung):
    _, store = umgebung
    report = sd.seed_processes(commit=True, with_permissions=False, only={"hardware"})
    assert [o.key for o in report.outcomes] == ["hardware"]
    assert [k for k, *_ in store.created] == ["hardware"]


def test_draft_modus_veroeffentlicht_nicht(umgebung):
    _, store = umgebung
    sd.seed_processes(commit=True, with_permissions=False, publish=False, only={"hardware"})
    assert len(store.created) == 1 and store.published == []


# ── Erstellrechte ────────────────────────────────────────────────────────────

def test_erstellrechte_werden_uebernommen(umgebung, monkeypatch):
    groups, store = umgebung
    it_gid = next(g["id"] for g in groups.groups if g["name"] == "it")
    ad_guid = "8f1e2c34-5b6a-47d8-9e0f-112233445566"
    monkeypatch.setattr(sd.backfill, "load_legacy_permissions",
                        lambda: ({"hardware": ["u-1"]}, {"hardware": [it_gid, ad_guid]}))

    report = sd.seed_processes(commit=True, only={"hardware"})
    (o,) = report.outcomes
    assert o.aktion == "created"
    assert o.create_permissions == {"everyone": False, "groups": [it_gid], "users": ["u-1"]}
    # AD-Gruppe wird gemeldet statt still als totes Recht mitgeschrieben.
    assert o.wirkungslose_gruppen == [ad_guid]
    gespeichert = json.loads(store.created[0][2])
    assert gespeichert["createPermissions"]["users"] == ["u-1"]
    assert ad_guid not in json.dumps(gespeichert)
