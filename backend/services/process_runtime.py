"""
Phasen-Runtime für definitions-getriebene Tickets (§7/§11 Stufe 2).

Der pro Ticket gespeicherte `runtime`-Zustand ist eine reine Ablauf-Struktur –
er enthält NIE Feldwerte (§5.6), nur Phasen-Status, Zeitstempel und Zähler:

    {
      "current_index": int,
      "epoch": int,                 # +1 bei Reopen (Stufe 5, Ledger-Schlüssel)
      "rejected": bool,
      "sla_paused_ms": int,
      "phases": [ {"key", "status": open|done|pending, "entered_at": iso|None} ]
    }

Reine Logik (kein DB-Zugriff) → unit-testbar. Zeit wird als UTC-ISO hereingereicht.
"""
from typing import Optional

from backend.schemas.process_definition import (
    ProcessDefinition, PhaseDef, PhaseKind, ResponsibilityKind,
)
from backend.services.condition_dsl import evaluate


def initial_runtime(defn: ProcessDefinition, now_iso: str) -> dict:
    phases = []
    for i, p in enumerate(defn.phases):
        phases.append({
            "key": p.key,
            "status": "open" if i == 0 else "pending",
            "entered_at": now_iso if i == 0 else None,
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


def advance(defn: ProcessDefinition, runtime: dict, now_iso: str) -> tuple[dict, str]:
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
    return runtime, enter_status_for(defn.phases[nxt])


def reject(runtime: dict) -> dict:
    runtime["rejected"] = True
    return runtime


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
    if r.kind == ResponsibilityKind.owner:
        return {"kind": "owner"}
    if r.kind == ResponsibilityKind.originator:
        return {"kind": "originator"}
    return {"kind": "unknown"}
