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
                            "by", "by_name", "at", "note"} ]
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


def reject(runtime: dict) -> dict:
    runtime["rejected"] = True
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
    if r.kind == ResponsibilityKind.owner:
        return {"kind": "owner"}
    if r.kind == ResponsibilityKind.originator:
        return {"kind": "originator"}
    return {"kind": "unknown"}
