"""In-App-Benachrichtigungen: wer bekommt bei welchem Ereignis was (rein, ohne DB).

Ergänzung zur Mail – der Mailversand ist davon unberührt. In der App bekommen auch
Ersteller:in und Beobachter:innen Fortschritts-Meldungen; die neu zuständige Stelle
eine „Neue Aufgabe".
"""
from backend.schemas.process_definition import ProcessDefinition
from backend.services import process_events as ev
from backend.services import process_notifications as pn
from backend.services import process_runtime as pr

DEFN = ProcessDefinition.model_validate({
    "key": "demo", "name": "Demo",
    "fields": [{"key": "a", "widget": "text"}, {"key": "wer", "widget": "user"}],
    "phases": [
        {"key": "start", "kind": "start", "label": "Antrag", "responsibility": {"kind": "owner"},
         "fields": [{"ref": "a"}, {"ref": "wer"}]},
        {"key": "frei", "kind": "task", "label": "Freigabe",
         "responsibility": {"kind": "group", "group": "g_frei"},
         "fields": [{"ref": "a", "mode": "readonly"}]},
        {"key": "bearb", "kind": "task", "label": "Bearbeitung",
         "responsibility": {"kind": "assignable", "fromField": "wer"},
         "fields": [{"ref": "a", "mode": "editable"}]},
        {"key": "durch", "kind": "review", "label": "Durchführung",
         "responsibility": {"kind": "departments", "rule": [{"group": "g_it"}, {"group": "g_fp"}]},
         "fields": [{"ref": "a", "mode": "readonly"}]},
    ],
})

GROUPS = {
    "g_frei": {"id": "g_frei", "name": "Freigabe", "members": ["chefin@x", "owner@x"]},
    "g_it": {"id": "g_it", "name": "IT", "members": ["it1@x", "it2@x"]},
    "g_fp": {"id": "g_fp", "name": "Fuhrpark", "members": ["fp1@x"]},
}


def ticket(phase_index: int, values=None):
    values = {"wer": "bearbeiter@x", "a": "GEHEIM-WERT", **(values or {})}
    rt = pr.initial_runtime(DEFN, "t0", values)
    status = "in_progress"
    for _ in range(phase_index):
        rt, status = pr.advance(DEFN, rt, "t1", values)
    return {"id": 42, "title": "Onboarding Max", "owner_id": "owner@x", "status": status,
            "process_key": "demo", "process_version": 1, "values": values, "runtime": rt}


def plan(action, row, *, actor="actor@x", details=None, body=None, watchers=("beob@x",),
         internal=False, auto_pending=lambda phase: False):
    return {i["user_id"]: i for i in pn.plan(
        action, row, defn=DEFN, details=details, body=body, actor_id=actor,
        actor_name="Akteur", internal=internal, watchers=set(watchers),
        groups_by_id=GROUPS, auto_pending=auto_pending)}


def test_phasenwechsel_neue_aufgabe_fuer_gruppe_fortschritt_fuer_beteiligte():
    out = plan(ev.ADVANCED, ticket(1), details={"from_phase": "start", "to_phase": "frei"})
    # Gruppenmitglieder: „Neue Aufgabe"; owner ist AUCH Mitglied → Aufgabe gewinnt.
    assert out["chefin@x"]["kind"] == "task" and out["owner@x"]["kind"] == "task"
    assert "Freigabe" in out["chefin@x"]["body"] and out["chefin@x"]["link"].endswith("?ansicht=bearbeiten")
    assert out["beob@x"]["kind"] == "progress" and "Weiter in Phase „Freigabe“" in out["beob@x"]["body"]
    assert out["beob@x"]["link"] == "/prozess-auftraege/42"


def test_zuweisbare_person_bekommt_die_aufgabe():
    out = plan(ev.ADVANCED, ticket(2), details={"from_phase": "frei", "to_phase": "bearb"})
    assert out["bearbeiter@x"]["kind"] == "task"
    assert out["owner@x"]["kind"] == "progress"


