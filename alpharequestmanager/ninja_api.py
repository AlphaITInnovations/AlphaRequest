# ninja_api.py
from __future__ import annotations

import json
import time
import urllib.parse
from datetime import datetime
from typing import Optional

import requests

from alpharequestmanager.config import config
from alpharequestmanager.logger import logger
import alpharequestmanager.database as db
from alpharequestmanager.ninja_render import render_ticket_description

# =========================
# Konfiguration
# =========================
CLIENT_ID = config.NINJA_CLIENT_ID
CLIENT_SECRET = config.NINJA_CLIENT_SECRET
REDIRECT_URI = config.NINJA_REDIRECT_URI

AUTH_BASE = "https://eu.ninjarmm.com/ws/oauth/authorize"
TOKEN_URL = "https://eu.ninjarmm.com/ws/oauth/token"
API_BASE = "https://eu.ninjarmm.com"

SCOPES = ["monitoring", "management", "control", "offline_access"]

HTTP_TIMEOUT = 30


class NinjaAuthFlowRequired(Exception):
    """Wird geworfen, wenn ein neuer OAuth-Flow erforderlich ist (z. B. kein/abgelaufenes Token),
    der aber *nicht* automatisch vom Backend gestartet werden darf.
    Admins starten den Flow im Frontend (Settings) und schließen ihn über den Callback."""
    pass


# =========================
# Token Management (persistiert in DB)
# =========================
def save_token(token_info: dict) -> None:
    """Speichert Token-Response + berechnetes expires_at."""
    token = dict(token_info or {})
    # expires_at aus expires_in ableiten, wenn vorhanden
    if token.get("expires_in"):
        token["expires_at"] = int(time.time()) + int(token.get("expires_in", 0))
    # Optional: Leere Strings auf None vereinheitlichen
    if token.get("refresh_token") == "":
        token["refresh_token"] = None
    # in DB persistieren
    try:
        db.set_ninja_token(token)
    except Exception:
        logger.exception("Konnte Ninja-Token nicht persistieren")
        raise


def load_token() -> Optional[dict]:
    """Lädt das Token primär aus der DB; fällt (optional) auf config zurück."""
    try:
        tok = db.get_ninja_token()
        if tok:
            return tok
    except Exception:
        logger.exception("Konnte Ninja-Token nicht laden (DB)")

    # Fallback, falls du temporär noch über ENV arbeitest
    return getattr(config, "NINJA_TOKEN", None)


def build_auth_url(state: str) -> str:
    """Erzeugt die OAuth-Autorisierungs-URL. Wird vom FastAPI-Endpoint /api/admin/ninja/start-auth genutzt."""
    qs = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(SCOPES),
        "state": state,
    })
    return f"{AUTH_BASE}?{qs}"


