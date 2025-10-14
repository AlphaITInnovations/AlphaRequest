import http.server
import socketserver
import webbrowser
from typing import Optional
import requests
import urllib.parse
import threading
import json
from alpharequestmanager.config import config
import time
from datetime import datetime
from alpharequestmanager.logger import logger
import alpharequestmanager.database as db


# =========================
# Konfiguration
# =========================
CLIENT_ID = config.NINJA_CLIENT_ID
CLIENT_SECRET = config.NINJA_CLIENT_SECRET
REDIRECT_URI = config.NINJA_REDIRECT_URI
AUTH_URL = f"https://eu.ninjarmm.com/ws/oauth/authorize?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&scope=monitoring%20management%20control%20offline_access&state=STATE"
TOKEN_URL = "https://eu.ninjarmm.com/ws/oauth/token"


class NinjaAuthFlowRequired(Exception):
    """Wird geworfen, wenn kein gültiges Token vorhanden ist und ein neuer Auth-Flow
    notwendig wäre – aber der aktuelle Benutzer kein Admin ist (oder unbekannt)."""
    pass

# =========================
# Funktion: Auth Code holen
# =========================
def get_auth_code():
    auth_code = None

    class OAuthHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal auth_code
            query = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(query)

            if "code" in params:
                auth_code = params["code"][0]
                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<h1>NinjaOne Authorization Code</h1><p>Code empfangen. Fenster kann geschlossen werden.</p>"
                )
                threading.Thread(target=httpd.shutdown, daemon=True).start()
            else:
                self.send_response(400)
                self.end_headers()

    with socketserver.TCPServer(("localhost", 9090), OAuthHandler) as httpd:
        print(f"Starte Browser: {AUTH_URL}")
        webbrowser.open(AUTH_URL)
        httpd.serve_forever()

    if not auth_code:
        raise Exception("Kein Authorization Code erhalten!")

    return auth_code



# =========================
# Token Management
# =========================
def save_token(token_info):
    token_info["expires_at"] = int(time.time()) + int(token_info.get("expires_in", 0))
    db.set_ninja_token(token_info)

def load_token():
    return config.NINJA_TOKEN

def get_new_token():
    code = get_auth_code()
    data = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }
    resp = requests.post(TOKEN_URL, data=data)
    resp.raise_for_status()
    token_info = resp.json()
    save_token(token_info)
    return token_info

def refresh_token(refresh_token_value):
    data = {
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": refresh_token_value,
    }
    resp = requests.post(TOKEN_URL, data=data)
    resp.raise_for_status()
    token_info = resp.json()
    save_token(token_info)
    print("Access Token refresh erfolgreich")
    return token_info

# get_valid_token anpassen: steuert, ob ein neuer Flow überhaupt gestartet werden darf
def get_valid_token(allow_new_flow: bool = False):
    token_info = load_token()
    if token_info:
        # Gültig?
        if "expires_at" in token_info and time.time() < token_info["expires_at"]:
            return token_info
        # Refresh versuchen
        if "refresh_token" in token_info:
            try:
                print("Access Token abgelaufen – versuche Refresh...")
                return refresh_token(token_info["refresh_token"])
            except Exception as e:
                print("Refresh fehlgeschlagen:", e)

    if allow_new_flow:
        print("Kein gültiges Token – starte neuen Auth Flow (erlaubt)...")
        return get_new_token()
    # Kein neuer Flow erlaubt -> signalisiere dem Aufrufer
    raise NinjaAuthFlowRequired("NinjaOne OAuth erfordert einen neuen Auth-Flow (nur Admin erlaubt)")



def get_access_token(is_admin: bool = False):
    """
    Liefert gültiges Access-Token.
    - is_admin=True  → darf neuen Flow starten
    - is_admin=False → wirft NinjaAuthFlowRequired, wenn kein Refresh möglich
    """
    token_info = get_valid_token(allow_new_flow=is_admin)
    return token_info["access_token"]

#API Request
def _api_request(method: str, endpoint: str, access_token: str = None, **kwargs):
    url = f"https://eu.ninjarmm.com{endpoint}"
    headers = kwargs.pop("headers", {})
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    resp = requests.request(method, url, headers=headers, **kwargs)
    if resp.status_code >= 400:
        print(f"Fehler bei {method} {url}: {resp.status_code} {resp.text}")
        resp.raise_for_status()
    if resp.text.strip():
        return resp.json()
    return None



def test_connection(is_admin: bool = False):
    """
    Testet die Verbindung zur NinjaOne API über den Organizations-Endpoint.
    """
    try:
        access_token = get_access_token(is_admin=is_admin)

        orgs = _api_request("GET", "/api/v2/organizations", access_token)
        logger.info("✅ API-Verbindung erfolgreich")
        return True
    except Exception as e:
        logger.error(f"❌ API-Verbindung fehlgeschlagen: {e}")
        return False




# =========================
# Funktion: Ticket erstellen
# =========================
def __create_ticket(access_token, ticket_data):
    url = "https://eu.ninjarmm.com/api/v2/ticketing/ticket"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    resp = requests.post(url, headers=headers, json=ticket_data)
    if resp.status_code >= 400:
        print("Fehler beim Ticket erstellen:", resp.status_code, resp.text)
        resp.raise_for_status()
    return resp.json()

