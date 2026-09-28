"""
Öffentlicher Health-/Uptime-Endpunkt für das Anwendungs-Monitoring.

Keine Authentifizierung – von Monitoring-Tools (Uptime-Checks) aufrufbar.
Prüft die Erreichbarkeit von Backend (dieser Endpunkt selbst), Datenbank
(SELECT 1) und – best-effort – dem Frontend (HTTP-Probe der FRONTEND_URL).

HTTP-Status: 200 wenn Backend + DB erreichbar, sonst 503 (damit ein Monitor
einen echten Ausfall an der DB erkennt). Der Frontend-Status ist informativ
(steckt in `components.frontend`) und beeinflusst den HTTP-Code nicht.
"""
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.utils.config import config

router = APIRouter()

# Näherung an die Prozess-Startzeit (Modul-Import beim App-Start) für die Uptime.
_STARTED_AT = datetime.now(timezone.utc)


def _check_database() -> tuple[bool, str | None]:
    """SELECT 1 gegen die DB. (True, None) bei Erfolg, sonst (False, Fehlertext)."""
    try:
        from backend.database.connection import get_connection, _fetchone
        conn = get_connection()
        try:
            row = _fetchone(conn, "SELECT 1 AS ok")
        finally:
            conn.close()
        if row and row.get("ok") == 1:
            return True, None
        return False, "unerwartete DB-Antwort"
    except Exception as e:
        return False, str(e)[:200]


def _check_frontend() -> tuple[str, str | None]:
    """Best-effort HTTP-Probe der FRONTEND_URL. Jede Antwort = erreichbar ('ok');
    Verbindungs-/Timeout-Fehler = 'down'; keine URL konfiguriert = 'unknown'."""
    url = (config.FRONTEND_URL or "").strip()
    if not url:
        return "unknown", "FRONTEND_URL nicht gesetzt"
    try:
        import requests
        import urllib3
        # Selbstsignierte Zertifikate (interne Hosts) nicht als Fehler werten –
        # es geht nur um Erreichbarkeit, nicht um Zertifikatsprüfung.
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        resp = requests.get(url, timeout=3, verify=False, allow_redirects=False)
        return "ok", f"HTTP {resp.status_code}"
    except Exception as e:
        return "down", str(e)[:200]


@router.get("/health")
def health():
    db_ok, db_detail = _check_database()
    fe_status, fe_detail = _check_frontend()

    components: dict = {
        "backend":  {"status": "ok"},
        "database": {"status": "ok" if db_ok else "down"},
        "frontend": {"status": fe_status},
    }
    if db_detail:
        components["database"]["detail"] = db_detail
    if fe_detail:
        components["frontend"]["detail"] = fe_detail

    # Gesamt: ok = alles erreichbar; degraded = Frontend nicht erreichbar, DB ok;
    # down = DB nicht erreichbar (Kern-Abhängigkeit).
    if not db_ok:
        overall = "down"
    elif fe_status != "ok":
        overall = "degraded"
    else:
        overall = "ok"

    body = {
        "status": overall,
        "components": components,
        "uptime_seconds": int((datetime.now(timezone.utc) - _STARTED_AT).total_seconds()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return JSONResponse(body, status_code=200 if db_ok else 503)
