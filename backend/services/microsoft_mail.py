"""Mailversand über Microsoft Graph.

Nur noch die Bausteine, an denen der Benachrichtigungs-Pfad des Prozess-Systems
hängt: Payload bauen, versenden (app-only und delegiert), Audit/Metrik je
Versand, Anhänge. Die fachlichen Alt-Mails (Eingangs-, Freigabe-, Ablehnungs-,
Nachtrags-Mail des Ticket-Systems) sind mit dem Alt-System entfallen – die
Prozess-Aufträge bauen ihre Mails selbst (services/process_actions.py).
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Union
import base64
import mimetypes
import os

import requests
from fastapi import Request

from backend.services.microsoft_auth import acquire_app_token
from backend.utils.logger import logger
from backend.utils.mail_templates import render_corporate_email
from backend.utils.config import config
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"


def _dev_prefix(subject: str) -> str:
    """Betreff in Nicht-Produktionsumgebungen mit [DEV] kennzeichnen."""
    env = (config.APP_ENV or "").strip()
    return f"[DEV] {subject}" if env.lower() != "production" else subject


class GraphMailError(RuntimeError):
    """Raised when Microsoft Graph sendMail fails."""


@dataclass
class EmailRecipient:
    address: str
    name: Optional[str] = None

    def to_graph(self) -> Dict[str, Any]:
        data = {"address": self.address}
        if self.name:
            data["name"] = self.name
        return {"emailAddress": data}


@dataclass
class EmailAttachment:
    filename: str
    content_bytes_b64: str
    content_type: str = "application/octet-stream"
    is_inline: bool = False
    content_id: Optional[str] = None

    def to_graph(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": self.filename,
            "contentType": self.content_type,
            "contentBytes": self.content_bytes_b64,
        }
        # Inline image support (CID)
        if self.is_inline:
            data["isInline"] = True
        if self.content_id:
            data["contentId"] = self.content_id
        return data

def inline_attachment_from_path(path: str, *, content_id: str, filename: str | None = None) -> EmailAttachment:
    p = pathlib.Path(path)

    # Wenn relativer Pfad: relativ zu .../backend/
    if not p.is_absolute():
        package_root = pathlib.Path(__file__).resolve().parents[1]  # services/.. = backend/
        p = (package_root / p).resolve()

    if not p.exists():
        raise FileNotFoundError(str(p))

    fname = filename or p.name
    ctype, _ = mimetypes.guess_type(str(p))
    ctype = ctype or "application/octet-stream"

    raw = p.read_bytes()
    b64 = base64.b64encode(raw).decode("utf-8")

    return EmailAttachment(
        filename=fname,
        content_bytes_b64=b64,
        content_type=ctype,
        is_inline=True,
        content_id=content_id,
    )

def brand_logo_attachment() -> Optional[EmailAttachment]:
    """Alpha-Logo als Inline-Anhang (cid:alpha_logo) für render_corporate_email.

    Das Corporate-Template referenziert den Kopf über `cid:alpha_logo`; ohne
    diesen Inline-Anhang bliebe dort ein kaputtes Bild. Fehlt die Datei, wird
    None geliefert – eine Mail darf am Logo nie scheitern.
    """
    try:
        return inline_attachment_from_path("static/logo.png", content_id="alpha_logo")
    except Exception:
        logger.warning("Mail-Logo (static/logo.png) nicht einbettbar – Mail ohne Logo")
        return None


def _guess_content_type(path: str) -> str:
    ctype, _ = mimetypes.guess_type(path)
    return ctype or "application/octet-stream"


def attachment_from_path(path: str, filename: Optional[str] = None) -> EmailAttachment:
    """
    Load a file from disk and convert to a Graph fileAttachment (contentBytes base64).

    WARNING: This is not suited for large attachments.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    fname = filename or os.path.basename(path)
    ctype = _guess_content_type(path)

    with open(path, "rb") as f:
        raw = f.read()

    b64 = base64.b64encode(raw).decode("utf-8")
    return EmailAttachment(filename=fname, content_bytes_b64=b64, content_type=ctype)


def _auth_header(access_token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }


