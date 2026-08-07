import asyncio
import sys
import uvicorn
from pathlib import Path
from typing import cast
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.datastructures import State
from backend.api.v1 import tickets as tickets_v1
from backend.api.v1 import auth as auth_v1
from backend.core.app_lifespan import lifespan
from backend.core.session import setup_session
from backend.database import init_db
from backend.models.models import TicketType
from backend.metrics.metrics import init_metrics
from backend.services.ticket_service import TicketService
from backend.utils.config import config
from backend.api.v1 import dashboard as dashboard_v1
from backend.api.v1 import users as users_v1
from backend.api.v1 import companies as companies_v1
from backend.api.v1 import ticket_view as ticket_view_v1
from backend.api.v1 import settings as settings_v1
from backend.api.v1 import ticket_overview as ticket_overview_v1
from backend.api.v1 import feedback as feedback_v1
from backend.api.v1 import freigabe as freigabe_v1
from backend.api.v1 import sessions as sessions_v1
from backend.api.v1 import health as health_v1
from backend.api.v1 import attachments as attachments_v1
from backend.api.v1 import processes as processes_v1
from backend.api.v1 import process_tickets as process_tickets_v1


def get_ticket_type_dict():
    return {t.name: t.value for t in TicketType}


def _assert_secure_config() -> None:
    """In Produktion niemals mit dem Default-/zu kurzen SECRET_KEY starten.
    Die Session ist ein signiertes Cookie, das die User-Identität trägt – ein
    bekannter/kurzer Schlüssel erlaubt das Fälschen beliebiger Sessions."""
    if config.APP_ENV == "development":
        return
    if config.SECRET_KEY in ("", "change-me-min-16-chars") or len(config.SECRET_KEY) < 16:
        raise RuntimeError(
            "Unsicherer SECRET_KEY: In Produktion muss SECRET_KEY gesetzt und "
            ">= 16 Zeichen lang sein (nicht der Default)."
        )


def _install_error_handlers(app: FastAPI) -> None:
    """Vereinheitlicht alle Fehler-Antworten auf den Envelope
    { error: { code, message, fields? } } (schemas.responses)."""
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException
    from fastapi.responses import JSONResponse

    _CODE_BY_STATUS = {400: "BAD_REQUEST", 401: "UNAUTHORIZED", 403: "FORBIDDEN",
                       404: "NOT_FOUND", 409: "CONFLICT", 422: "VALIDATION_FAILED"}

    @app.exception_handler(RequestValidationError)
    async def _on_validation_error(request, exc: RequestValidationError):
        fields = []
        for e in exc.errors():
            loc = list(e.get("loc", []))
            # Nur den führenden Quell-Marker entfernen (body/query/path), nicht ein
            # gleichnamiges Feld an tieferer Stelle.
            if loc and loc[0] in ("body", "query", "path"):
                loc = loc[1:]
            fields.append({"path": ".".join(str(p) for p in loc) or "body",
                           "code": str(e.get("type", "invalid")),
                           "message": e.get("msg", "ungültig")})
        return JSONResponse(status_code=422, content={"error": {
            "code": "VALIDATION_FAILED", "message": "Validierung fehlgeschlagen", "fields": fields}})

    @app.exception_handler(StarletteHTTPException)
    async def _on_http_error(request, exc: StarletteHTTPException):
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail:
            body = {"code": detail.get("code"), "message": detail.get("message", "")}
            if detail.get("fields"):
                body["fields"] = detail["fields"]
        else:
            body = {"code": _CODE_BY_STATUS.get(exc.status_code, "HTTP_ERROR"),
                    "message": detail if isinstance(detail, str) else str(detail)}
        return JSONResponse(status_code=exc.status_code, content={"error": body},
                            headers=getattr(exc, "headers", None))


