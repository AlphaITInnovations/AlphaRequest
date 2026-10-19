import time
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool
from starlette import status
from starlette.status import HTTP_302_FOUND

from backend.core.dependencies import get_current_user, check_session_only
from backend.core.session import rotate_sid, SERVER_BOOT_ID
from backend.database.users import (
    upsert_user, get_user_permissions, get_user, set_group_admin, revoke_group_admin,
    PERM_ADMIN,
)
from backend.database.settings import get_maintenance
from backend.services.admin_sync import (
    decide_group_admin_action, ACTION_PROMOTE, ACTION_REVOKE,
)
from backend.metrics.auth_metrics import (
    record_login_attempt, record_login_success, record_login_failed,
)
from backend.schemas.responses import DataResponse
from backend.schemas.user import UserOut, ProfileOut
from backend.services.microsoft_auth import (
    initiate_auth_flow, acquire_token_by_auth_code,
)
from backend.services.microsoft_graph import get_user_profile
from backend.services import directus_employee
from backend.database.audit_log import record_audit
from backend.database.sessions import upsert_session, delete_session, get_session
from backend.utils.config import config
from backend.utils.logger import logger


def _client_ip(request: Request) -> str | None:
    try:
        return request.client.host if request.client else None
    except Exception:
        return None


def _employee_link_audit(email: str) -> tuple[str | None, dict]:
    """Status der Directus-Mitarbeiter-Zuordnung für den Login-Audit-Eintrag.

    Treffer → kein Sonder-Hinweis (details nur „zugeordnet"); KEIN Treffer oder
    Directus nicht erreichbar → sprechende `summary`, damit eine Anmeldung, die
    danach am Mitarbeiter-Gate (enforce_employee_link) scheitert, nicht als leerer
    „Login"-Eintrag ohne Grund dasteht. Die eigentliche Sperre bleibt im Gate (pro
    Request, bewusst ohne Audit – sonst Spam); hier genügt der eine Login-Eintrag.
    Wirft nie – der Audit darf den Login nicht kippen."""
    mail = (email or "").strip()
    if not mail:
        return ("Anmeldung ohne E-Mail – keine Directus-Zuordnung möglich",
                {"directus_employee": "keine_email"})
    try:
        rec = directus_employee.lookup_employee(mail)
    except directus_employee.EmployeeLookupError as e:
        return ("Directus-Zuordnung beim Login nicht prüfbar – Directus nicht "
                "erreichbar/konfiguriert (Break-Glass nur für Admins/Allowlist)",
                {"directus_employee": "fehler", "email": mail, "error": str(e)[:300]})
    except Exception as e:                      # defensiv: Audit darf den Login nie kippen
        logger.exception("Directus-Zuordnung beim Login-Audit fehlgeschlagen")
        return (None, {"directus_employee": "unbekannt", "email": mail, "error": str(e)[:300]})
    if rec is None:
        return (f"Kein Directus-Mitarbeiter-Datensatz zur E-Mail „{mail}“ – Konto kann erst "
                "arbeiten, wenn die E-Mail in alphacore korrekt hinterlegt ist",
                {"directus_employee": "kein_treffer", "email": mail})
    return (None, {"directus_employee": "zugeordnet"})

router = APIRouter()

# ── /auth/refresh-session ─────────────────────────────────────────────────────

@router.post("/auth/refresh-session", response_model=DataResponse[UserOut])
def refresh_session(
    request: Request,
    user: dict = Depends(get_current_user),
):
    """
    Aktualisiert Permissions in der Session.
    Nützlich nachdem ein Admin einem User Rechte geändert hat.
    """
    db_user = get_user(user["id"])
    if not db_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    permissions = list(db_user.permissions)
    request.session["user"]["permissions"] = permissions
    request.session["last_activity"] = int(time.time())

    return DataResponse(data=UserOut(
        id=user["id"],
        displayName=user["displayName"],
        mail=user.get("mail") or user.get("email"),
        permissions=permissions,
    ))


