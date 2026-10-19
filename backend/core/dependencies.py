from typing import Dict, Optional
import time
from fastapi import Request, HTTPException, status
from backend.utils.config import config
from backend.utils.logger import logger
from backend.core.session import SERVER_BOOT_ID
from backend.database.users import get_user_permissions, PERM_ADMIN
from backend.database import sessions as session_store
from backend.services import directus_employee

SAFE_UPDATE_INTERVAL = 60  # seconds
#: Header für automatische Hintergrund-Abfragen (Live-Ansichten). Solche Requests
#: werden normal authentifiziert und unterliegen dem Timeout, VERLÄNGERN die
#: Session aber nicht – sonst hielte ein offener Live-Reiter eine Session auf
#: einem unbeaufsichtigten Rechner ewig am Leben.
BACKGROUND_POLL_HEADER = "x-background-poll"
# Präsenz-Drossel: `last_seen` höchstens alle 30 s pro Session schreiben.
PRESENCE_TOUCH_INTERVAL = 30  # seconds


def _check_session_store(request, session: dict) -> Optional[dict]:
    """Serverseitige Session prüfen (Force-Logout) und Präsenz auffrischen.

    Fail-open: Ein DB-Fehler loggt NIEMANDEN aus – dann greifen weiterhin
    Cookie + boot_id + Timeout. Nur ein tatsächlich fehlender Row (Admin hat
    force-abgemeldet) führt zu 401. Gibt die Session-Zeile zurück (oder None bei
    fehlender sid / fail-open), damit der Aufrufer das Login-Profil daraus nutzen
    kann – ohne zweite Abfrage.
    """
    sid = session.get("sid")
    if not sid:
        return None
    try:
        row = session_store.get_session(sid)
        if row is None:
            session.clear()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        if int(row.get("age_seconds") or 0) >= PRESENCE_TOUCH_INTERVAL:
            ip = request.client.host if request.client else None
            session_store.touch_session(sid, ip)
        return row
    except HTTPException:
        raise
    except Exception:
        logger.exception("Session-Store-Check fehlgeschlagen (sid=%s) – fail-open", sid)
        return None


#: Login-Daten, die serverseitig an der Session-Zeile liegen (nicht im Cookie).
LOGIN_PROFILE_KEYS = ("groups", "phone", "mobile", "company", "position", "address")


def _attach_login_profile(user: dict, row: Optional[dict]) -> None:
    """AD-Gruppen + Graph-Profil aus der Session-Zeile an die Request-Kopie hängen.
    Fehlt die Zeile (fail-open bei DB-Fehler), gibt es keine AD-Gruppen – Rechte,
    die NUR an einer AD-Gruppe hängen, greifen für diesen einen Request dann nicht
    (fail-closed); alles andere läuft normal."""
    profile = (row or {}).get("login_profile") or {}
    for key in LOGIN_PROFILE_KEYS:
        if key in profile:
            user[key] = profile[key]
    user.setdefault("groups", [])


def _is_background_poll(request) -> bool:
    """Automatische Hintergrund-Abfrage (zählt nicht als Nutzer-Aktivität)?"""
    headers = getattr(request, "headers", None) or {}
    return str(headers.get(BACKGROUND_POLL_HEADER, "")).strip() == "1"


def _is_admin(user: dict) -> bool:
    return PERM_ADMIN in (user.get("permissions") or [])


def enforce_employee_link(user: dict) -> None:
    """Hard Gate: ohne zugeordneten Directus-Mitarbeiter-Datensatz kein Arbeiten.

    Die Zuordnung läuft über die E-Mail (Azure `user["email"]`). Zu unterscheiden:
      1. kein Datensatz zur E-Mail → 403 (Konto ohne Stammdaten; bewusst hart).
      2. Directus nicht erreichbar/konfiguriert → 503, ABER Break-Glass: Admins und
         die ENV-Allowlist (`AUTH_BOOTSTRAP_EMAILS`) kommen trotzdem rein, damit ein
         Directus-Ausfall nicht alle (inkl. der Leute, die ihn beheben) aussperrt.

    Bei Erfolg wird der Datensatz als `user["employee"]` angehängt. Ist das Gate
    per `AUTH_REQUIRE_DIRECTUS_EMPLOYEE=false` abgeschaltet, wird der Datensatz nur
    best-effort angehängt, aber nie blockiert.
    """
    email = (user.get("email") or "").strip()
    require = config.AUTH_REQUIRE_DIRECTUS_EMPLOYEE
    bootstrap = email.lower() in config.AUTH_BOOTSTRAP_EMAILS

    try:
        rec = directus_employee.lookup_employee(email)
    except directus_employee.EmployeeLookupError:
        # Fall 2: Directus down/aus. Ohne Gate ignorieren; mit Gate nur Break-Glass.
        if not require or bootstrap or _is_admin(user):
            user["employee"] = None
            return
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "DIRECTUS_UNAVAILABLE",
                    "message": "Mitarbeiterdaten sind zurzeit nicht erreichbar. "
                               "Bitte später erneut versuchen."})

    if rec is None and require and not bootstrap:
        # Fall 1: Konto ohne Directus-Stammdaten – bewusst hart.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "NO_DIRECTUS_RECORD",
                    "message": "Zu Ihrem Konto wurde kein Mitarbeiter-Datensatz "
                               "gefunden. Bitte an die Administration wenden."})

    user["employee"] = rec


