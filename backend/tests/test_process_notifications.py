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
    # Ersteller:in lehnt selbst ab: keine Meldung über die eigene Aktion
    # (die Mail geht trotzdem raus – die Glocke zeigt, was ANDERE tun).
    out = plan(ev.REJECTED, ticket(1), actor="owner@x")
    assert "owner@x" not in out and out["beob@x"]["body"] == "Abgelehnt"
    assert plan(ev.DEPARTMENT_DONE, ticket(3), actor="owner@x", details={"group": "g_it"}).keys() \
        == {"beob@x"}
    assert "owner@x" not in plan(ev.DEPARTMENT_REJECTED, ticket(3), actor="owner@x",
                                 details={"group": "g_fp"})
    # Abschluss: kein task-Zweig – auch nicht für eine zuständige Ersteller:in.
    assert "owner@x" not in plan(ev.ADVANCED, ticket(4), actor="owner@x",
                                 details={"from_phase": "durch", "to_phase": None, "status": "archived"})
    # Eigener Nachtrag – auch als Mitglied einer beteiligten Fachabteilung.
    assert "it1@x" not in plan(ev.ADDENDUM, ticket(4), actor="it1@x", body="x")


def test_neue_aufgabe_auch_an_die_ausloesende_person_wenn_zustaendig():
    """Wer den Wechsel auslöst und selbst für die neue Phase zuständig ist, hat
    trotzdem eine Aufgabe – wie die Phasen-Mail. Fortschritt bekommt sie nicht."""
    out = plan(ev.ADVANCED, ticket(1), actor="owner@x",      # owner ist auch in g_frei
               details={"from_phase": "start", "to_phase": "frei"})
    assert out["owner@x"]["kind"] == "task" and out["chefin@x"]["kind"] == "task"
    sent_back = plan(ev.APPROVAL_SENT_BACK, ticket(0), actor="owner@x", details={"to_phase": "start"})
    assert sent_back["owner@x"]["kind"] == "task"
    # Nicht zuständig → nichts über die eigene Aktion.
    assert "beob@x" not in plan(ev.ADVANCED, ticket(1), actor="beob@x",
                                details={"from_phase": "start", "to_phase": "frei"})
    # Durchgangsphase bleibt auch für die auslösende Person ohne Aufgabe.
    assert "owner@x" not in plan(ev.ADVANCED, ticket(1), actor="owner@x",
                                 details={"from_phase": "start", "to_phase": "frei"},
                                 auto_pending=lambda phase: phase.key == "frei")


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


# ── Nachbesserungen aus der Prüfung ───────────────────────────────────────────

def test_nachtrag_nach_zwangsabschluss_nur_erreichte_abteilungen():
    """Zwangsabschluss in der Freigabe-Phase: spätere Phasen nie erreicht – deren
    Mitglieder dürften den Auftrag nicht öffnen und bekommen keine Vorschau."""
    row = ticket(1)                                   # in „Freigabe" (g_frei)
    row["runtime"] = pr.force_archive(row["runtime"])
    row["status"] = "archived"
    out = plan(ev.ADDENDUM, row, body="Bitte ändern")
    assert "chefin@x" in out                          # Freigabe erreicht
    assert not ({"it1@x", "it2@x", "fp1@x", "bearbeiter@x"} & set(out))


def test_aufgabe_bei_zurueckgeben_wiederaufnahme_und_manueller_phase_trotz_auto_advance():
    """Dort läuft on_enter-auto_advance NICHT – die Phase wartet wirklich."""
    immer = lambda phase: True                        # noqa: E731
    sent_back = plan(ev.APPROVAL_SENT_BACK, ticket(0), details={"to_phase": "start"}, auto_pending=immer)
    assert sent_back["owner@x"]["kind"] == "task"
    reopened = plan(ev.REOPENED, ticket(1), auto_pending=immer)
    assert reopened["chefin@x"]["kind"] == "task"
    forced = plan(ev.ADVANCED, ticket(1), auto_pending=immer,
                  details={"from_phase": "start", "to_phase": "frei", "forced": True})
    assert forced["chefin@x"]["kind"] == "task"
    # Normaler Phasenwechsel in eine Durchgangsphase: weiterhin keine Aufgabe.
    normal = plan(ev.ADVANCED, ticket(1), auto_pending=immer,
                  details={"from_phase": "start", "to_phase": "frei"})
    assert "chefin@x" not in normal


def test_system_eintrag_schliesst_die_ausloesende_person_aus(monkeypatch):
    """Verketteter automatischer Phasenwechsel: Verlauf sagt „System", die Person,
    die ihn ausgelöst hat, bekommt trotzdem keine Meldung über die eigene Aktion."""
    seen = {}
    monkeypatch.setattr(ev.store, "add_event", lambda **kw: {"id": 1, **kw})
    monkeypatch.setattr(ev, "record_audit", lambda **kw: None)
    monkeypatch.setattr(pn, "fanout", lambda row, action, **kw: seen.update(kw))
    ev.system(ticket(1), ev.ADVANCED, details={"to_phase": "frei", "auto": True},
              notify_exclude="owner@x")
    assert seen["actor_id"] == "owner@x"


def test_systemkette_ausloesende_person_bekommt_aufgabe_wenn_zustaendig():
    """Verketteter Wechsel endet in einer Phase der auslösenden Person (notify_exclude
    kommt in plan als actor_id an): Aufgabe ja, Fortschritt nein."""
    out = plan(ev.ADVANCED, ticket(2), actor="bearbeiter@x",
               details={"from_phase": "frei", "to_phase": "bearb", "auto": True},
               watchers=("beob@x", "bearbeiter@x"))
    assert out["bearbeiter@x"]["kind"] == "task"