# ── /auth/me ──────────────────────────────────────────────────────────────────

@router.get("/auth/me", response_model=DataResponse[UserOut])
def me(request: Request, user: dict = Depends(get_current_user)):
    # `permissions` trägt nur noch die Rollen-/Extra-Rechte (view/manage/admin).
    # Die frühere Anreicherung um `create_<tickettyp>` ist mit dem Alt-System
    # entfallen: welcher Prozess anlegbar ist, entscheidet die DEFINITION
    # (createPermissions) und steht je Prozess in GET /processes als `may_create`.
    permissions = get_user_permissions(user["id"])

    return DataResponse(data=UserOut(
        id=user["id"],
        displayName=user["displayName"],
        mail=user.get("mail") or user.get("email"),
        permissions=permissions,
    ))


# ── /auth/profile (volle Profil-Anzeige inkl. Directus-Stammdaten) ────────────

@router.get("/auth/profile", response_model=DataResponse[ProfileOut])
def profile(request: Request, user: dict = Depends(get_current_user)):
    """Alle Infos des angemeldeten Nutzers für die Profil-Ansicht: Konto + das,
    was Azure über die Session mitgibt, plus der per E-Mail verknüpfte
    Directus-Mitarbeiter-Datensatz (`employee`). `permissions` und `employee`
    sind von get_current_user bereits frisch gesetzt."""
    return DataResponse(data=ProfileOut(
        id=user["id"],
        displayName=user["displayName"],
        mail=user.get("mail") or user.get("email"),
        permissions=list(user.get("permissions") or []),
        phone=user.get("phone"),
        mobile=user.get("mobile"),
        company=user.get("company"),
        position=user.get("position"),
        address=user.get("address"),
        groups=list(user.get("groups") or []),
        employee=user.get("employee"),
    ))


# ── /auth/check (Heartbeat – aktualisiert last_activity NICHT) ────────────────

@router.get("/auth/check")
def check_session(user: dict = Depends(check_session_only)):
    """
    Prüft ob die Session noch gültig ist.
    Aktualisiert last_activity NICHT – damit der Heartbeat
    die Session nicht künstlich am Leben hält.
    """
    return {"status": "ok"}


# ── Wartungsmodus (öffentlich – für den Login-Bildschirm) ─────────────────────

@router.get("/maintenance", include_in_schema=False)
def maintenance_status():
    """Öffentlicher Wartungsstatus für den NICHT angemeldeten Login-Bildschirm:
    ist gerade Wartung, mit Hinweistext und geplantem Ende. Bewusst OHNE
    Auth und ohne `by` (wer aktiviert hat ist intern). Fail-open: bei Fehler
    „keine Wartung", damit der Login immer erreichbar bleibt."""
    try:
        m = get_maintenance()
    except Exception:
        logger.exception("Wartungsstatus konnte nicht geladen werden")
        return {"active": False, "message": None, "planned_end": None, "since": None}
    return {"active": m["active"], "message": m["message"],
            "planned_end": m["planned_end"], "since": m["since"]}


# ── Login-Flow ─────────────────────────────────────────────────────────────────

def _split_login_identity(id_claims: dict, infos: dict, email: str, oid) -> tuple[dict, dict]:
    """Login-Daten aufteilen: was ins Session-COOKIE darf und was serverseitig an
    die Session-Zeile (active_sessions.login_profile_json) gehört.

    Ins Cookie nur die schlanke Identität – es ist signiert, aber NICHT
    verschlüsselt, geht mit jedem Request mit und ist auf 4 KB begrenzt. Die
    AD-Gruppen (bei vielen Mitgliedschaften schnell mehrere KB) und das
    Graph-Profil (Telefon, Adresse …) stehen serverseitig; get_current_user hängt
    sie pro Request wieder an (core/dependencies._attach_login_profile)."""
    user_payload = {
        "id":          email or oid,   # Identität = E-Mail (Fallback oid, falls leer)
        "oid":         oid,            # Azure Object-ID – nur noch informativ
        "displayName": id_claims.get("name") or infos.get("displayName"),
        "email":       email,
    }
    login_profile = {
        "groups":   id_claims.get("groups", []) or [],
        "phone":    infos.get("phone"),
        "mobile":   infos.get("mobile"),
        "company":  infos.get("company"),
        "position": infos.get("position"),
        "address":  infos.get("address") or {},
    }
    return user_payload, login_profile