def create_app() -> FastAPI:
    _assert_secure_config()
    app = FastAPI(lifespan=lifespan)
    app.state = cast(State, app.state)
    app.state.manager = TicketService()
    _install_error_handlers(app)

    BASE_DIR = Path(__file__).resolve().parent

    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

    app.templates = Jinja2Templates(directory=BASE_DIR / "templates")
    app.templates.env.globals["SESSION_TIMEOUT"] = config.SESSION_TIMEOUT
    app.templates.env.globals["TicketTypes"] = get_ticket_type_dict()

    setup_session(app)
    init_metrics(app, app.state.manager)

    @app.middleware("http")
    async def _security_headers(request, call_next):
        """Defensive Response-Header (Clickjacking/MIME-Sniffing/Referer-Leak).
        Keine CSP – die müsste erst gegen die SPA getestet werden."""
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        # Verhindert, dass die (token-tragende) Freigabe-URL per Referer abfließt.
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if config.APP_ENV != "development":
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains",
            )

        # Abgelehnte Admin-/Settings-Zugriffe (403) auditieren (Missbrauchsversuche).
        if response.status_code == 403:
            path = request.url.path
            if "/admin/" in path or "/settings/" in path:
                try:
                    from backend.database.audit_log import record_audit
                    u = (request.scope.get("session") or {}).get("user") or {}
                    record_audit(
                        action="access_denied",
                        actor_id=u.get("id"),
                        actor_name=u.get("displayName") or u.get("email") or "?",
                        entity_type="auth",
                        summary=f"{request.method} {path}",
                        details={"method": request.method, "path": path},
                        ip=request.client.host if request.client else None,
                    )
                except Exception:
                    pass

        return response

    app.include_router(auth_v1.router)
    app.include_router(auth_v1.router, prefix="/api/v1")
    app.include_router(tickets_v1.router, prefix="/api/v1")
    app.include_router(dashboard_v1.router, prefix="/api/v1")
    app.include_router(users_v1.router, prefix="/api/v1")
    app.include_router(companies_v1.router, prefix="/api/v1")
    app.include_router(ticket_view_v1.router, prefix="/api/v1")
    app.include_router(settings_v1.router, prefix="/api/v1")
    app.include_router(ticket_overview_v1.router, prefix="/api/v1")
    app.include_router(feedback_v1.router, prefix="/api/v1")
    app.include_router(freigabe_v1.router, prefix="/api/v1")
    app.include_router(sessions_v1.router, prefix="/api/v1")
    app.include_router(attachments_v1.router, prefix="/api/v1")
    app.include_router(processes_v1.router, prefix="/api/v1")
    app.include_router(process_tickets_v1.router, prefix="/api/v1")

    # Öffentlicher Health-/Uptime-Endpunkt – unter /health UND /api/v1/health
    # erreichbar (Root für interne/Container-Checks, /api/v1 hinter dem Proxy).
    app.include_router(health_v1.router)
    app.include_router(health_v1.router, prefix="/api/v1")

    return app


app = create_app()


def configure_event_loop():
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def run_server(https: bool = False):
    ssl_args = {}
    if https:
        ssl_args = {
            "ssl_keyfile": "../data/cert/key.pem",
            "ssl_certfile": "../data/cert/cert.pem",
        }
    # Läuft hinter Traefik (TLS-Terminierung): X-Forwarded-For/-Proto auswerten,
    # damit request.client.host die ECHTE Nutzer-IP ist (wichtig fürs Audit-Log)
    # und das Schema als https erkannt wird. forwarded_allow_ips="*" ist ok, weil
    # die App nur über den Proxy erreichbar ist (nicht öffentlich exponiert).
    uvicorn.run(
        app, host="0.0.0.0", port=config.PORT, reload=False,
        proxy_headers=True, forwarded_allow_ips="*",
        **ssl_args,
    )


def main():
    init_db()
    configure_event_loop()
    run_server(https=config.HTTPS)


if __name__ == "__main__":

    main()
