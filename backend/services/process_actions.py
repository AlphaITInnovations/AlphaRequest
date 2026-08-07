"""
Ausführung von Automation-Actions (§6) – Registry aus Empfänger-Resolvern und
Action-Handlern.

`run_action` löst KEINE Persistenz aus: es versendet ggf. Mail (über einen
injizierbaren Sender) und gibt die gewünschten Zustandsänderungen als dict
zurück ({status?, priority?, values?, advance?}). Der Aufrufer (Scheduler bzw.
Request-Pfad) wendet sie an – so bleibt die Logik ohne DB testbar.

In Stufe 5 umgesetzt: notify, escalate, set_status, set_priority, set_field,
auto_advance. Erkannt-aber-noch-nicht-ausgeführt (geloggt): spawn_process,
assign_sequence, require_attachment (Attachments hängen noch am Alt-Ticket-System).
"""
import json
from datetime import datetime, timezone
from typing import Callable, Optional

from backend.schemas.process_definition import ProcessDefinition, PhaseDef, Action, ActionType
from backend.services import process_runtime as pr
from backend.utils.config import config
from backend.utils.logger import logger


def resolve_recipients(to: Optional[str], row: dict, phase: Optional[PhaseDef],
                       groups: Optional[list] = None) -> list[str]:
    """Empfänger-Adressen für notify/escalate. Gruppen liefern ihre Verteiler
    (distributions). Nicht auf Adressen auflösbare Ziele (owner/user/watchers/
    supervisor) sowie ein leeres Ergebnis fallen auf TICKET_MAIL zurück – eine
    Aktion läuft NIE stumm ins Leere."""
    if groups is None:
        from backend.database.groups import get_groups
        groups = get_groups()
    by_id = {g.get("id"): g for g in groups}

    def dist(gid):
        g = by_id.get(gid)
        return list(g.get("distributions") or []) if g else []

    emails: set[str] = set()
    if to == "responsible" and phase is not None:
        resp = pr.resolve_responsibility(phase, row.get("values") or {})
        if resp.get("kind") == "group":
            emails |= set(dist(resp.get("group")))
        elif resp.get("kind") == "departments":
            for d in resp.get("departments", []):
                emails |= set(dist(d["group"]))
    elif to and to.startswith("group:"):
        emails |= set(dist(to.split(":", 1)[1]))
    # owner / user / watchers / supervisor: (noch) keine Adressquelle → Fallback.

    emails = {e for e in emails if e}
    if not emails:
        fb = getattr(config, "TICKET_MAIL", "") or ""
        if fb:
            emails.add(fb)
    return sorted(emails)


def _build_message(action: Action, row: dict, phase: Optional[PhaseDef]) -> tuple[str, str]:
    title = row.get("title") or f"Auftrag #{row.get('id')}"
    verb = "Eskalation" if action.type == ActionType.escalate else "Erinnerung"
    phase_lbl = (phase.label or phase.key) if phase else "—"
    subject = f"[AlphaRequest] {verb}: {title}"
    body = (f"<p><b>{verb}</b> für den Auftrag „{title}“ (Phase: {phase_lbl}).</p>"
            f"<p>Bitte im System bearbeiten: {config.FRONTEND_URL}</p>")
    return subject, body


def _default_sender(recipients: list[str], subject: str, body: str, kind: str = "automation") -> None:
    if not recipients:
        return
    from backend.services.microsoft_mail import send_mail_app_only
    send_mail_app_only(
        sender_upn_or_id="alpharequest@alpha-it-innovations.org",
        subject=subject, body=body, to_recipients=list(recipients),
        body_type="HTML", kind=kind,
    )


def run_action(action: Action, row: dict, defn: ProcessDefinition, phase: Optional[PhaseDef],
               *, sender: Callable = _default_sender, groups: Optional[list] = None) -> dict:
    """Führt eine Action aus (Mail-Nebenwirkung) und gibt Zustandsänderungen zurück."""
    t = action.type
    changes: dict = {}
    if t in (ActionType.notify, ActionType.escalate):
        recips = resolve_recipients(action.to, row, phase, groups)
        subject, body = _build_message(action, row, phase)
        try:
            sender(recips, subject, body, kind=t.value)
        except Exception:
            logger.exception("Automation-Mail (%s) fehlgeschlagen für Ticket #%s", t.value, row.get("id"))
        if t == ActionType.escalate:
            changes["priority"] = "high"
    elif t == ActionType.set_priority:
        changes["priority"] = action.value
    elif t == ActionType.set_status:
        changes["status"] = action.value
    elif t == ActionType.set_field:
        changes["values"] = {action.field: action.value}
    elif t == ActionType.auto_advance:
        changes["advance"] = True
    else:
        logger.info("Automation-Action „%s“ ist in Stufe 5 noch nicht umgesetzt (Ticket #%s)",
                    t.value, row.get("id"))
    return changes


def apply_action_changes(row: dict, defn: ProcessDefinition, changes: dict, store) -> None:
    """Persistiert die von run_action gelieferten Zustandsänderungen und
    aktualisiert das übergebene row-Dict in place (kein next_timer-Restamp – das
    macht der Aufrufer). `store` wird injiziert (Testbarkeit)."""
    tid = row["id"]
    if "priority" in changes:
        store.set_priority(tid, changes["priority"])
        row["priority"] = changes["priority"]
    if "status" in changes:
        store.set_status(tid, changes["status"])
        row["status"] = changes["status"]
    if "values" in changes:
        merged = {**(row.get("values") or {}), **changes["values"]}
        store.update_values(tid, json.dumps(merged, ensure_ascii=False))
        row["values"] = merged
    if changes.get("advance"):
        runtime, status = pr.advance(defn, row["runtime"], datetime.now(timezone.utc).isoformat())
        store.update_runtime(tid, runtime_json=json.dumps(runtime, ensure_ascii=False), status=status)
        row["runtime"] = runtime
        row["status"] = status