def get_ticket(ticket_id, is_admin: bool = False):
    access_token = get_access_token(is_admin=is_admin)
    """
    Holt ein einzelnes Ticket aus NinjaOne per Ticket-ID.
    """
    url = f"https://eu.ninjarmm.com/api/v2/ticketing/ticket/{ticket_id}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }

    resp = requests.get(url, headers=headers)
    if resp.status_code >= 400:
        print("Fehler beim Abrufen des Tickets:", resp.status_code, resp.text)
        resp.raise_for_status()
    return resp.json()

def update_ticket(access_token, ticket_id, update_data):
    """
    Aktualisiert ein Ticket in NinjaOne.
    :param access_token: gültiges Bearer Token
    :param ticket_id: ID des Tickets
    :param update_data: dict mit den Feldern, die aktualisiert werden sollen
    """
    url = f"https://eu.ninjarmm.com/api/v2/ticketing/ticket/{ticket_id}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    resp = requests.put(url, headers=headers, json=update_data)
    if resp.status_code >= 400:
        print("Fehler beim Ticket-Update:", resp.status_code, resp.text)
        resp.raise_for_status()
    return resp.json()

def add_ticket_comment(access_token, ticket_id, body, public=True, html_body=None):
    """
    Fügt einem Ticket einen Kommentar hinzu (ohne Dateien).
    Gibt JSON zurück, falls vorhanden – ansonsten None.
    """
    url = f"https://eu.ninjarmm.com/api/v2/ticketing/ticket/{ticket_id}/comment"
    headers = {"Authorization": f"Bearer {access_token}"}

    comment_obj = {
        "public": public,
        "body": body,
        "htmlBody": html_body or f"<p>{body}</p>"
    }

    multipart_data = {
        "comment": (None, json.dumps(comment_obj), "application/json")
    }

    resp = requests.post(url, headers=headers, files=multipart_data)

    if resp.status_code >= 400:
        print("Fehler beim Hinzufügen des Kommentars:", resp.status_code, resp.text)
        resp.raise_for_status()

    # Manche Endpoints geben keinen JSON-Body zurück
    if resp.text.strip():
        return resp.json()
    else:
        return {"status": resp.status_code, "message": "Kommentar erfolgreich hinzugefügt"}


def create_ticket(
    client_id: int,
    form_id: int,
    subject: str,
    description: str | dict,   # <- hier auch dict erlauben
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

    # Falls description schon ein dict ist (mit body/htmlBody), direkt übernehmen
    if isinstance(description, dict):
        ticket["description"] = description
    else:
        ticket["description"] = {
            "public": True,
            "body": description,
            "htmlBody": f"<p>{description}</p>"
        }

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
    arbeitsbeginn=None,   # datetime oder int (Timestamp)
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
    # --- Pflichtfeld-Prüfung ---
    if not requester_mail:
        raise ValueError("❌ requester_mail ist Pflicht!")
    if not vorname or not nachname:
        raise ValueError("❌ Vorname und Nachname sind Pflicht!")
    if not firma:
        raise ValueError("❌ Firma ist Pflicht!")

    # --- Arbeitsbeginn vorbereiten ---
    arbeitsbeginn_val = None
    if isinstance(arbeitsbeginn, datetime):
        arbeitsbeginn_val = int(time.mktime(arbeitsbeginn.timetuple()))
    elif isinstance(arbeitsbeginn, int):
        arbeitsbeginn_val = arbeitsbeginn

    # --- Attribute nur setzen, wenn Wert nicht leer ist ---
    attributes = []

    def add_attr(attr_id, value):
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



    # --- Payload für Logging ---
    payload = {
        "client_id": client_id,
        "form_id": 9,  # ID für EDV-Zugang beantragen
        "subject": "EDV-Zugang beantragen",
        "description": description,
        "requester_mail": requester_mail,
        "attributes": attributes,
    }

    logger.info("🎟️ Ticket-Payload an NinjaOne:\n%s", json.dumps(payload, indent=2, ensure_ascii=False))

    # --- Ticket erstellen ---
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


def is_alpha_request_approved(ticket_id: int) -> bool | None:
    """
    Prüft im Ticket-Log, ob das Attribut 'AlphaRequest Status' zuletzt
    auf 'Erledigt✅' oder 'Abgelehnt ❌' gesetzt wurde.
    """
    access_token = get_access_token()
    entries = _api_request(
        "GET",
        f"/v2/ticketing/ticket/{ticket_id}/log-entry?pageSize=50",
        access_token
    )
    if not entries:
        return None

    # neuesten Eintrag mit Attribut-Änderung suchen
    for entry in sorted(entries, key=lambda e: e.get("createTime", 0), reverse=True):
        attrs = entry.get("changeDiff", {}).get("attributeValues", [])
        if not attrs:
            continue

        # Nur Attribute mit ID 201 (= AlphaRequest Status)
        for attr in attrs:
            attr_id = attr.get("attributeId", {}).get("id")
            if attr_id == 201:
                new_val = attr.get("new", "")
                if "Erledigt" in new_val:
                    return True
                if "Abgelehnt" in new_val:
                    return False
                return None

    return None




def find_requester_uid_by_email(access_token, email):
    url = "https://eu.ninjarmm.com/api/v2/users"  # oder contacts
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    users = resp.json()
    for u in users:
        if u.get("email", "").lower() == email.lower():
            return u["uid"]
    return None



def get_alpha_request_comment(ticket: dict) -> str | None:
    """
    Holt den Wert des Attributs 'AlphaRequest Kommentar' (id=202) aus einem Ninja-Ticket.
    """
    for attr in ticket.get("attributeValues", []):
        if attr.get("attributeId") == 202:   # int vergleichen!
            return attr.get("value")
    return None







