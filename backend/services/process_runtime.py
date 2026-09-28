"""
Phasen-Runtime für definitions-getriebene Tickets (§7/§11 Stufe 2).

Der pro Ticket gespeicherte `runtime`-Zustand ist eine reine Ablauf-Struktur –
er enthält NIE Feldwerte (§5.6), nur Phasen-Status, Zeitstempel und Zähler:

    {
      "current_index": int,
      "epoch": int,                 # +1 bei Reopen (Ledger-Schlüssel)
      "rejected": bool,
      "sla_paused_ms": int,
      "phases": [ {
          "key", "status": open|done|pending, "entered_at": iso|None,
          # Nur bei responsibility.kind == 'departments': Stand JE Abteilung.
          # Erst wenn alle PFLICHT-Abteilungen done/skipped sind, darf die Phase
          # abgeschlossen werden – sonst könnte IT für den Fuhrpark quittieren.
          "departments": [ {"group", "required", "status": open|done|skipped,
                            "by", "by_name", "at", "note"} ],
          # Nur bei kind='approval': die gefallene Entscheidung (siehe
          # set_phase_decision). Fehlt, solange nicht entschieden wurde.
          "decision": {"act", "by", "by_name", "at", "reason", "reason_in_field"}
      } ]
    }

Reine Logik (kein DB-Zugriff) → unit-testbar. Zeit wird als UTC-ISO hereingereicht.
"""
from typing import Optional

from backend.schemas.process_definition import (
    ProcessDefinition, PhaseDef, PhaseKind, ResponsibilityKind,
)
from backend.services.condition_dsl import evaluate


def seed_departments(phase: PhaseDef, values: dict) -> list:
    """Abteilungs-Stand für eine Fachabteilungs-Phase aufbauen (beim Eintritt).

    Welche Abteilungen beteiligt sind, entscheidet die Bedingung je Regel – daher
    wird das erst beim EINTRITT ausgewertet, wenn die Werte vorliegen.
    """
    if phase.responsibility.kind != ResponsibilityKind.departments:
        return []
    out = []
    for dr in phase.responsibility.rule:
        if dr.when is not None and not evaluate(dr.when, values):
            continue
        out.append({"group": dr.group, "required": dr.required, "status": "open",
                    "by": None, "by_name": None, "at": None, "note": None})
    return out


def initial_runtime(defn: ProcessDefinition, now_iso: str,
                    values: Optional[dict] = None) -> dict:
    values = values or {}
    phases = []
    for i, p in enumerate(defn.phases):
        phases.append({
            "key": p.key,
            "status": "open" if i == 0 else "pending",
            "entered_at": now_iso if i == 0 else None,
            # Nur die aktive Phase bekommt ihren Abteilungs-Stand; die späteren
            # erst beim Eintritt (die Bedingungen können sich bis dahin ändern).
            "departments": seed_departments(p, values) if i == 0 else [],
        })
    return {
        "current_index": 0,
        "epoch": 0,
        "rejected": False,
        "sla_paused_ms": 0,
        "phases": phases,
    }


def current_phase(defn: ProcessDefinition, runtime: dict) -> Optional[PhaseDef]:
    idx = runtime.get("current_index", 0)
    if 0 <= idx < len(defn.phases):
        return defn.phases[idx]
    return None


def is_terminal(runtime: dict) -> bool:
    return bool(runtime.get("rejected")) or runtime.get("current_index", 0) >= len(runtime.get("phases", []))


def enter_status_for(phase: PhaseDef) -> str:
    if phase.enterStatus:
        return phase.enterStatus
    return "in_request" if phase.kind == PhaseKind.review else "in_progress"


def advance(defn: ProcessDefinition, runtime: dict, now_iso: str,
            values: Optional[dict] = None) -> tuple[dict, str]:
    """Aktuelle Phase abschließen, nächste aktivieren. Gibt (runtime, status) zurück;
    hinter der letzten Phase → status 'archived'."""
    idx = runtime["current_index"]
    runtime["phases"][idx]["status"] = "done"
    nxt = idx + 1
    runtime["current_index"] = nxt
    if nxt >= len(defn.phases):
        return runtime, "archived"
    entry = runtime["phases"][nxt]
    entry["status"] = "open"
    entry["entered_at"] = now_iso
    entry["departments"] = seed_departments(defn.phases[nxt], values or {})
    return runtime, enter_status_for(defn.phases[nxt])


