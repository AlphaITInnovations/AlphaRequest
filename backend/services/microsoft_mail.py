# backend/microsoft_mail.py

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Union, Set
import base64
import mimetypes
import os

import requests
from fastapi import Request, Path

from backend.database.groups import get_groups
from backend.models.models import TicketPriority, TicketType, Ticket
from backend.services.microsoft_auth import acquire_app_token
from backend.utils.config import Config
from backend.utils.logger import logger
from backend.utils.mail_templates import render_corporate_email
from backend.utils.config import config
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"


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


def _post_sendmail(url: str, access_token: str, payload: Dict[str, Any], timeout_s: int = 30) -> None:
    resp = requests.post(url, headers=_auth_header(access_token), json=payload, timeout=timeout_s)
    if resp.status_code >= 400:
        # Graph error responses are usually JSON with "error": {"code","message",...}
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text

        raise GraphMailError(
            f"Graph sendMail failed: HTTP {resp.status_code} - {detail}"
        )


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
) -> None:
    """
    Sends email as the signed-in user (delegated permission).
    Requires: delegated Mail.Send
    Endpoint: POST /me/sendMail
    """
    payload = build_message_payload(
        subject=subject,
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
    _post_sendmail(url, access_token, payload)


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
        subject=subject,
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
    _post_sendmail(url, access_token, payload)


def send_test_mail(to: str):
    send_mail_app_only(
        sender_upn_or_id="alpharequest@alpha-it-innovations.org",
        subject="AlphaRequest Testmail",
        body=render_corporate_email(
            subject="AlphaRequest Testmail",
            headline="AlphaRequest (hier klicken)",
            intro="Hallo,\n\n das hier ist eine Testmail vom AlphaRequest System\n",
            info_box_url=config.FRONTEND_URL + "/dashboard",
            content="",
        ),
        to_recipients=[to],
        body_type="HTML",
        attachments=[inline_attachment_from_path("static/logo.png", content_id="alpha_logo")],
    )

def send_newrequest_mail(to: str, prio: TicketPriority, titel: str, ttype: TicketType, ticketid):

    ticket_type_labels = {
        TicketType.hardware: "Hardware Bestellung",
        TicketType.niederlassung_anmelden: "Onboarding Niederlassung",
        TicketType.niederlassung_schliessen: "Offboarding Niederlassung",
        TicketType.niederlassung_umzug: "Umzug Niederlassung",
        TicketType.zugang_beantragen: "Onboarding Mitarbeiter:innen",
        TicketType.zugang_sperren: "Offboarding Mitarbeiter:innen",
    }

    priority_labels = {
        TicketPriority.low: "Niedrig",
        TicketPriority.medium: "Mittel",
        TicketPriority.high: "Hoch",
        TicketPriority.critical: "Kritisch",
    }

    readable_type = ticket_type_labels.get(ttype, ttype.value)
    readable_prio = priority_labels.get(prio, prio.value)

    send_mail_app_only(
        sender_upn_or_id="alpharequest@alpha-it-innovations.org",
        subject=f"Neuer Auftrag #{ticketid} in AlphaRequest",
        body=render_corporate_email(
            subject=titel,
            headline="AlphaRequest (hier klicken)",
            intro=(
                f"Hallo,\n\n"
                f"Ihnen wurde ein neuer Auftrag „{readable_type}“ "
                f"mit der Priorität „{readable_prio}“ zugewiesen.\n\n"
                f"Bitte prüfen Sie die Details im System und übernehmen Sie die weitere Bearbeitung."
            ),
            info_box_url=config.FRONTEND_URL + "/dashboard",

            content="",
        ),
        to_recipients=[to],
        body_type="HTML",
        attachments=[inline_attachment_from_path("static/logo.png", content_id="alpha_logo")],
    )

def send_mail_to_fachabteilung(to: str, prio: TicketPriority, titel: str, ttype: TicketType, ticketid):
    ticket_type_labels = {
        TicketType.hardware: "Hardware Bestellung",
        TicketType.niederlassung_anmelden: "Onboarding Niederlassung",
        TicketType.niederlassung_schliessen: "Offboarding Niederlassung",
        TicketType.niederlassung_umzug: "Umzug Niederlassung",
        TicketType.zugang_beantragen: "Onboarding Mitarbeiter:innen",
        TicketType.zugang_sperren: "Offboarding Mitarbeiter:innen",
    }

    priority_labels = {
        TicketPriority.low: "Niedrig",
        TicketPriority.medium: "Mittel",
        TicketPriority.high: "Hoch",
        TicketPriority.critical: "Kritisch",
    }

    readable_type = ticket_type_labels.get(ttype, ttype.value)
    readable_prio = priority_labels.get(prio, prio.value)
    send_mail_app_only(
        sender_upn_or_id="alpharequest@alpha-it-innovations.org",
        subject=f"Neuer Fachabteilungsauftrag #{ticketid} in AlphaRequest",
        body=render_corporate_email(
            subject=titel,
            headline="AlphaRequest (hier klicken)",
            intro=(
                f"Hallo,\n\n"
                f"Ihrer Fachabteilung wurde ein neuer Auftrag „{readable_type}“ "
                f"mit der Priorität „{readable_prio}“ zugewiesen.\n\n"
                f"Bitte prüfen Sie die Details im System und übernehmen Sie die weitere Bearbeitung."
            ),
            info_box_url=config.FRONTEND_URL + "dashboard",
            content="",
        ),
        to_recipients=[to],
        body_type="HTML",
        attachments=[inline_attachment_from_path("static/logo.png", content_id="alpha_logo")],
    )



def send_mail_to_all_fachabteilung(workflow: dict, ticket: Ticket):
    """
    Sammelt alle Verteiler-Mailadressen der betroffenen
    Fachabteilungen und sendet eine Mail.
    """

    if not workflow or "departments" not in workflow:
        logger.warning("Workflow enthält keine Departments")
        return

    department_ids = workflow["departments"].keys()

    groups = get_groups()

    # Alle Verteiler sammeln (unique)
    recipients: Set[str] = set()

    for group in groups:
        if group.get("id") in department_ids:
            distributions = group.get("distributions", [])
            if isinstance(distributions, list):
                for mail in distributions:
                    if mail:
                        recipients.add(mail.strip().lower())

    if not recipients:
        logger.warning(
            "Keine Verteiler-Mailadressen für Ticket %s gefunden",
            ticket.id,
        )
        return

    logger.info(
        "Sende Ticket %s an Verteiler: %s",
        ticket.id,
        list(recipients),
    )

    for mail in recipients:
        send_mail_to_fachabteilung(
            to=mail,
            prio=ticket.priority,
            titel=ticket.title,
            ttype=ticket.ticket_type,
            ticketid=ticket.id,
        )