def test_fachabteilungen_nur_offene_mitglieder():
    row = ticket(3)
    pr.set_department_status(row["runtime"], "g_fp", "done", by="x", by_name="X", at="t2")
    out = plan(ev.ADVANCED, row, details={"from_phase": "bearb", "to_phase": "durch"})
    assert out["it1@x"]["kind"] == "task" and out["it2@x"]["kind"] == "task"
    assert "fp1@x" not in out                       # Fuhrpark schon erledigt
    assert "(IT)" in out["it1@x"]["body"]


def test_abschluss_nur_fortschritt():
    row = ticket(4)
    out = plan(ev.ADVANCED, row, details={"from_phase": "durch", "to_phase": None, "status": "archived"})
    assert set(out) == {"owner@x", "beob@x"}
    assert all(i["kind"] == "progress" and i["body"] == "Abgeschlossen" for i in out.values())


def test_durchgangsphase_erzeugt_keine_aufgabe():
    out = plan(ev.ADVANCED, ticket(1), details={"from_phase": "start", "to_phase": "frei"},
               auto_pending=lambda phase: phase.key == "frei")
    assert "chefin@x" not in out                   # Phase schaltet sofort weiter
    assert out["owner@x"]["kind"] == "progress"


def test_eigene_aktion_meldet_nichts_an_sich_selbst():
    out = plan(ev.ADVANCED, ticket(1), actor="chefin@x",
               details={"from_phase": "start", "to_phase": "frei"})
    assert "chefin@x" not in out


def test_intern_und_irrelevante_aktionen_erzeugen_nichts():
    assert plan(ev.ADVANCED, ticket(1), internal=True, details={"to_phase": "frei"}) == {}
    # „Angaben geändert" verriete Änderungen an evtl. unsichtbaren Feldern.
    assert plan(ev.UPDATED, ticket(1), details={"fields": ["a"]}) == {}
    assert plan(ev.CREATED, ticket(0)) == {}


def test_ablehnung_und_fachabteilungs_ereignisse():
    assert plan(ev.REJECTED, ticket(1))["owner@x"]["body"] == "Abgelehnt"
    out = plan(ev.DEPARTMENT_DONE, ticket(3), details={"group": "g_it"})
    assert out["beob@x"]["body"] == "IT hat ihren Teil erledigt" and set(out) == {"owner@x", "beob@x"}
    assert plan(ev.DEPARTMENT_REJECTED, ticket(3), details={"group": "g_fp"})["owner@x"]["body"] \
        == "Abgelehnt durch Fuhrpark"


def test_zur_nachbesserung_zurueck_aufgabe_an_die_zielstelle():
    row = ticket(0)    # zurück in der Start-Phase (zuständig: owner)
    out = plan(ev.APPROVAL_SENT_BACK, row, details={"to_phase": "start"})
    assert out["owner@x"]["kind"] == "task" and "Nachbesserung" in out["owner@x"]["body"]
    assert out["beob@x"]["kind"] == "progress"


def test_nachtrag_an_beteiligte_und_mitglieder_der_fachabteilungen():
    row = ticket(4)    # abgeschlossen: alle Phasen durchlaufen
    out = plan(ev.ADDENDUM, row, body="Bitte  noch\n die Adresse ändern " + "x" * 200)
    assert {"owner@x", "beob@x", "chefin@x", "it1@x", "fp1@x"} <= set(out)
    assert all(i["kind"] == "addendum" for i in out.values())
    assert out["owner@x"]["body"].startswith("Nachtrag: Bitte noch die Adresse ändern")
    assert out["owner@x"]["body"].endswith("…") and len(out["owner@x"]["body"]) < 160


def test_beobachter_eingetragen_nur_die_person_selbst():
    out = plan(ev.WATCHER_ADDED, ticket(1), details={"watcher": "neu@x"})
    assert set(out) == {"neu@x"} and out["neu@x"]["kind"] == "watch"
    assert "Akteur hat dich" in out["neu@x"]["body"]
    assert plan(ev.WATCHER_ADDED, ticket(1), actor="neu@x", details={"watcher": "neu@x"}) == {}


def test_texte_enthalten_keine_feldwerte():
    rows = [plan(ev.ADVANCED, ticket(i), details={"from_phase": "x", "to_phase": DEFN.phases[i].key})
            for i in range(1, 4)]
    for out in rows:
        for item in out.values():
            assert "GEHEIM" not in (item["title"] + item["body"])