def build_message_payload(
    subject: str,
    body: str,
    to_recipients: Sequence[Union[str, EmailRecipient]],
    *,
    cc_recipients: Optional[Sequence[Union[str, EmailRecipient]]] = None,
    bcc_recipients: Optional[Sequence[Union[str, EmailRecipient]]] = None,
    body_type: str = "HTML",  # "HTML" or "Text"
    reply_to: Optional[Sequence[Union[str, EmailRecipient]]] = None,
    attachments: Optional[Sequence[EmailAttachment]] = None,
    importance: Optional[str] = None,  # "low" | "normal" | "high"
) -> Dict[str, Any]:
    """
    Creates the JSON payload expected by Graph sendMail.
    """
    def _normalize(recips: Sequence[Union[str, EmailRecipient]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for r in recips:
            if isinstance(r, str):
                out.append(EmailRecipient(address=r).to_graph())
            else:
                out.append(r.to_graph())
        return out

    message: Dict[str, Any] = {
        "subject": subject,
        "body": {"contentType": body_type, "content": body},
        "toRecipients": _normalize(to_recipients),
    }

    if cc_recipients:
        message["ccRecipients"] = _normalize(cc_recipients)
    if bcc_recipients:
        message["bccRecipients"] = _normalize(bcc_recipients)
    if reply_to:
        message["replyTo"] = _normalize(reply_to)
    if importance:
        message["importance"] = importance

    if attachments:
        message["attachments"] = [a.to_graph() for a in attachments]

    return {
        "message": message,
        "saveToSentItems": True,
    }


def _audit_mail(payload: Dict[str, Any], kind: str, outcome: str, detail: Optional[str] = None) -> None:
    """Schreibt einen Audit-Eintrag pro Mailversand (an wen, welcher Typ, Betreff,
    Ergebnis). Rein informativ – darf den Versand nie stören (best-effort)."""
    try:
        msg = payload.get("message", {}) if isinstance(payload, dict) else {}

        def _addrs(key: str) -> list:
            return [
                (r.get("emailAddress") or {}).get("address")
                for r in (msg.get(key) or [])
                if (r.get("emailAddress") or {}).get("address")
            ]

        to = _addrs("toRecipients")
        cc = _addrs("ccRecipients")
        subject = msg.get("subject")
        recips = ", ".join(to) or "—"
        summary = (f"Mail '{kind}' an {recips}" if outcome == "sent"
                   else f"Mailversand '{kind}' an {recips} fehlgeschlagen")

        from backend.database.audit_log import record_audit
        record_audit(
            action="mail_sent" if outcome == "sent" else "mail_failed",
            actor_type="system",
            actor_name="System",
            entity_type="mail",
            entity_id=kind,
            summary=summary,
            details={
                "kind": kind, "to": to, "cc": cc, "subject": subject,
                "outcome": outcome, **({"error": detail} if detail else {}),
            },
        )
    except Exception:
        pass


def _post_sendmail(url: str, access_token: str, payload: Dict[str, Any], timeout_s: int = 30,
                   *, kind: str = "other") -> None:
    from backend.metrics.mail_metrics import record_mail
    try:
        resp = requests.post(url, headers=_auth_header(access_token), json=payload, timeout=timeout_s)
    except Exception as e:
        record_mail(kind, "error")
        _audit_mail(payload, kind, "failed", str(e)[:200])
        raise
    if resp.status_code >= 400:
        record_mail(kind, "error")
        # Graph error responses are usually JSON with "error": {"code","message",...}
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text

        _audit_mail(payload, kind, "failed", f"HTTP {resp.status_code}")
        raise GraphMailError(
            f"Graph sendMail failed: HTTP {resp.status_code} - {detail}"
        )
    record_mail(kind, "sent")
    _audit_mail(payload, kind, "sent")


# -------------------------
# Public API
# -------------------------

def send_mail_delegated(
    access_token: str,
    subject: str,
    body: str,
    to_recipients: Sequence[Union[str, EmailRecipient]],
    *,
    cc_recipients: Optional[Sequence[Union[str, EmailRecipient]]] = None,
    bcc_recipients: Optional[Sequence[Union[str, EmailRecipient]]] = None,
    body_type: str = "HTML",
    reply_to: Optional[Sequence[Union[str, EmailRecipient]]] = None,
    attachments: Optional[Sequence[EmailAttachment]] = None,
    importance: Optional[str] = None,
    kind: str = "other",
) -> None:
    """
    Sends email as the signed-in user (delegated permission).
    Requires: delegated Mail.Send
    Endpoint: POST /me/sendMail
    """
    payload = build_message_payload(
        subject=_dev_prefix(subject),
        body=body,
        to_recipients=to_recipients,
        cc_recipients=cc_recipients,
        bcc_recipients=bcc_recipients,
        body_type=body_type,
        reply_to=reply_to,
        attachments=attachments,
        importance=importance,
    )
    url = f"{GRAPH_BASE_URL}/me/sendMail"
    _post_sendmail(url, access_token, payload, kind=kind)


def send_mail_delegated_from_request(
    request: Request,
    token_result: Dict[str, Any],
    subject: str,
    body: str,
    to_recipients: Sequence[Union[str, EmailRecipient]],
    **kwargs: Any,
) -> None:
    """
    Convenience wrapper if you already have `token_result` from your auth flow
    (e.g. acquire_token_by_auth_code(...)).
    """
    access_token = token_result.get("access_token")
    if not access_token:
        raise ValueError("token_result has no access_token")
    send_mail_delegated(access_token, subject, body, to_recipients, **kwargs)


def send_mail_app_only(
    sender_upn_or_id: str,
    subject: str,
    body: str,
    to_recipients: Sequence[Union[str, EmailRecipient]],
    *,
    cc_recipients: Optional[Sequence[Union[str, EmailRecipient]]] = None,
    bcc_recipients: Optional[Sequence[Union[str, EmailRecipient]]] = None,
    body_type: str = "HTML",
    reply_to: Optional[Sequence[Union[str, EmailRecipient]]] = None,
    attachments: Optional[Sequence[EmailAttachment]] = None,
    importance: Optional[str] = None,
    kind: str = "other",
) -> None:
    """
    Sends email as a specific user using application permissions (client credentials).
    Requires: application Mail.Send + admin consent.
    Endpoint: POST /users/{id|upn}/sendMail
    """
    token_result = acquire_app_token()
    access_token = token_result.get("access_token")
    if not access_token:
        raise RuntimeError("App token result has no access_token")

    payload = build_message_payload(
        subject=_dev_prefix(subject),
        body=body,
        to_recipients=to_recipients,
        cc_recipients=cc_recipients,
        bcc_recipients=bcc_recipients,
        body_type=body_type,
        reply_to=reply_to,
        attachments=attachments,
        importance=importance,
    )
    url = f"{GRAPH_BASE_URL}/users/{sender_upn_or_id}/sendMail"
    _post_sendmail(url, access_token, payload, kind=kind)


def send_test_mail(to: str):
    send_mail_app_only(
        sender_upn_or_id="alpharequest@alpha-it-innovations.org",
        subject="AlphaRequest Testmail",
        kind="test",
        body=render_corporate_email(
            subject="AlphaRequest Testmail",
            headline="AlphaRequest (hier klicken)",
            intro="Hallo,\n\n das hier ist eine Testmail vom AlphaRequest System\n",
            info_box_url=config.FRONTEND_URL + "/dashboard",
            content="",
        ),
        to_recipients=[to],
        body_type="HTML",
        attachments=[a for a in [brand_logo_attachment()] if a],
    )


def send_personalnummer_warning_mail(company_name: str, remaining: int, pnr_to: int) -> None:
    """Warnt TICKET_MAIL, wenn der Personalnummern-Bereich einer Firma zur Neige geht."""
    to = getattr(config, "TICKET_MAIL", "") or ""
    if not to:
        logger.warning("Keine TICKET_MAIL konfiguriert – Personalnummern-Warnung nicht versendet")
        return
    send_mail_app_only(
        sender_upn_or_id="alpharequest@alpha-it-innovations.org",
        subject=f"⚠️ Personalnummern für {company_name} gehen zur Neige",
        kind="personalnummer_warning",
        body=render_corporate_email(
            subject=f"Personalnummern-Bereich {company_name} fast erschöpft",
            headline="AlphaRequest – Einstellungen öffnen",
            intro=(
                f"Achtung: Für die Firma „{company_name}“ sind nur noch {remaining} "
                f"Personalnummer(n) frei (der Bereich endet bei {pnr_to}).\n\n"
                "Bitte den Bereich rechtzeitig unter Einstellungen → Firmen erweitern – "
                "sonst können bald keine Onboarding-Aufträge mehr für diese Firma erstellt werden."
            ),
            info_box_url=config.FRONTEND_URL + "/settings",
            info_rows=[("Firma", company_name), ("Noch frei", str(remaining)), ("Bereichsende", str(pnr_to))],
            content="",
        ),
        to_recipients=[to],
        body_type="HTML",
        attachments=[a for a in [brand_logo_attachment()] if a],
    )
