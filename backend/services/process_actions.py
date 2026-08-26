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

Neben den Automations-Actions liegen hier die festen Benachrichtigungen, die
JEDER Prozess braucht und die niemand pro Prozess konfigurieren soll:
Diese Mails gehen an die ZUSTÄNDIGE Stelle (und bei Ablehnung/Rücksprung an die
Ersteller:in), NIE automatisch an Beobachter:innen – Beobachten heißt mitlesen.
Wer sie doch anschreiben will, konfiguriert das im Prozess ausdrücklich:
`notify` mit `to: "watchers"`.

`notify_phase_entry` (Arbeit liegt an – bei einer Freigabe-Phase mit
Entscheidungs-Links statt „bitte im System bearbeiten“), `notify_comment`
(Nachtrag), `notify_rejection` (Auftrag abgelehnt) und `notify_sent_back`
(zur Nachbesserung zurückgegeben).
"""
import html
import json
from typing import Callable, Optional

from backend.schemas.process_definition import (
    Action, ActionType, PhaseDef, PhaseKind, ProcessDefinition,
)
from backend.services import process_runtime as pr
from backend.utils.config import config
from backend.utils.logger import logger
from backend.utils.mail_templates import FONT as _MAIL_FONT
from backend.utils.mail_templates import MailBranding, render_corporate_email


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


# Eine Instanz reicht – die Palette ist konstant und liefert die Marken-Farben
# für die Mail-Bausteine (Button, Zitat-Block).
_BRAND = MailBranding()


def _primary_button_html(url: str, label: str = "Auftrag öffnen") -> str:
    """Ein mailsicherer Haupt-Button (Türkis) – Tabelle statt Flexbox (Outlook)."""
    href = html.escape(url, quote=True)
    return f"""
    <table role="presentation" cellpadding="0" cellspacing="0" style="margin-top:22px;">
      <tr><td style="border-radius:10px; background:{_BRAND.primary_color};">
        <a href="{href}"
           style="display:inline-block; color:#ffffff; font-family:{_MAIL_FONT};
                  font-size:15px; font-weight:600; text-decoration:none; padding:13px 30px;
                  border-radius:10px;">{html.escape(label)}</a>
      </td></tr>
    </table>
    """


def _quote_block(text: Optional[str]) -> str:
    """Freitext (Begründung, Nachtrag) als abgesetzter Zitat-Block – escaped,
    Zeilenumbrüche erhalten. Leerer Text → leerer String."""
    inner = html.escape(text or "").replace("\n", "<br>")
    if not inner.strip():
        return ""
    return (f'<div style="margin-top:16px; padding:14px 16px; background:{_BRAND.surface_subtle};'
            f' border-left:3px solid {_BRAND.primary_color}; border-radius:10px;'
            f' font-family:{_MAIL_FONT}; color:{_BRAND.text_color};'
            f' font-size:14px; line-height:1.6;">{inner}</div>')


def _build_message(action: Action, row: dict, phase: Optional[PhaseDef]) -> tuple[str, str]:
    title = str(row.get("title") or f"Auftrag #{row.get('id')}")
    # `template` ist der frei wählbare Anlass-Text der Automation. Ohne ihn steht
    # dort „Erinnerung" bzw. „Eskalation" – was für eine gerade übernommene
    # Aufgabe falsch klingt („Erinnerung" an etwas, das man erstmals sieht).
    verb = (action.template or "").strip() or (
        "Eskalation" if action.type == ActionType.escalate else "Erinnerung")
    phase_lbl = str((phase.label or phase.key) if phase else "—")
    link = _ticket_link(row)
    # Betreff: keine Zeilenumbrüche (Header-Injection).
    subject = f"[AlphaRequest] {verb}: {title}".replace("\r", " ").replace("\n", " ")[:200]
    body = render_corporate_email(
        subject=subject,
        header_subtitle=verb,
        headline=title,
        info_box_url=link,
        intro="Dieser Auftrag wartet auf Ihre Bearbeitung.",
        info_rows=[("Auftrag", f"#{row.get('id')}"), ("Phase", phase_lbl)],
        action_html=_primary_button_html(link),
        content="",
    )
    return subject, body


def _default_sender(recipients: list[str], subject: str, body: str, kind: str = "automation",
                    attachments: Optional[list] = None) -> None:
    if not recipients:
        return
    from backend.services.microsoft_mail import brand_logo_attachment, send_mail_app_only
    # Das Logo IMMER mitschicken: das Corporate-Template referenziert es über
    # cid:alpha_logo; ohne Inline-Anhang bliebe im Kopf ein kaputtes Bild.
    logo = brand_logo_attachment()
    alle = ([logo] if logo else []) + list(attachments or [])
    send_mail_app_only(
        sender_upn_or_id="alpharequest@alpha-it-innovations.org",
        subject=subject, body=body, to_recipients=list(recipients),
        body_type="HTML", kind=kind, attachments=alle or None,
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


# ── Freigabe per Mail-Link ────────────────────────────────────────────────────

def _ticket_link(row: dict) -> str:
    """Mail-Link in die BEARBEITUNGS-Ansicht: die Detailseite öffnet standardmäßig
    nur lesend, und Mails gehen an die Stelle, die handeln soll. Ohne Rechte
    zeigt der Parameter trotzdem nur die Leseansicht (abilities entscheiden)."""
    return f"{config.FRONTEND_URL}/prozess-auftraege/{row.get('id')}?ansicht=bearbeiten"


def _subject(text: str) -> str:
    """Betreff ohne Zeilenumbrüche (Header-Injection) und in sicherer Länge."""
    return text.replace("\r", " ").replace("\n", " ")[:200]


def _duration_text(seconds: int) -> str:
    """„7 Tage“ / „12 Stunden“ – aus einer ISO-Dauer wird lesbarer Text."""
    if seconds % 86400 == 0:
        tage = seconds // 86400
        return f"{tage} Tag" if tage == 1 else f"{tage} Tage"
    if seconds % 3600 == 0:
        std = seconds // 3600
        return f"{std} Stunde" if std == 1 else f"{std} Stunden"
    return f"{max(1, seconds // 60)} Minuten"


def approval_links(row: dict, phase: PhaseDef) -> tuple[str, str]:
    """Die beiden Entscheidungs-Links (JA/NEIN) für die aktuelle Phase.

    Beide tragen den aktuellen Epoch: nach einer Wiederaufnahme oder einem
    Rücksprung sind die Links der vorigen Runde wirkungslos.
    """
    from backend.services import process_approval as approval
    base = (getattr(config, "FRONTEND_URL", "") or "").rstrip("/")
    epoch = int((row.get("runtime") or {}).get("epoch", 0))
    tid = row.get("id")

    def url(act: str) -> str:
        token = approval.make_token(tid, act, phase.key, epoch)
        return f"{base}/api/v1/process-freigabe?token={token}"

    return url("approve"), url("reject")


def _approval_buttons_html(approve_url: str, reject_url: str,
                           approve_label: str, reject_label: str) -> str:
    """Zwei mailsichere Aktions-Knöpfe (Tabelle statt Flexbox – Outlook)."""
    a_url, r_url = html.escape(approve_url, quote=True), html.escape(reject_url, quote=True)
    return f"""
    <table role="presentation" cellpadding="0" cellspacing="0" style="margin-top:20px;">
      <tr>
        <td style="padding-right:10px;">
          <a href="{a_url}"
             style="display:inline-block; background:#15A34A; color:#ffffff;
                    font-family:{_MAIL_FONT}; font-size:15px; font-weight:600;
                    text-decoration:none; padding:13px 28px; border-radius:10px;">
            &#10003;&nbsp; {html.escape(approve_label)}
          </a>
        </td>
        <td>
          <a href="{r_url}"
             style="display:inline-block; background:{_BRAND.surface}; color:#C0392F;
                    font-family:{_MAIL_FONT}; font-size:15px; font-weight:600;
                    text-decoration:none; padding:12px 27px; border-radius:10px;
                    border:1px solid #E7B8B4;">
            &#10007;&nbsp; {html.escape(reject_label)}
          </a>
        </td>
      </tr>
    </table>
    """


def _attachment_note_html(n: int) -> str:
    """Kleiner Hinweis in der Freigabe-Mail, dass Dateien beigefügt sind."""
    if n <= 0:
        return ""
    was = "1 Datei ist" if n == 1 else f"{n} Dateien sind"
    return (f'<p style="font-family:{_MAIL_FONT}; font-size:13px; color:{_BRAND.muted_text}; '
            f'margin:14px 0 0 0;">&#128206; {was} dieser E-Mail beigefügt (z. B. Lebenslauf).</p>')


def _approval_message(row: dict, phase: PhaseDef, title: str,
                      *, n_attachments: int = 0) -> tuple[str, str]:
    from backend.services import mail_template as mt
    from backend.services.iso_duration import parse_duration
    spec = phase.approval
    approve_url, reject_url = approval_links(row, phase)
    try:
        gueltig = _duration_text(parse_duration(spec.linkMaxAge))
    except Exception:
        gueltig = spec.linkMaxAge
    subject = _subject(f"[AlphaRequest] Freigabe erforderlich: {title}")

    # Vorlagentext `approval.emailBody` mit Auftragswerten füllen (reiner Text –
    # das Template escaped ihn als `content`). {{title}}/{{id}} zusätzlich.
    values = row.get("values") or {}

    def resolve(token: str) -> str:
        if token == "title":
            return title
        if token == "id":
            return str(row.get("id") or "")
        return mt.format_value(values.get(token))

    info_text = mt.substitute(spec.emailBody, resolve).strip() if spec.emailBody else ""

    # Aktionsblock: Frage (fett) → Anhang-Hinweis → JA/NEIN-Knöpfe → Gültigkeit.
    question_html = (
        f'<div style="font-family:{_MAIL_FONT}; color:{_BRAND.heading_color};'
        f' font-size:16px; font-weight:700; margin-top:20px;">{html.escape(spec.question)}</div>')
    validity_html = (
        f'<p style="font-family:{_MAIL_FONT}; font-size:12px;'
        f' color:{_BRAND.muted_text}; line-height:1.6; margin-top:16px;">Der Link öffnet eine '
        f'Bestätigungsseite – erst dort wird entschieden. Eine Anmeldung ist nicht nötig. '
        f'Gültig {html.escape(gueltig)} ab Versand.</p>')
    action_html = (question_html + _attachment_note_html(n_attachments)
                   + _approval_buttons_html(approve_url, reject_url,
                                            spec.approveLabel, spec.rejectLabel)
                   + validity_html)

    body = render_corporate_email(
        subject=subject,
        header_subtitle="Freigabe erforderlich",
        headline=title,
        info_box_url=None,        # externe Empfänger:innen haben keinen Zugang → nicht klickbar
        intro=f"Für diesen Auftrag (#{row.get('id')}) wird Ihre Entscheidung gebraucht.",
        info_rows=[("Auftrag", f"#{row.get('id')}")],
        content=info_text,
        action_html=action_html,
    )
    return subject, body


# Gesamtgröße der base64-KODIERTEN Anhänge (genau das, was Graph inline als
# `contentBytes` überträgt). Graph deckelt die GESAMTE Nachricht bei ~4 MB, und
# base64 bläht die Rohgröße um 4/3 auf – deshalb messen wir die KODIERTE Länge und
# bleiben konservativ darunter (eine Rohgrößen-Prüfung ließe eine 3-MB-Datei durch,
# die kodiert ~4 MB ergibt und den Versand still scheitern ließe).
_MAIL_ATTACH_TOTAL_LIMIT = int(3.5 * 1024 * 1024)


def _ticket_attachments(row: dict) -> list:
    """Aktuelle Datei-Anhänge des Auftrags als Mail-Anhänge (Freigabe-Mail).

    Nur die jeweils aktuellen Versionen, bis zu einem Gesamt-Limit (base64-kodiert
    gemessen). Fehlende, unlesbare oder zu große Dateien werden ausgelassen (Log) –
    ein Anhang-Problem darf den Versand der Freigabe-Mail nie kippen.
    """
    tid = row.get("id")
    if not tid:
        return []
    try:
        from backend.database import attachments as att_db
        from backend.services import attachment_storage as storage
        from backend.services.microsoft_mail import attachment_from_path
    except Exception:
        logger.exception("Anhang-Module für Freigabe-Mail nicht ladbar (#%s)", tid)
        return []
    try:
        rows = att_db.list_for_ticket(tid, entity_type=att_db.ENTITY_PROCESS_TICKET)
    except Exception:
        logger.exception("Anhänge für Freigabe-Mail nicht ladbar (#%s)", tid)
        return []
    out: list = []
    total = 0
    for a in rows:
        name = a.get("original_filename") or "Anhang"
        try:
            path = storage.full_path(a["stored_path"])
            att = attachment_from_path(str(path), filename=name)
            enc = len(getattr(att, "content_bytes_b64", "") or "")   # ~ übertragene Größe
            if total + enc > _MAIL_ATTACH_TOTAL_LIMIT:
                logger.warning("Freigabe-Mail #%s: „%s“ ausgelassen – kodiertes "
                               "Gesamtlimit %d B erreicht", tid, name,
                               _MAIL_ATTACH_TOTAL_LIMIT)
                continue
            out.append(att)
            total += enc
        except Exception:
            logger.exception("Freigabe-Mail #%s: „%s“ nicht anhängbar", tid, name)
    return out


def _report_recipient_gap(row: dict, phase: PhaseDef, recips: list[str]) -> None:
    """Eine Freigabe ohne erreichbare Empfänger:in darf nicht still liegen bleiben.

    Bisher hätte nur ein `logger.warning` davon erzählt – der Auftrag wartet dann
    auf eine Entscheidung, die niemand angefordert bekommen hat. Deshalb hier
    zusätzlich ein Audit-Eintrag UND ein Verlaufs-Eintrag am Auftrag (den sieht
    die zuständige Seite, das Audit nur die Aufsicht).

    Der Ersatz-Fall wird an der Zentraladresse erkannt: liefert
    `resolve_recipients` genau TICKET_MAIL, ist der Verteiler der Gruppe leer
    (in dem seltenen Fall, dass eine Gruppe genau diese Adresse als Verteiler
    führt, ist der Hinweis harmlos falsch-positiv).
    """
    fallback = (getattr(config, "TICKET_MAIL", "") or "")
    ersatz = bool(recips) and bool(fallback) and recips == [fallback]
    if recips and not ersatz:
        return

    from backend.database.audit_log import record_audit
    from backend.services import process_approval as approval
    from backend.services import process_events as events

    grund = ("kein Verteiler hinterlegt und keine Zentraladresse konfiguriert"
             if not recips else
             "kein Verteiler hinterlegt – ersatzweise an die Zentraladresse")
    logger.error("Freigabe-Mail für #%s (Phase %s): %s", row.get("id"), phase.key, grund)
    details = {"phase": phase.key, "reason": grund, "recipients": list(recips)}
    record_audit(
        action="process_approval_no_recipient", actor_id=None, actor_name="System",
        actor_type="system", entity_type="process_ticket", entity_id=str(row.get("id")),
        summary=f"Freigabe-Phase „{phase.label or phase.key}“: {grund}",
        details=details,
    )
    events.system(row, approval.EVENT_NO_RECIPIENT, phase_key=phase.key, details=details)


def notify_phase_entry(row: dict, defn: ProcessDefinition, phase: Optional[PhaseDef],
                       *, sender: Callable = _default_sender,
                       groups: Optional[list] = None) -> list[str]:
    """Beim Betreten einer Phase automatisch die zuständige Stelle informieren.

    Das Alt-System hat das an sechs Stellen gemacht; ohne dieses Verhalten würde
    niemand erfahren, dass Arbeit ansteht – Automationen dafür in JEDEM Prozess
    einzeln zu pflegen wäre eine Fehlerquelle. Abschaltbar je Phase über
    responsibility.notifyOnEnter.

    Bei einer Freigabe-Phase mit `approval.externalLink` geht statt der
    „bitte im System bearbeiten“-Mail die Entscheidungs-Mail mit JA/NEIN-Links
    raus – die entscheidende Person hat womöglich gar keinen Zugang.
    Beobachter:innen bekommen weiterhin NUR die Info-Mail, niemals die Links.

    Gibt die tatsächlichen Empfänger zurück (für Audit/Tests). Wirft nicht.
    """
    if phase is None or not phase.responsibility.notifyOnEnter:
        return []
    freigabe = (phase.kind == PhaseKind.approval and phase.approval is not None
                and phase.approval.externalLink)
    # NUR die Start-Phase überspringt die Benachrichtigung: dort legt die
    # erstellende Person gerade selbst an – sie über ihre eigene Eingabe zu
    # informieren wäre sinnlos. Eine SPÄTERE Phase, die (über
    # responsibility.kind=owner) zur erstellenden Person zurückkommt, ist dagegen
    # eine echte neue Aufgabe für sie und MUSS eine Mail auslösen – früher hat die
    # Prüfung auf owner das fälschlich mitunterdrückt.
    if phase.kind == PhaseKind.start:
        return []
    try:
        recips = resolve_recipients("responsible", row, phase, groups)
        title = str(row.get("title") or f"Auftrag #{row.get('id')}")
        phase_lbl = str(phase.label or phase.key)
        link = _ticket_link(row)
        if freigabe:
            # Ohne erreichbare Empfänger:in bleibt der Auftrag unbemerkt liegen –
            # das muss sichtbar werden, nicht nur im Log stehen.
            _report_recipient_gap(row, phase, recips)
            if recips:
                # Hochgeladene Dateien (z. B. Lebenslauf) reisen mit – die
                # freigebende Person hat sonst keinen Zugang zum Auftrag.
                atts = _ticket_attachments(row)
                subject, body = _approval_message(row, phase, title,
                                                  n_attachments=len(atts))
                extra = {"attachments": atts} if atts else {}
                sender(recips, subject, body, kind="approval_link", **extra)
        elif recips:
            subject = _subject(f"[AlphaRequest] Neue Aufgabe: {title}")
            body = render_corporate_email(
                subject=subject,
                header_subtitle="Neue Aufgabe",
                headline=title,
                info_box_url=link,
                intro="Dieser Auftrag liegt jetzt bei Ihnen zur Bearbeitung.",
                info_rows=[("Auftrag", f"#{row.get('id')}"), ("Phase", phase_lbl)],
                action_html=_primary_button_html(link),
                content="",
            )
            sender(recips, subject, body, kind="phase_entry")

        # KEINE Mail an Beobachter:innen. Beobachten heißt MITLESEN: der Auftrag
        # erscheint in der Übersicht und zeigt dort den aktuellen Stand. Wer
        # freiwillig folgt, will nicht bei jedem Phasenwechsel eine Mail – und ein
        # Postfach voller „zur Information“ macht die Mails unwichtig, die
        # wirklich eine Aufgabe ankündigen.
        return list(recips)
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
            # Bewusst OHNE Beobachter:innen – Beobachten heißt mitlesen, nicht
            # benachrichtigt werden (siehe notify_phase_entry).
        if actor_email:
            recips.discard(actor_email)
        if not recips:
            return []
        title = str(row.get("title") or f"Auftrag #{row.get('id')}")
        marker = "Interner Nachtrag" if internal else "Nachtrag"
        subject = (f"[AlphaRequest] {marker}: {title}"
                   .replace("\r", " ").replace("\n", " ")[:200])
        link = _ticket_link(row)
        out = sorted(recips)
        mail_body = render_corporate_email(
            subject=subject,
            header_subtitle=marker,
            headline=title,
            info_box_url=link,
            intro=f"{author_name} hat einen {marker.lower()} zu diesem Auftrag hinterlassen:",
            content="",
            action_html=_quote_block(body_text) + _primary_button_html(link),
        )
        sender(out, subject, mail_body, kind="comment")
        return out
    except Exception:
        logger.exception("Nachtrags-Benachrichtigung für Ticket #%s fehlgeschlagen", row.get("id"))
        return []


def notify_rejection(row: dict, defn: Optional[ProcessDefinition], *,
                     reason: Optional[str], by_name: str,
                     sender: Callable = _default_sender,
                     groups: Optional[list] = None) -> list[str]:
    """Die Ersteller:in über die Ablehnung ihres Auftrags informieren. Wirft nicht.

    Vorbild: microsoft_mail.send_rejection_mail. Empfänger ist bewusst nur die
    Ersteller:in (über `resolve_recipients("owner", …)`, also inklusive
    Zentraladressen-Ersatz statt stiller Nicht-Zustellung) – die bearbeitende
    Seite hat gerade selbst abgelehnt und braucht keine Rückmeldung darüber.

    `by_name` beschreibt, WER abgelehnt hat. Bei einer Entscheidung per Mail-Link
    gibt es keine Identität; dort steht der Kanal statt eines erfundenen Namens.
    """
    try:
        recips = resolve_recipients("owner", row, None, groups)
        if not recips:
            return []
        title = str(row.get("title") or f"Auftrag #{row.get('id')}")
        subject = _subject(f"[AlphaRequest] Auftrag abgelehnt: {title}")
        link = _ticket_link(row)
        info_rows = [("Auftrag", f"#{row.get('id')}"), ("Abgelehnt von", by_name)]
        if not reason:
            info_rows.append(("Begründung", "keine angegeben"))
        body = render_corporate_email(
            subject=subject,
            header_subtitle="Auftrag abgelehnt",
            headline=title,
            info_box_url=link,
            intro=f"Ihr Auftrag (#{row.get('id')}) wurde abgelehnt.",
            info_rows=info_rows,
            content="",
            action_html=_quote_block(reason) + _primary_button_html(link),
        )
        sender(recips, subject, body, kind="rejection")
        return list(recips)
    except Exception:
        logger.exception("Ablehnungs-Mail für Ticket #%s fehlgeschlagen", row.get("id"))
        return []


def notify_sent_back(row: dict, defn: Optional[ProcessDefinition],
                     phase: Optional[PhaseDef], *, reason: Optional[str],
                     by_name: str, sender: Callable = _default_sender,
                     groups: Optional[list] = None) -> list[str]:
    """Auftrag wurde zur Nachbesserung auf eine frühere Phase zurückgegeben.

    Eigene Mail statt `notify_phase_entry`, aus zwei Gründen:
      * Die Zielphase gehört typischerweise der ERSTELLER:IN – und genau die
        überspringt `notify_phase_entry` bewusst („nicht über die eigene Eingabe
        informieren“). Beim Rücksprung wäre das falsch, der Auftrag bliebe
        unbemerkt liegen.
      * Ohne die Begründung wäre die Mail wertlos: „liegt wieder bei Ihnen“
        beantwortet nicht, was nachzubessern ist.

    Wirft nicht; gibt die Empfänger zurück.
    """
    try:
        recips = set(resolve_recipients("responsible", row, phase, groups))
        owner = _user_email(row.get("owner_id"))
        if owner:
            recips.add(owner)
        # Bewusst OHNE Beobachter:innen – Beobachten heißt mitlesen.
        if not recips:
            return []
        title = str(row.get("title") or f"Auftrag #{row.get('id')}")
        phase_lbl = str((phase.label or phase.key) if phase else "—")
        subject = _subject(f"[AlphaRequest] Nachbesserung nötig: {title}")
        link = _ticket_link(row)
        out = sorted(recips)
        info_rows = [("Auftrag", f"#{row.get('id')}"), ("Phase", phase_lbl),
                     ("Zurückgegeben von", by_name)]
        body = render_corporate_email(
            subject=subject,
            header_subtitle="Nachbesserung nötig",
            headline=title,
            info_box_url=link,
            intro="Dieser Auftrag wurde in der Freigabe zurückgegeben und liegt wieder bei Ihnen.",
            info_rows=info_rows,
            content=("" if reason else "Eine Rückmeldung wurde nicht angegeben."),
            action_html=_quote_block(reason) + _primary_button_html(link),
        )
        sender(out, subject, body, kind="sent_back")
        return out
    except Exception:
        logger.exception("Nachbesserungs-Mail für Ticket #%s fehlgeschlagen", row.get("id"))
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
        # rev-Guard UND frischer Stand: hier wird der KOMPLETTE values-Blob
        # zurückgeschrieben. Ohne beides könnte eine Automation mit veraltetem
        # row-Dict eine gerade vergebene Nummer (server_generated) wieder
        # entfernen. Ein Konflikt landet über fire() als fehlgeschlagene
        # Automation im Audit – laut statt still.
        fresh = store.get(tid) or {}
        merged = {**(fresh.get("values") or row.get("values") or {}), **changes["values"]}
        updated = store.update_values(tid, json.dumps(merged, ensure_ascii=False),
                                      expected_rev=fresh.get("rev"))
        if updated:
            row.update(updated)
        else:
            row["values"] = merged