def _session_is_live(session) -> bool:
    """Ist die Cookie-Session serverseitig NOCH gültig? Nur dann darf /start-auth
    kurzschließen. Ein Cookie mit `user` allein genügt NICHT: nach Server-Neustart
    (boot_id passt nicht) oder Admin-Force-Logout (Server-Row weg) ist die Session
    tot, trägt aber weiter `user`. Fail-open bei DB-Hänger (wie _check_session_store),
    damit ein kurzer Ausfall einen gültigen Login nicht abwürgt."""
    if not session.get("user") or session.get("boot_id") != SERVER_BOOT_ID:
        return False
    sid = session.get("sid")
    if not sid:
        return False
    try:
        return get_session(sid) is not None
    except Exception:
        logger.exception("Session-Store-Check in /start-auth fehlgeschlagen – fail-open")
        return True


@router.get("/start-auth", include_in_schema=False)
def start_auth(request: Request):
    record_login_attempt()
    # Nur eine WIRKLICH gültige Session kurzschließen. Eine tote Session (Neustart /
    # Force-Logout) trägt zwar noch `user` im Cookie – früher bounced /start-auth sie
    # endlos zur Frontend-URL (die dann 401t), und erst /logout (das den Cookie leert)
    # brach den Zwischenzustand. Jetzt: toten Cookie verwerfen und sauber neu anmelden.
    if _session_is_live(request.session):
        return RedirectResponse(config.FRONTEND_URL, status_code=HTTP_302_FOUND)
    if request.session.get("user"):
        request.session.clear()   # toten Cookie wegräumen, bevor der OAuth-Flow startet
    auth_url = initiate_auth_flow(request)
    return RedirectResponse(auth_url)


@router.get("/auth/callback", include_in_schema=False)
async def auth_callback(request: Request):
    """OAuth-Rücksprung von Microsoft.

    `async`, weil der Graph-Profil-Abruf asynchron ist. ALLES andere – Token-Tausch
    bei Microsoft (MSAL), DB, Directus, Audit – blockiert und läuft deshalb im
    Thread-Pool: das Backend ist EIN Prozess; blockierende Aufrufe auf dem
    Event-Loop legten während jedes Logins die App für alle anderen still (bei
    Directus-Ausfall bis zum 15-s-Timeout)."""
    try:
        if not request.session.get("auth_flow"):
            raise HTTPException(status_code=400, detail="OAuth Flow fehlt")

        result = await run_in_threadpool(acquire_token_by_auth_code, request)

        if not result or "access_token" not in result:
            return await run_in_threadpool(_login_token_error, request)

        try:
            infos = await get_user_profile(result["access_token"])
        except Exception:
            logger.exception("Graph-Call fehlgeschlagen")
            infos = {}

        return await run_in_threadpool(_complete_login, request, result, infos)

    except Exception:
        logger.exception("Login fehlgeschlagen")
        return await run_in_threadpool(_login_failed, request)


def _login_token_error(request: Request) -> RedirectResponse:
    """Kein Token von Microsoft erhalten (blockierend: Audit)."""
    record_login_failed(reason="token_error")
    record_audit(action="login_failed", actor_type="system", actor_name="?",
                 entity_type="auth", summary="Token konnte nicht bezogen werden",
                 details={"reason": "token_error"}, ip=_client_ip(request))
    return RedirectResponse(
        f"{config.FRONTEND_URL}/login?error=token_error",
        status_code=HTTP_302_FOUND,
    )


