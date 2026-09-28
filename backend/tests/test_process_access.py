"""Zugriff auf Prozess-Aufträge + Abteilungs-Stand (reine Logik, keine DB)."""

from backend.schemas.process_definition import ProcessDefinition
from backend.services import process_access as acc
from backend.services import process_runtime as pr

DEFN = ProcessDefinition.model_validate({
    "key": "demo", "name": "Demo",
    "fields": [{"key": "a", "widget": "text"},
               {"key": "fuhrpark.car", "widget": "select",
                "options": [{"value": "Ja"}, {"value": "Nein"}]}],
    "phases": [
        {"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
         "grantsFullView": True, "fields": [{"ref": "a", "required": True}]},
        {"key": "review", "kind": "review",
         "responsibility": {"kind": "departments", "rule": [
             {"group": "g_it", "required": True},
             {"group": "g_fp", "required": True, "when": {"==": ["fuhrpark.car", "Ja"]}},
             {"group": "g_opt", "required": False}]},
         "fields": [{"ref": "a", "mode": "readonly"}]},
        {"key": "final", "kind": "task", "responsibility": {"kind": "group", "group": "g_lead"},
         "fields": [{"ref": "a", "mode": "readonly"}]},
    ],
})

OWNER = {"id": "u_owner", "permissions": []}
IT = {"id": "u_it", "permissions": []}
FREMD = {"id": "u_x", "permissions": []}
AUFSICHT = {"id": "u_view", "permissions": ["view"]}
ADMIN = {"id": "u_admin", "permissions": ["view", "manage", "admin"]}


def ticket(values=None, phase_index=0):
    rt = pr.initial_runtime(DEFN, "t0", values or {})
    for _ in range(phase_index):
        rt, _st = pr.advance(DEFN, rt, "t1", values or {})
    return {"id": 1, "owner_id": "u_owner", "status": "in_progress",
            "values": values or {}, "runtime": rt}


# ── Sichtbarkeit des Auftrags ─────────────────────────────────────────────────

def test_owner_und_aufsicht_sehen_immer():
    t = ticket()
    assert acc.may_view(DEFN, t, OWNER, []) is True
    assert acc.may_view(DEFN, t, AUFSICHT, []) is True
    assert acc.may_view(DEFN, t, ADMIN, []) is True


def test_unbeteiligte_sehen_nicht():
    assert acc.may_view(DEFN, ticket(), FREMD, []) is False


def test_beobachter_sieht():
    assert acc.may_view(DEFN, ticket(), FREMD, [], watcher_ids=["u_x"]) is True


def test_zustaendige_abteilung_sieht_in_ihrer_phase():
    t = ticket(phase_index=1)                      # review-Phase
    assert acc.may_view(DEFN, t, IT, ["g_it"]) is True
    assert acc.may_view(DEFN, t, IT, ["g_andere"]) is False


def test_zustaendigkeit_endet_mit_der_phase():
    """In der Folgephase ist die IT nicht mehr zuständig (kein Dauer-Zugriff)."""
    t = ticket(phase_index=2)                      # final-Phase (g_lead)
    assert acc.may_view(DEFN, t, IT, ["g_it"]) is False
    assert acc.may_view(DEFN, t, IT, ["g_lead"]) is True


# ── Bearbeiten ────────────────────────────────────────────────────────────────

def test_aufsicht_darf_lesen_aber_nicht_bearbeiten():
    t = ticket()
    assert acc.may_view(DEFN, t, AUFSICHT, []) is True
    assert acc.may_edit(DEFN, t, AUFSICHT, []) is False


def test_owner_darf_in_seiner_phase_bearbeiten():
    assert acc.may_edit(DEFN, ticket(), OWNER, []) is True
    # in der review-Phase nicht mehr
    assert acc.may_edit(DEFN, ticket(phase_index=1), OWNER, []) is False


def test_admin_darf_immer_bearbeiten():
    assert acc.may_edit(DEFN, ticket(phase_index=1), ADMIN, []) is True


# ── Abteilungen einzeln ───────────────────────────────────────────────────────

def test_bedingte_abteilung_wird_beim_eintritt_ausgewertet():
    ohne = ticket({"fuhrpark.car": "Nein"}, phase_index=1)
    assert {d["group"] for d in pr.current_departments(ohne["runtime"])} == {"g_it", "g_opt"}
    mit = ticket({"fuhrpark.car": "Ja"}, phase_index=1)
    assert {d["group"] for d in pr.current_departments(mit["runtime"])} == {"g_it", "g_fp", "g_opt"}


def test_nur_pflichtabteilungen_blockieren():
    t = ticket({"fuhrpark.car": "Nein"}, phase_index=1)
    rt = t["runtime"]
    assert pr.departments_complete(rt) is False          # g_it offen
    pr.set_department_status(rt, "g_it", "done", by="u_it", by_name="IT", at="t2")
    # g_opt ist optional → blockiert nicht
    assert pr.departments_complete(rt) is True


def test_skipped_gilt_als_erledigt():
    t = ticket({"fuhrpark.car": "Nein"}, phase_index=1)
    rt = t["runtime"]
    pr.set_department_status(rt, "g_it", "skipped", by="u_it", by_name="IT", at="t2")
    assert pr.departments_complete(rt) is True


