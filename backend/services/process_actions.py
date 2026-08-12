"""
Ausführung von Automation-Actions (§6) – Registry aus Empfänger-Resolvern und
Action-Handlern.

`run_action` löst KEINE Persistenz aus: es versendet ggf. Mail (über einen
injizierbaren Sender) und gibt die gewünschten Zustandsänderungen als dict
zurück ({status?, priority?, values?, advance?}). Der Aufrufer (Scheduler bzw.
Request-Pfad) wendet sie an – so bleibt die Logik ohne DB testbar.

Umgesetzt: notify, escalate, set_status, set_priority, set_field, auto_advance.
Erkannt-aber-noch-nicht-ausgeführt (und daher beim Veröffentlichen abgelehnt,
s. UNIMPLEMENTED_ACTIONS): spawn_process, assign_sequence, require_attachment.

Neben den Automations-Actions liegen hier die beiden festen Benachrichtigungen,
die JEDER Prozess braucht und die niemand pro Prozess konfigurieren soll:
`notify_phase_entry` (Arbeit liegt an) und `notify_comment` (Nachtrag).
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
    """Mail-Adresse einer Person aus dem AD-Cache. None, wenn nicht auflösbar.

    `get_user` liefert eine `AppUser`-Dataclass (kein dict) – deshalb per
    getattr. Beides zu unterstützen ist Absicht: Tests reichen hier Dicts herein.
    """
    if not user_id:
        return None
    try:
        from backend.database.users import get_user
        row = get_user(user_id)
        if row is None:
            return None
        if isinstance(row, dict):
            return row.get("mail") or row.get("email") or None
        return getattr(row, "email", None) or getattr(row, "mail", None) or None
    except Exception:
        logger.warning("Mail-Adresse für %s nicht auflösbar", user_id)
        return None


def watcher_emails(ticket_id) -> list[str]:
    """Mail-Adressen der Beobachter:innen eines Auftrags (leer, wenn keine)."""
    if ticket_id is None:
        return []
    try:
        from backend.database import process_ticket_watchers as watchers
        ids = watchers.watcher_ids(int(ticket_id))
    except Exception:
        logger.warning("Beobachter für #%s nicht ladbar", ticket_id)
        return []
    return [m for m in (_user_email(uid) for uid in sorted(ids)) if m]


def resolve_recipients(to: Optional[str], row: dict, phase: Optional[PhaseDef],
                       groups: Optional[list] = None) -> list[str]:
    """Empfänger-Adressen für notify/escalate. Gruppen liefern ihre Verteiler
    (distributions). Nicht auf Adressen auflösbare Ziele (owner/user/supervisor)
    sowie ein leeres Ergebnis fallen auf TICKET_MAIL zurück – eine Aktion läuft
    NIE stumm ins Leere.

    Ausnahme `watchers`: „niemand beobachtet" ist ein gültiges leeres Ergebnis
    und kein Auflöse-Fehler. Dafür die Zentral-Adresse anzuschreiben wäre nur Lärm.
    """
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
    elif to == "watchers":
        emails |= set(watcher_emails(row.get("id")))
    elif to and to.startswith("group:"):
        emails |= set(dist(to.split(":", 1)[1]))

    emails = {e for e in emails if e}
    if not emails and to == "watchers":
        return []
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
        title = str(row.get("title") or f"Auftrag #{row.get('id')}")
        phase_lbl = str(phase.label or phase.key)
        link = f"{config.FRONTEND_URL}/prozess-auftraege/{row.get('id')}"
        if recips:
            subject = (f"[AlphaRequest] Neue Aufgabe: {title}"
                       .replace("\r", " ").replace("\n", " ")[:200])
            body = (f"<p>Der Auftrag „{html.escape(title)}“ liegt jetzt bei Ihnen "
                    f"(Phase: {html.escape(phase_lbl)}).</p>"
                    f"<p>Zum Bearbeiten: {html.escape(link)}</p>")
            sender(recips, subject, body, kind="phase_entry")

        # Beobachter:innen bekommen eine EIGENE Mail – „liegt jetzt bei Ihnen"
        # wäre für sie falsch, sie sollen nur mitlesen. Wer schon als zuständige
        # Stelle angeschrieben wurde, bekommt sie nicht doppelt.
        extra = [m for m in watcher_emails(row.get("id")) if m not in set(recips)]
        if extra:
            w_subject = (f"[AlphaRequest] Zur Information: {title}"
                         .replace("\r", " ").replace("\n", " ")[:200])
            w_body = (f"<p>Der von Ihnen beobachtete Auftrag „{html.escape(title)}“ "
                      f"ist jetzt in der Phase „{html.escape(phase_lbl)}“.</p>"
                      f"<p>Ansehen: {html.escape(link)}</p>")
            sender(extra, w_subject, w_body, kind="phase_entry_watcher")
        return list(recips) + extra
    except Exception:
        logger.exception("Phasen-Benachrichtigung für Ticket #%s fehlgeschlagen", row.get("id"))
        return []


def notify_comment(row: dict, phase: Optional[PhaseDef], *, author_name: str,
                   body_text: str, internal: bool = False,
                   actor_email: Optional[str] = None,
                   sender: Callable = _default_sender,
                   groups: Optional[list] = None) -> list[str]:
    """Über einen Nachtrag (Kommentar) informieren. Wirft nicht.

    Empfänger: die zuständige Stelle, die Ersteller:in und die Beobachter:innen –
    ohne die schreibende Person selbst (die weiß es ja). Bei einem INTERNEN
    Nachtrag entfallen Ersteller:in und Beobachter:innen: der Text ist nur für
    die bearbeitende Seite gedacht, also darf er auch nur dorthin gemailt werden.
    """
    try:
        recips = set(resolve_recipients("responsible", row, phase, groups))
        if not internal:
            owner = _user_email(row.get("owner_id"))
            if owner:
                recips.add(owner)
            recips |= set(watcher_emails(row.get("id")))
        if actor_email:
            recips.discard(actor_email)
        if not recips:
            return []
        title = str(row.get("title") or f"Auftrag #{row.get('id')}")
        marker = "Interner Nachtrag" if internal else "Nachtrag"
        subject = (f"[AlphaRequest] {marker}: {title}"
                   .replace("\r", " ").replace("\n", " ")[:200])
        # Freitext einer Person → konsequent escapen, Zeilenumbrüche erhalten.
        text = html.escape(body_text or "").replace("\n", "<br>")
        out = sorted(recips)
        mail_body = (f"<p><b>{html.escape(marker)}</b> von {html.escape(author_name)} "
                     f"zum Auftrag „{html.escape(title)}“:</p>"
                     f"<blockquote>{text}</blockquote>"
                     f"<p>Zum Auftrag: {html.escape(config.FRONTEND_URL)}"
                     f"/prozess-auftraege/{row.get('id')}</p>")
        sender(out, subject, mail_body, kind="comment")
        return out
    except Exception:
        logger.exception("Nachtrags-Benachrichtigung für Ticket #%s fehlgeschlagen", row.get("id"))
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