def exchange_code_for_token(code: str) -> dict:
    """Tauscht den Authorization Code gegen Tokens (Access/Refresh) und speichert sie."""
    data = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }
    resp = requests.post(TOKEN_URL, data=data, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    token_info = resp.json()
    save_token(token_info)
    logger.info("Ninja OAuth: Code gegen Token getauscht (Access + ggf. Refresh).")
    return token_info


def refresh_token(refresh_token_value: str) -> dict:
    """Erneuert das Access-Token mittels Refresh-Token und speichert das Ergebnis."""
    data = {
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": refresh_token_value,
    }
    resp = requests.post(TOKEN_URL, data=data, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    token_info = resp.json()
    save_token(token_info)
    logger.info("Ninja OAuth: Access Token via Refresh erneuert.")
    return token_info


def get_valid_token(allow_new_flow: bool = False) -> dict:
    """Liefert ein gültiges Token oder wirft NinjaAuthFlowRequired.
    Wichtig: startet *keinen* interaktiven Flow mehr. Das macht der Admin via Frontend.
    """
    token_info = load_token()
    now = time.time()

    if token_info:
        # Gültig?
        if token_info.get("expires_at") and now < float(token_info["expires_at"]):
            return token_info

        # Refresh versuchen, wenn möglich
        rtok = token_info.get("refresh_token")
        if rtok:
            try:
                return refresh_token(rtok)
            except Exception:
                logger.exception("Ninja OAuth: Refresh fehlgeschlagen")

    # Hier KEIN automatischer Flow mehr – nur signalisieren:
    # allow_new_flow=True heißt: der Aufrufer DARF den Flow starten (z. B. Admin-Route).
    # Den Start übernimmt aber dein FastAPI-Endpoint /api/admin/ninja/start-auth.
    raise NinjaAuthFlowRequired(
        "Ninja OAuth erfordert neuen Auth-Flow. Bitte als Admin in den Settings starten."
    )


def get_access_token(is_admin: bool = False) -> str:
    """Public API für Aufrufer: sorgt für gültiges Access-Token oder wirft NinjaAuthFlowRequired."""
    # is_admin wird hier nur genutzt, falls du später verschiedenes Verhalten willst;
    # der Flow wird aber grundsätzlich nicht mehr von hier gestartet.
    tok = get_valid_token(allow_new_flow=is_admin)
    return tok["access_token"]


# =========================
# Low-Level API Helper
# =========================
def _api_request(method: str, endpoint: str, access_token: Optional[str] = None, **kwargs):
    """Allgemeiner Request-Wrapper mit Fehlerausgabe."""
    url = f"{API_BASE}{endpoint}"
    headers = kwargs.pop("headers", {}) or {}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    # sinnvolle Defaults
    kwargs.setdefault("timeout", HTTP_TIMEOUT)

    resp = requests.request(method, url, headers=headers, **kwargs)
    if resp.status_code >= 400:
        logger.error("Fehler bei %s %s: %s %s", method, url, resp.status_code, resp.text)
        resp.raise_for_status()
    if resp.text and resp.text.strip():
        # Manche Endpunkte liefern leeren Body bei 204
        try:
            return resp.json()
        except Exception:
            return resp.text
    return None


# =========================
# Health / Test
# =========================
def test_connection(is_admin: bool = False) -> bool:
    """Testet die Verbindung über den Organizations-Endpoint."""
    try:
        access_token = get_access_token(is_admin=is_admin)
        _ = _api_request("GET", "/api/v2/organizations", access_token)
        logger.info("✅ Ninja API-Verbindung erfolgreich")
        return True
    except NinjaAuthFlowRequired:
        # durchreichen – der Aufrufer (FastAPI) kann eine freundliche Meldung zeigen
        raise
    except Exception as e:
        logger.error("❌ Ninja API-Verbindung fehlgeschlagen: %s", e)
        return False


# =========================
# Tickets
# =========================
def __create_ticket(access_token: str, ticket_data: dict):
    url = f"{API_BASE}/api/v2/ticketing/ticket"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    resp = requests.post(url, headers=headers, json=ticket_data, timeout=HTTP_TIMEOUT)
    if resp.status_code >= 400:
        logger.error("Fehler beim Ticket erstellen: %s %s", resp.status_code, resp.text)
        resp.raise_for_status()
    return resp.json()


def get_ticket(ticket_id: int, is_admin: bool = False):
    """Holt ein einzelnes Ticket per Ticket-ID."""
    access_token = get_access_token(is_admin=is_admin)
    url = f"{API_BASE}/api/v2/ticketing/ticket/{ticket_id}"
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    resp = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
    if resp.status_code >= 400:
        logger.error("Fehler beim Abrufen des Tickets: %s %s", resp.status_code, resp.text)
        resp.raise_for_status()
    return resp.json()


def update_ticket(access_token: str, ticket_id: int, update_data: dict):
    """Aktualisiert ein Ticket in NinjaOne."""
    url = f"{API_BASE}/api/v2/ticketing/ticket/{ticket_id}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    resp = requests.put(url, headers=headers, json=update_data, timeout=HTTP_TIMEOUT)
    if resp.status_code >= 400:
        logger.error("Fehler beim Ticket-Update: %s %s", resp.status_code, resp.text)
        resp.raise_for_status()
    return resp.json()


def add_ticket_comment(access_token: str, ticket_id: int, body: str, public: bool = True, html_body: Optional[str] = None):
    """Fügt einem Ticket einen Kommentar hinzu (ohne Dateien)."""
    url = f"{API_BASE}/api/v2/ticketing/ticket/{ticket_id}/comment"
    headers = {"Authorization": f"Bearer {access_token}"}

    comment_obj = {"public": public, "body": body, "htmlBody": html_body or f"<p>{body}</p>"}
    multipart_data = {"comment": (None, json.dumps(comment_obj), "application/json")}

    resp = requests.post(url, headers=headers, files=multipart_data, timeout=HTTP_TIMEOUT)
    if resp.status_code >= 400:
        logger.error("Fehler beim Hinzufügen des Kommentars: %s %s", resp.status_code, resp.text)
        resp.raise_for_status()

    if resp.text and resp.text.strip():
        try:
            return resp.json()
        except Exception:
            return {"status": resp.status_code, "message": resp.text}
    return {"status": resp.status_code, "message": "Kommentar erfolgreich hinzugefügt"}


def create_ticket(
    client_id: int,
    form_id: int,
    subject: str,
    description: str | dict,
    requester_mail: Optional[str] = None,
    attributes: Optional[list[dict[str, object]]] = None,
    status: int = 1000,
    is_admin: bool = False,
):
    access_token = get_access_token(is_admin=is_admin)

    requester_uid = None
    if requester_mail:
        requester_uid = find_requester_uid_by_email(access_token, requester_mail)

    ticket: dict[str, object] = {
        "clientId": client_id,
        "ticketFormId": form_id,
        "subject": subject,
        "status": status,
    }
    print(description)
    rendered, overflow_html = render_ticket_description(form_id, description)
    ticket["description"] = rendered

    if requester_uid:
        ticket["requesterUid"] = requester_uid
    if attributes:
        ticket["attributes"] = attributes

    return __create_ticket(access_token, ticket)


def create_ticket_edv_beantragen(
    client_id=2,
    description="",
    requester_mail=None,
    vorname="",
    nachname="",
    firma="AlphaConsult KG",
    arbeitsbeginn=None,
    titel="",
    strasse="",
    ort="",
    plz="",
    handy="",
    telefon="",
    fax="",
    niederlassung="",
    kostenstelle="",
    kommentar="",
    checkbox_datev_user=False,
    checkbox_elo_user=False,
    is_admin: bool = False,
):
    if not requester_mail:
        raise ValueError("❌ requester_mail ist Pflicht!")
    if not vorname or not nachname:
        raise ValueError("❌ Vorname und Nachname sind Pflicht!")
    if not firma:
        raise ValueError("❌ Firma ist Pflicht!")

    # Arbeitsbeginn → Unix-TS
    arbeitsbeginn_val = None
    if isinstance(arbeitsbeginn, datetime):
        arbeitsbeginn_val = int(arbeitsbeginn.timestamp())
    elif isinstance(arbeitsbeginn, int):
        arbeitsbeginn_val = arbeitsbeginn

    attributes: list[dict[str, object]] = []

    def add_attr(attr_id: int, value: object):
        if value not in (None, "", []):
            attributes.append({"attributeId": attr_id, "value": value})

    add_attr(203, vorname)
    add_attr(204, nachname)
    add_attr(205, firma)
    add_attr(206, arbeitsbeginn_val)
    add_attr(207, titel)
    add_attr(216, strasse)
    add_attr(209, ort)
    add_attr(210, plz)
    add_attr(211, handy)
    add_attr(212, telefon)
    add_attr(213, fax)
    add_attr(214, niederlassung)
    add_attr(215, kostenstelle)
    add_attr(202, kommentar)
    add_attr(217, checkbox_datev_user)
    add_attr(225, checkbox_elo_user)

    payload = {
        "client_id": client_id,
        "form_id": 9,  # ID für EDV-Zugang beantragen
        "subject": "EDV-Zugang beantragen",
        "description": description,
        "requester_mail": requester_mail,
        "attributes": attributes,
    }

    logger.info("🎟️ Ticket-Payload an NinjaOne:\n%s", json.dumps(payload, indent=2, ensure_ascii=False))
    return create_ticket(**payload, is_admin=is_admin)


def create_ticket_hardware(client_id=2, description="", requester_mail=None, is_admin: bool = False):
    return create_ticket(
        client_id=client_id,
        form_id=10,
        subject="Neue Hardwarebestellung",
        description=description,
        requester_mail=requester_mail,
        is_admin=is_admin,
    )


def create_ticket_edv_sperren(client_id=2, description="", requester_mail=None, is_admin: bool = False):
    return create_ticket(
        client_id=client_id,
        form_id=8,
        subject="EDV Zugang sperren",
        description=description,
        requester_mail=requester_mail,
        is_admin=is_admin,
    )


def create_ticket_niederlassung_anmelden(client_id=2, description="", requester_mail=None, is_admin: bool = False):
    return create_ticket(
        client_id=client_id,
        form_id=11,
        subject="Niederlassung anmelden",
        description=description,
        requester_mail=requester_mail,
        is_admin=is_admin,
    )


def create_ticket_niederlassung_umziehen(client_id=2, description="", requester_mail=None, is_admin: bool = False):
    return create_ticket(
        client_id=client_id,
        form_id=12,
        subject="Niederlassung umziehen",
        description=description,
        requester_mail=requester_mail,
        is_admin=is_admin,
    )


def create_ticket_niederlassung_schließen(client_id=2, description="", requester_mail=None, is_admin: bool = False):
    return create_ticket(
        client_id=client_id,
        form_id=13,
        subject="Niederlassung schließen",
        description=description,
        requester_mail=requester_mail,
        is_admin=is_admin,
    )


# =========================
# Sonstige Helfer
# =========================
def is_alpha_request_approved(ticket_id: int) -> bool | None:
    """Prüft im Ticket-Log, ob Attribut 201 (= AlphaRequest Status) zuletzt 'Erledigt✅' oder 'Abgelehnt ❌' war."""
    access_token = get_access_token()
    # KORREKTER Pfad enthält /api/
    entries = _api_request(
        "GET",
        f"/api/v2/ticketing/ticket/{ticket_id}/log-entry?pageSize=50",
        access_token,
    ) or []

    # neuesten Eintrag mit Attribut-Änderung suchen
    for entry in sorted(entries, key=lambda e: e.get("createTime", 0), reverse=True):
        attrs = (entry.get("changeDiff", {}) or {}).get("attributeValues", []) or []
        if not attrs:
            continue
        for attr in attrs:
            # je nach API-Form kann attributeId int oder Objekt sein
            attr_id = attr.get("attributeId")
            if isinstance(attr_id, dict):
                attr_id = attr_id.get("id")
            if attr_id == 201:
                new_val = (attr.get("new") or "") if isinstance(attr.get("new"), str) else str(attr.get("new") or "")
                if "Erledigt" in new_val:
                    return True
                if "Abgelehnt" in new_val:
                    return False
                return None
    return None


def find_requester_uid_by_email(access_token: str, email: str) -> Optional[str]:
    url = f"{API_BASE}/api/v2/users"
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    users = resp.json() or []
    email_l = (email or "").lower()
    for u in users:
        if (u.get("email") or "").lower() == email_l:
            return u.get("uid")
    return None


def get_alpha_request_comment(ticket: dict) -> Optional[str]:
    """Holt den Wert des Attributs 'AlphaRequest Kommentar' (id=202) aus einem Ninja-Ticket."""
    for attr in ticket.get("attributeValues", []) or []:
        # je nach Darstellung int oder obj
        aid = attr.get("attributeId")
        if isinstance(aid, dict):
            aid = aid.get("id")
        if aid == 202:
            return attr.get("value")
    return None