def test_unbeteiligte_abteilung_kann_nicht_gesetzt_werden():
    t = ticket({"fuhrpark.car": "Nein"}, phase_index=1)
    ok = pr.set_department_status(t["runtime"], "g_fp", "done",
                                 by="u", by_name="X", at="t2")
    assert ok is False                                  # g_fp ist hier nicht beteiligt


def test_nur_mitglieder_duerfen_ihre_abteilung_abschliessen():
    t = ticket({"fuhrpark.car": "Ja"}, phase_index=1)
    assert acc.may_complete_department(DEFN, t, IT, ["g_it"], "g_it") is True
    # Mitglied der IT darf NICHT für den Fuhrpark quittieren
    assert acc.may_complete_department(DEFN, t, IT, ["g_it"], "g_fp") is False
    # Admin darf
    assert acc.may_complete_department(DEFN, t, ADMIN, [], "g_fp") is True
    # Abteilung, die gar nicht beteiligt ist
    assert acc.may_complete_department(DEFN, t, ADMIN, [], "g_unbeteiligt") is False


def test_phasenwechsel_setzt_abteilungen_neu():
    """Beim Eintritt in eine neue Phase gilt ihr eigener Abteilungs-Stand."""
    t = ticket({"fuhrpark.car": "Ja"}, phase_index=1)
    rt = t["runtime"]
    pr.set_department_status(rt, "g_it", "done", by="u", by_name="X", at="t2")
    rt, _ = pr.advance(DEFN, rt, "t3", t["values"])
    # final-Phase hat keine Abteilungen → nichts blockiert
    assert pr.current_departments(rt) == []
    assert pr.departments_complete(rt) is True


# ── Archiv-Beteiligung (persönliches Archiv, alle Status) ─────────────────────

FP = {"id": "u_fp", "permissions": []}
LEAD = {"id": "u_lead", "permissions": []}


def _arch(phase_index=1, values=None, status="in_progress", rejected=False):
    """Auftrag mit ECHTER Runtime, die bis `phase_index` fortgeschritten ist."""
    t = ticket(values=values, phase_index=phase_index)
    t["id"] = 9
    t["status"] = status
    if rejected:
        t["runtime"]["rejected"] = True
    return t


def test_responsible_group_refs_trennt_bedingt():
    uncond, cond = acc.responsible_group_refs(DEFN)
    assert uncond == {"g_it", "g_opt", "g_lead"}
    assert [g for g, _w in cond] == ["g_fp"]


def test_archive_abteilung_erst_ab_erreichter_phase():
    # g_it ist erst in der review-Phase (Fachabteilung, phase 1) zuständig – vorher
    # (start, phase 0) taucht der Auftrag im persönlichen Archiv NICHT auf.
    assert acc.archive_involved(DEFN, _arch(phase_index=0), IT, ["g_it"]) is False
    assert acc.archive_involved(DEFN, _arch(phase_index=1), IT, ["g_it"]) is True


def test_archive_gruppen_phase_erst_ab_erreicht():
    # g_lead ist erst in der final-Phase (phase 2) zuständig.
    assert acc.archive_involved(DEFN, _arch(phase_index=1), LEAD, ["g_lead"]) is False
    assert acc.archive_involved(DEFN, _arch(phase_index=2), LEAD, ["g_lead"]) is True


def test_archive_bedingte_abteilung_phase_und_bedingung():
    # g_fp nur bei Dienstwagen=Ja – UND erst, wenn die review-Phase erreicht ist.
    assert acc.archive_involved(DEFN, _arch(1, {"fuhrpark.car": "Ja"}), FP, ["g_fp"]) is True
    assert acc.archive_involved(DEFN, _arch(1, {"fuhrpark.car": "Nein"}), FP, ["g_fp"]) is False
    # Bedingung erfüllt, aber Phase noch nicht erreicht → nein.
    assert acc.archive_involved(DEFN, _arch(0, {"fuhrpark.car": "Ja"}), FP, ["g_fp"]) is False


def test_archive_abgelehnt_vor_erreichen_bleibt_unsichtbar():
    # Schon in der start-Phase abgelehnt – die review-Fachabteilungen waren nie dran.
    weg = _arch(0, {"fuhrpark.car": "Ja"}, status="rejected", rejected=True)
    assert acc.archive_involved(DEFN, weg, FP, ["g_fp"]) is False
    assert acc.archive_involved(DEFN, weg, IT, ["g_it"]) is False


def test_archive_owner_und_beobachter():
    assert acc.archive_involved(DEFN, _arch(0), OWNER, []) is True
    assert acc.archive_involved(DEFN, _arch(0), FREMD, [], is_watcher=True) is True


def test_archive_aufsicht_allein_zaehlt_nicht():
    # Aufsicht/Admin ist Sache der Übersicht „Alle Aufträge", nicht des Archivs.
    assert acc.archive_involved(DEFN, _arch(1), AUFSICHT, []) is False
    assert acc.archive_involved(DEFN, _arch(1), ADMIN, []) is False


def test_archive_echte_unbeteiligte():
    assert acc.archive_involved(DEFN, _arch(1, {"fuhrpark.car": "Ja"}), FREMD, ["g_andere"]) is False