def _login_failed(request: Request) -> RedirectResponse:
    """Unerwarteter Fehler im Login (blockierend: Audit)."""
    record_login_failed(reason="exception")
    record_audit(action="login_failed", actor_type="system", actor_name="?",
                 entity_type="auth", summary="Login fehlgeschlagen",
                 details={"reason": "exception"}, ip=_client_ip(request))
    return RedirectResponse(
        f"{config.FRONTEND_URL}/login?error=login_failed",
        status_code=HTTP_302_FOUND,
    )


def _complete_login(request: Request, result: dict, infos: dict) -> RedirectResponse:
    """Erfolgsweg nach Token + Graph-Profil: Nutzer anlegen, Admin-Gruppe
    abgleichen, Wartungs-Sperre, Session aufbauen, Audit. Komplett blockierend
    (DB/Directus) → wird im Thread-Pool ausgeführt; Fehler steigen zum Aufrufer
    auf (→ _login_failed)."""
    id_claims = result.get("id_token_claims", {}) or {}

    # Die AAD-Admin-Gruppe ist maßgeblich für die Admin-Rolle.
    # Wichtig: nur auswerten, wenn ADMIN_GROUP_ID konfiguriert ist und der
    # groups-Claim tatsächlich geliefert wurde. Bei "groups overage" (User in
    # sehr vielen Gruppen) fehlt der Claim – dann NICHT anfassen (fail-safe),
    # sonst würde man Admins fälschlich degradieren.
    raw_groups = id_claims.get("groups")
    groups_authoritative = isinstance(raw_groups, list)  # kein Overage
    user_groups = raw_groups if groups_authoritative else []

    admin_group_configured = bool(config.ADMIN_GROUP_ID)
    is_in_admin_group = admin_group_configured and config.ADMIN_GROUP_ID in user_groups

    # Gruppen-GUIDs nur im DEBUG-Log (verraten Org-Struktur, nicht ins INFO-Log).
    logger.debug("Login groups for user %s: %s", id_claims.get("name"), user_groups)

    # Personen-Identität = kleingeschriebene dienstliche E-Mail. Das ist der
    # stabile, in Azure UND Directus vorhandene Schlüssel; das Directus-Gate
    # (enforce_employee_link) garantiert, dass zu dieser E-Mail ein Mitarbeiter-
    # Datensatz existiert. Von hier fließt sie als user["id"] in owner_id,
    # Beobachter, Zuständigkeit, Gruppen-Mitglieder, app_users usw. Die Azure
    # Object-ID (oid) bleibt nur informativ als user["oid"].
    email = (id_claims.get("preferred_username")
             or id_claims.get("email")
             or infos.get("mail") or "").strip().lower()
    oid = id_claims.get("oid") or id_claims.get("sub")

    user_payload, login_profile = _split_login_identity(id_claims, infos, email, oid)

    # User anlegen / last_login aktualisieren (Rolle wird separat synchronisiert)
    db_user = upsert_user(
        user_id=user_payload["id"],
        display_name=user_payload["displayName"] or "",
        email=user_payload["email"] or "",
    )

    # Admin-Rolle mit der AD-Gruppe abgleichen: gruppen-basierte Admins werden
    # bei Austritt entzogen; manuell vergebene Rollen bleiben unberührt
    # (siehe services.admin_sync). Defensiv – ein Fehler darf den Login nicht
    # blockieren.
    action = decide_group_admin_action(
        admin_group_configured=admin_group_configured,
        groups_authoritative=groups_authoritative,
        is_in_admin_group=is_in_admin_group,
        current_role=db_user.role,
        admin_via_group=db_user.admin_via_group,
    )
    try:
        if action == ACTION_PROMOTE:
            db_user = set_group_admin(user_payload["id"]) or db_user
            record_audit(action="admin_granted", actor_id=user_payload["id"],
                         actor_name=user_payload["displayName"] or "", entity_type="user",
                         entity_id=user_payload["id"], summary="Admin via AD-Gruppe",
                         ip=_client_ip(request))
        elif action == ACTION_REVOKE:
            logger.info("Admin-Rolle entzogen (nicht mehr in AAD-Admin-Gruppe): %s",
                        user_payload["id"])
            db_user = revoke_group_admin(user_payload["id"]) or db_user
            record_audit(action="admin_revoked", actor_id=user_payload["id"],
                         actor_name=user_payload["displayName"] or "", entity_type="user",
                         entity_id=user_payload["id"], summary="Nicht mehr in AD-Admin-Gruppe",
                         ip=_client_ip(request))
    except Exception:
        logger.exception("Admin-Gruppen-Sync fehlgeschlagen für %s", user_payload["id"])

    # Permissions in die Session schreiben
    user_payload["permissions"] = db_user.permissions

    # Wartungsmodus: während einer Wartung dürfen sich nur Admins anmelden.
    # Normale Konten werden hier abgewiesen – OHNE dass eine Session entsteht;
    # der Login-Bildschirm zeigt Hinweis + geplantes Ende. Fail-OPEN: kann der
    # Zustand nicht gelesen werden (DB-Hänger), wird NICHT gesperrt – die Sperre
    # ist Bequemlichkeit, keine Sicherheitsgrenze, und darf nicht alle (inkl.
    # der Leute, die die Wartung beenden) aussperren.
    try:
        maintenance_active = get_maintenance()["active"]
    except Exception:
        logger.exception("Wartungsmodus-Prüfung beim Login fehlgeschlagen – fail-open")
        maintenance_active = False
    if maintenance_active and PERM_ADMIN not in (db_user.permissions or []):
        record_audit(action="login_blocked", actor_id=user_payload["id"],
                     actor_name=user_payload["displayName"] or "", entity_type="auth",
                     entity_id=user_payload["id"],
                     summary="Anmeldung während Wartungsmodus abgewiesen (kein Admin)",
                     ip=_client_ip(request))
        request.session.clear()   # keinen Halb-Zustand (auth_flow) zurücklassen
        return RedirectResponse(
            f"{config.FRONTEND_URL}/login?error=maintenance",
            status_code=HTTP_302_FOUND,
        )

    sid = rotate_sid(request.session)
    request.session.update({
        "user": user_payload,
        "last_activity": int(time.time()),
        "boot_id": SERVER_BOOT_ID,
    })
    request.session.pop("auth_flow", None)

    # Serverseitige Session-Row anlegen (für Live-Liste + Force-Logout).
    # Best-effort – ein DB-Fehler darf den Login nicht verhindern.
    try:
        upsert_session(
            sid=sid,
            user_id=user_payload["id"],
            user_name=user_payload["displayName"] or "",
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            login_profile=login_profile,
        )
    except Exception:
        logger.exception("Session-Registrierung fehlgeschlagen (sid=%s)", sid)

    record_login_success()
    # Directus-Zuordnung EINMAL beim Login prüfen und ins Audit schreiben – sonst
    # bleibt eine Anmeldung, die anschließend am Mitarbeiter-Gate scheitert (z. B.
    # E-Mail in alphacore falsch), ein leerer „Login"-Eintrag ohne Grund.
    link_summary, link_details = _employee_link_audit(user_payload["email"])
    record_audit(action="login", actor_id=user_payload["id"],
                 actor_name=user_payload["displayName"] or "", entity_type="auth",
                 entity_id=user_payload["id"], summary=link_summary,
                 details=link_details, ip=_client_ip(request))

    return RedirectResponse(config.FRONTEND_URL, status_code=HTTP_302_FOUND)


# ── Logout ────────────────────────────────────────────────────────────────────

@router.get("/logout", include_in_schema=False)
def logout(request: Request):
    sid = request.session.get("sid")
    if sid:
        delete_session(sid)
    u = request.session.get("user") or {}
    record_audit(action="logout", actor_id=u.get("id"), actor_name=u.get("displayName") or "",
                 entity_type="auth", entity_id=u.get("id"), ip=_client_ip(request))
    request.session.clear()
    return RedirectResponse(f"{config.FRONTEND_URL}/login", status_code=HTTP_302_FOUND)