def get_current_user(request: Request) -> Dict:
    session = request.session
    stored_user = session.get("user")
    now = int(time.time())
    last_activity_raw = session.get("last_activity")

    if not stored_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    # Nach einem Server-Neustart sind alte Sessions ungültig (boot_id passt nicht mehr).
    if session.get("boot_id") != SERVER_BOOT_ID:
        session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    # Serverseitige Session prüfen (Force-Logout) + Präsenz auffrischen (fail-open).
    row = _check_session_store(request, session)

    # ARBEITSKOPIE: alles, was hier angereichert wird (frische Rechte, Directus-
    # Mitarbeiter-Datensatz, AD-Gruppen, Graph-Profil), gilt NUR für diesen Request.
    # Am Session-Dict selbst würde Starlette es bei JEDER Antwort ins (nur
    # signierte, nicht verschlüsselte) Cookie serialisieren – private Adresse/
    # Telefon im Browser und ein Cookie > 4 KB (nginx 502 / Browser verwirft es).
    user = dict(stored_user)
    _attach_login_profile(user, row)

    try:
        cookie_len = sum((len(k) + len(v)) for k, v in request.cookies.items())
    except Exception:
        cookie_len = -1

    # DEBUG statt INFO: sid ist der Schlüssel zum serverseitigen Token-Store und
    # soll nicht bei jedem Request in die regulären Logs geschrieben werden.
    logger.debug(
        "session_keys=%s sid=%s last=%s now=%s cookie_len=%s",
        list(session.keys()), session.get("sid"), last_activity_raw, now, cookie_len,
    )

    try:
        last_activity = int(last_activity_raw) if last_activity_raw is not None else 0
    except Exception:
        last_activity = 0

    if last_activity == 0:
        session["last_activity"] = now
        user["permissions"] = get_user_permissions(user["id"])
        enforce_employee_link(user)
        return user

    if now - last_activity > int(config.SESSION_TIMEOUT):
        sid = session.get("sid")
        try:
            if sid:
                session_store.delete_session(sid)
        except Exception:
            logger.exception("Session-Row für sid=%s nicht löschbar", sid)
        session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    if now - last_activity >= SAFE_UPDATE_INTERVAL and not _is_background_poll(request):
        session["last_activity"] = now

    # Permissions immer frisch aus der DB – nie aus der Session
    user["permissions"] = get_user_permissions(user["id"])
    enforce_employee_link(user)
    return user



def check_session_only(request: Request) -> Dict:
    """
    Prüft ob die Session noch gültig ist, OHNE last_activity zu aktualisieren.
    Wird vom Heartbeat-Endpoint verwendet, damit der Heartbeat die Session
    nicht künstlich am Leben hält.
    """
    session = request.session
    user = session.get("user")
    now = int(time.time())

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    if session.get("boot_id") != SERVER_BOOT_ID:
        session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    # Force-Logout auch im Heartbeat erkennen + Präsenz auffrischen (fail-open).
    _check_session_store(request, session)

    try:
        last_activity = int(session.get("last_activity") or 0)
    except Exception:
        last_activity = 0

    if last_activity == 0 or now - last_activity > int(config.SESSION_TIMEOUT):
        sid = session.get("sid")
        try:
            if sid:
                session_store.delete_session(sid)
        except Exception:
            logger.exception("Session-Row für sid=%s nicht löschbar", sid)
        session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    return user