# ── Abteilungs-Stand der aktuellen Phase ──────────────────────────────────────

def current_departments(runtime: dict) -> list:
    idx = runtime.get("current_index", 0)
    phases = runtime.get("phases", [])
    if 0 <= idx < len(phases):
        return phases[idx].get("departments") or []
    return []


def department_entry(runtime: dict, group_id: str) -> Optional[dict]:
    for d in current_departments(runtime):
        if d.get("group") == group_id:
            return d
    return None


def set_department_status(runtime: dict, group_id: str, status: str, *,
                          by: Optional[str], by_name: Optional[str],
                          at: str, note: Optional[str] = None) -> bool:
    """Stand einer Abteilung setzen. False, wenn sie an dieser Phase nicht beteiligt ist."""
    entry = department_entry(runtime, group_id)
    if entry is None:
        return False
    entry["status"] = status
    entry["by"] = by
    entry["by_name"] = by_name
    entry["at"] = at
    entry["note"] = note
    return True


def open_required_departments(runtime: dict) -> list:
    """Pflicht-Abteilungen, die noch offen sind (blockieren den Abschluss)."""
    return [d for d in current_departments(runtime)
            if d.get("required", True) and d.get("status") not in ("done", "skipped")]


def departments_complete(runtime: dict) -> bool:
    """Darf die Fachabteilungs-Phase abgeschlossen werden?

    Optionale Abteilungen blockieren nicht; 'skipped' gilt als erledigt.
    Ohne Abteilungen (andere Phasenart) immer True.
    """
    return not open_required_departments(runtime)


# ── Entscheidung einer Freigabe-Phase ─────────────────────────────────────────
#
# Strukturell analog zum Abteilungs-Stand: ein Eintrag AM PHASEN-OBJEKT, keine
# Feldwerte (§5.6). Der Eintrag ist zugleich die Einmaligkeits-Sperre für die
# Entscheidung per Mail-Link: liegt eine Entscheidung vor, wird ein zweiter Klick
# abgewiesen statt erneut ausgeführt.

def phase_decision(runtime: dict, index: int) -> Optional[dict]:
    """Entscheidung dieser Phase – None, solange keine gefallen ist."""
    phases = runtime.get("phases") or []
    if 0 <= index < len(phases):
        return phases[index].get("decision")
    return None


def set_phase_decision(runtime: dict, index: int, *, act: str,
                       by: Optional[str], by_name: Optional[str], at: str,
                       reason: Optional[str] = None,
                       reason_in_field: bool = False) -> dict:
    """Entscheidung festschreiben.

    Wirft ValueError bei unbekanntem Index ODER wenn bereits entschieden wurde –
    die Einmaligkeit ist der eigentliche Zweck des Eintrags, sie darf nicht
    stillschweigend überschrieben werden.

    `reason_in_field=True` heißt: die Begründung steht in einem Feldwert und
    bewusst NICHT hier. Der Runtime geht ungefiltert an jede Person mit
    Leserecht; ein Text, der laut Definition in ein (womöglich vertrauliches)
    Feld gehört, darf hier kein Zweitkanal an der Sichtbarkeit vorbei sein (§5.1).
    """
    phases = runtime.get("phases") or []
    if not (0 <= index < len(phases)):
        raise ValueError(f"Phase {index} gibt es in diesem Auftrag nicht")
    if phases[index].get("decision"):
        raise ValueError("Für diese Phase wurde bereits entschieden")
    phases[index]["decision"] = {
        "act": act, "by": by, "by_name": by_name, "at": at,
        "reason": reason, "reason_in_field": bool(reason_in_field),
    }
    return runtime


def _clear_decisions_from(phases: list, index: int) -> None:
    """Entscheidungen ab `index` verwerfen – diese Phasen werden erneut durchlaufen.

    Ohne das bliebe eine Freigabe-Phase nach Rücksprung/Wiederaufnahme für immer
    „bereits bearbeitet“, und der zweite Durchlauf hätte keinen Entscheidungsweg
    mehr.
    """
    for entry in phases[index:]:
        entry.pop("decision", None)


