# alpharequestmanager/microsoft_mail.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Union
import base64
import mimetypes
import os

import requests
from fastapi import Request

from alpharequestmanager.services.microsoft_auth import acquire_app_token
from alpharequestmanager.services.mail_templates import render_corporate_email
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
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    fname = filename or os.path.basename(path)
    ctype, _ = mimetypes.guess_type(path)
    ctype = ctype or "application/octet-stream"

    with open(path, "rb") as f:
        raw = f.read()

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



send_mail_app_only(
    sender_upn_or_id="alpharequest@alpha-it-innovations.org",
    subject="AlphaRequest Auftrags Update",
    body=render_corporate_email(
        subject="AlphaRequest Auftrags Update",
        headline="Auftrag #52135 (hier klicken)",
        intro="Hallo Marco,\n\n einer deiner Aufträge wurde geupdatet.\n",
        info_box_url="https://alpharequest.dom.local/dashboard",
        content="• Feld1: Platzhalter\n• Feld2: Platzhalter\n",
    ),
    to_recipients=["marco.schneider@alpha-it-innovations.org"],
    body_type="HTML",
    attachments=[inline_attachment_from_path("../static/logo.png", content_id="alpha_logo")],
)
