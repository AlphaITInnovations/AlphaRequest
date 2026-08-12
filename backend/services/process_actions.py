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
import html
import json
from typing import Callable, Optional

from backend.schemas.process_definition import (
    Action, ActionType, PhaseDef, ProcessDefinition, ResponsibilityKind,
)
from backend.services import process_runtime as pr
from backend.utils.config import config
from backend.utils.logger import logger


def _user_email(user_id: Optional[str]) -> Optional[str]:
    """Mail-Adresse einer Person aus dem AD-Cache. None, wenn nicht auflösbar."""
    if not user_id:
        return None
    try:
        from backend.database.users import get_user
        row = get_user(user_id)
        mail = (row or {}).get("mail") or (row or {}).get("email")
        return mail or None
    except Exception:
        logger.warning("Mail-Adresse für %s nicht auflösbar", user_id)
        return None


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
        kind = resp.get("kind")
        if kind == "group":
            emails |= set(dist(resp.get("group")))
        elif kind == "departments":
            # Nur noch offene Abteilungen anschreiben – wer fertig ist, braucht
            # keine Erinnerung mehr.
            live = pr.current_departments(row.get("runtime") or {})
            targets = ([d["group"] for d in live if d.get("status") not in ("done", "skipped")]
                       if live else [d["group"] for d in resp.get("departments", [])])
            for gid in targets:
                emails |= set(dist(gid))
        elif kind == "user":
            # deckt kind=user UND kind=assignable ab (dort steht die Person im Feld)
            mail = _user_email(resp.get("user"))
            if mail:
                emails.add(mail)
        elif kind == "owner":
            mail = _user_email(row.get("owner_id"))
            if mail:
                emails.add(mail)
    elif to == "owner":
        mail = _user_email(row.get("owner_id"))
        if mail:
            emails.add(mail)
    elif to and to.startswith("group:"):
        emails |= set(dist(to.split(":", 1)[1]))
    # watchers: kommt mit der Beobachter-Funktion; bis dahin greift der Fallback.

    emails = {e for e in emails if e}
    if not emails:
        fb = getattr(config, "TICKET_MAIL", "") or ""
        if fb:
            emails.add(fb)
    return sorted(emails)


def _build_message(action: Action, row: dict, phase: Optional[PhaseDef]) -> tuple[str, str]:
    title = str(row.get("title") or f"Auftrag #{row.get('id')}")
    verb = "Eskalation" if action.type == ActionType.escalate else "Erinnerung"
    phase_lbl = str((phase.label or phase.key) if phase else "—")
    # Betreff: keine Zeilenumbrüche (Header-Injection); Body: HTML escapen.
    subject = f"[AlphaRequest] {verb}: {title}".replace("\r", " ").replace("\n", " ")[:200]
    body = (f"<p><b>{html.escape(verb)}</b> für den Auftrag „{html.escape(title)}“ "
            f"(Phase: {html.escape(phase_lbl)}).</p>"
            f"<p>Bitte im System bearbeiten: {html.escape(config.FRONTEND_URL)}</p>")
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


def notify_phase_entry(row: dict, defn: ProcessDefinition, phase: Optional[PhaseDef],
                       *, sender: Callable = _default_sender,
                       groups: Optional[list] = None) -> list[str]:
    """Beim Betreten einer Phase automatisch die zuständige Stelle informieren.

    Das Alt-System hat das an sechs Stellen gemacht; ohne dieses Verhalten würde
    niemand erfahren, dass Arbeit ansteht – Automationen dafür in JEDEM Prozess
    einzeln zu pflegen wäre eine Fehlerquelle. Abschaltbar je Phase über
    responsibility.notifyOnEnter.

    Gibt die tatsächlichen Empfänger zurück (für Audit/Tests). Wirft nicht.
    """
    if phase is None or not phase.responsibility.notifyOnEnter:
        return []
    # Die Start-Phase gehört der Person, die gerade angelegt hat – die muss man
    # nicht über ihre eigene Eingabe informieren.
    if phase.responsibility.kind == ResponsibilityKind.owner:
        return []
    try:
        recips = resolve_recipients("responsible", row, phase, groups)
        if not recips:
            return []
        title = str(row.get("title") or f"Auftrag #{row.get('id')}")
        phase_lbl = str(phase.label or phase.key)
        subject = (f"[AlphaRequest] Neue Aufgabe: {title}"
                   .replace("\r", " ").replace("\n", " ")[:200])
        body = (f"<p>Der Auftrag „{html.escape(title)}“ liegt jetzt bei Ihnen "
                f"(Phase: {html.escape(phase_lbl)}).</p>"
                f"<p>Zum Bearbeiten: {html.escape(config.FRONTEND_URL)}"
                f"/prozess-auftraege/{row.get('id')}</p>")
        sender(recips, subject, body, kind="phase_entry")
        return recips
    except Exception:
        logger.exception("Phasen-Benachrichtigung für Ticket #%s fehlgeschlagen", row.get("id"))
        return []


def apply_action_changes(row: dict, defn: ProcessDefinition, changes: dict, store) -> None:
    """Persistiert die von run_action gelieferten Zustandsänderungen und
    aktualisiert das übergebene row-Dict in place. `store` wird injiziert
    (Testbarkeit).

    `advance` wird hier NICHT behandelt – der Phasenübergang läuft ausschließlich
    über process_engine.transition (damit on_exit/on_enter und das Neustempeln
    des Timers garantiert mitlaufen)."""
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