def reject(runtime: dict) -> dict:
    runtime["rejected"] = True
    return runtime


def force_archive(runtime: dict) -> dict:
    """Auftrag zwangsweise abschließen (Admin-Eingriff).

    Setzt den Zeiger HINTER die letzte Phase – derselbe Endzustand, den `advance`
    nach der letzten Phase erzeugt. Offene Phasen bleiben als „open" stehen und
    lügen damit nicht: sie wurden nie erledigt, der Auftrag wurde abgebrochen.
    Rückholbar bleibt er über `reopen`.
    """
    runtime["current_index"] = len(runtime.get("phases") or [])
    return runtime


def phase_index(defn: ProcessDefinition, phase_key: str) -> Optional[int]:
    for i, p in enumerate(defn.phases):
        if p.key == phase_key:
            return i
    return None


def reopen(defn: ProcessDefinition, runtime: dict, now_iso: str, *,
           phase_key: Optional[str] = None,
           values: Optional[dict] = None) -> tuple[dict, str]:
    """Abgeschlossenen oder abgelehnten Auftrag wieder aufnehmen.

    `phase_key` bestimmt, wo weitergearbeitet wird (Standard: die letzte Phase,
    die schon einmal betreten wurde – bei einem archivierten Auftrag also die
    letzte, bei einem abgelehnten die, in der abgelehnt wurde).

    Der **Epoch wird erhöht**. Das ist nicht kosmetisch: die Timer-Sperre
    (`process_timer_fires`) schlüsselt über `(ticket, phase, epoch, ...)`. Ohne
    Bump würde eine Eskalation, die im ersten Durchlauf schon gefeuert hat, im
    zweiten nie wieder feuern – der wiederaufgenommene Auftrag hätte stumme
    Fristen. Aus demselben Grund wird `entered_at` neu gesetzt: die Frist läuft
    ab der Wiederaufnahme, nicht ab dem ersten Betreten.

    Gibt (runtime, status) zurück. Wirft ValueError bei unbekanntem Phasen-Key.
    """
    phases = runtime.get("phases") or []
    if phase_key is not None:
        idx = phase_index(defn, phase_key)
        if idx is None or idx >= len(phases):
            raise ValueError(f"Unbekannte Phase: {phase_key}")
    else:
        # Letzte Phase, die schon einmal betreten wurde.
        entered = [i for i, p in enumerate(phases) if p.get("entered_at")]
        idx = entered[-1] if entered else 0

    runtime["epoch"] = int(runtime.get("epoch", 0)) + 1
    runtime["rejected"] = False
    runtime["current_index"] = idx
    for i, entry in enumerate(phases):
        if i < idx:
            # Davor liegende Phasen bleiben erledigt (ihre Arbeit ist getan).
            entry["status"] = "done"
        elif i == idx:
            entry["status"] = "open"
            entry["entered_at"] = now_iso
            entry["departments"] = seed_departments(defn.phases[i], values or {})
        else:
            entry["status"] = "pending"
            entry["entered_at"] = None
            entry["departments"] = []
    _clear_decisions_from(phases, idx)
    return runtime, enter_status_for(defn.phases[idx])


def send_back(defn: ProcessDefinition, runtime: dict, now_iso: str,
              phase_key: str, values: Optional[dict] = None) -> tuple[dict, str]:
    """Einen LAUFENDEN Auftrag auf eine frühere Phase zurückgeben (Nachbesserung).

    Der „Nein, aber bitte nachbessern“-Zweig einer Freigabe
    (`approval.onReject = "back_to:<phase>"`). Anders als `reopen`: der Auftrag
    ist nicht fertig, `rejected` bleibt unberührt, und das Ziel muss echt VOR
    der aktuellen Phase liegen (ein Sprung nach vorn würde Arbeit überspringen).

    **Der Epoch wird trotzdem erhöht.** Der Auftrag „war nie fertig“ ist als
    Begründung dagegen zu schwach, denn der Epoch ist im Datenmodell kein
    Abschluss-Merkmal, sondern der Schlüssel für DURCHLÄUFE. Ohne Bump bricht
    zweierlei:

      1. **Fristen.** Die Fire-once-Sperre (`process_timer_fires`) schlüsselt
         über (ticket, phase, epoch, automation, occurrence). Die Zielphase hat
         ihre Timer in diesem Epoch bereits abgearbeitet – im zweiten Durchlauf
         bliebe jede Eskalation stumm. Genau der Fehler, den der Docstring von
         `reopen` beschreibt; er hängt am zweiten Durchlauf, nicht daran, ob
         der Auftrag zwischendurch archiviert war.
      2. **Mail-Links.** Das Freigabe-Token trägt (tid, act, phase, epoch). Die
         Entscheidung der Freigabe-Phase wird beim Rücksprung verworfen (sonst
         gäbe es in Runde 2 keinen Entscheidungsweg) – ohne Epoch-Bump wäre
         damit der Link aus Runde 1 wieder gültig und könnte Runde 2 entscheiden.

    `entered_at` der Zielphase wird neu gesetzt: die Fristen laufen ab der
    Rückgabe, nicht ab dem ersten Betreten.

    Gibt (runtime, status) zurück. Wirft ValueError bei unbekanntem oder nicht
    vorher liegendem Phasen-Key.
    """
    phases = runtime.get("phases") or []
    idx = phase_index(defn, phase_key)
    if idx is None or idx >= len(phases):
        raise ValueError(f"Unbekannte Phase: {phase_key}")
    aktuell = int(runtime.get("current_index", 0))
    if idx >= aktuell:
        raise ValueError(f"„{phase_key}“ liegt nicht vor der aktuellen Phase – "
                         f"ein Rücksprung nach vorn würde Arbeit überspringen")

    runtime["epoch"] = int(runtime.get("epoch", 0)) + 1
    runtime["current_index"] = idx
    for i, entry in enumerate(phases):
        if i < idx:
            # Davor liegende Phasen bleiben erledigt (ihre Arbeit ist getan).
            entry["status"] = "done"
        elif i == idx:
            entry["status"] = "open"
            entry["entered_at"] = now_iso
            entry["departments"] = seed_departments(defn.phases[i], values or {})
        else:
            entry["status"] = "pending"
            entry["entered_at"] = None
            entry["departments"] = []
    _clear_decisions_from(phases, idx)
    return runtime, enter_status_for(defn.phases[idx])


def resolve_responsibility(phase: PhaseDef, values: dict) -> dict:
    """Wer ist für die Phase zuständig? Bedingte Abteilungen via DSL ausgewertet."""
    r = phase.responsibility
    if r.kind == ResponsibilityKind.departments:
        groups = [dr.group for dr in r.rule if (dr.when is None or evaluate(dr.when, values))]
        required = {dr.group: dr.required for dr in r.rule}
        return {"kind": "departments",
                "departments": [{"group": g, "required": required.get(g, True), "status": "open"}
                                for g in groups]}
    if r.kind == ResponsibilityKind.group:
        return {"kind": "group", "group": r.group}
    if r.kind == ResponsibilityKind.user:
        return {"kind": "user", "user": r.user}
    if r.kind == ResponsibilityKind.assignable:
        # Zuständige Person steht in einem Personen-Feld des Auftrags. Ist es
        # (noch) leer, gibt es niemanden – das muss der Aufrufer sehen können.
        picked = values.get(r.fromField or "") or None
        return {"kind": "user", "user": picked,
                "from_field": r.fromField, "assignable": True}
    if r.kind == ResponsibilityKind.group_from_field:
        # Zuständige Fachabteilung steht in einem Gruppen-Feld – die erstellende
        # Person hat sie gewählt. Nach außen ist das eine normale Gruppen-
        # Zuständigkeit, damit Mailversand und Rechte unverändert greifen.
        picked = values.get(r.fromField or "") or None
        return {"kind": "group", "group": picked,
                "from_field": r.fromField, "assignable": True}
    if r.kind == ResponsibilityKind.owner:
        return {"kind": "owner"}
    return {"kind": "unknown"}
