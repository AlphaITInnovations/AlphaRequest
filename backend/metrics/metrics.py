import os
import base64
import threading
import time

from fastapi import Request, Response
from prometheus_client import (
    generate_latest,
    CONTENT_TYPE_LATEST,
    REGISTRY
)

from backend.metrics.collect_guard import run_part
from backend.metrics.http_metrics import MetricsMiddleware
from backend.metrics.auth_metrics import collect_session_metrics
from backend.metrics.process_metrics import collect_process_ticket_metrics
from backend.metrics.system_metrics import collect_system_metrics


# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------

ENABLE_METRICS = os.getenv("ENABLE_METRICS", "true").lower() == "true"

METRICS_USERNAME = os.getenv("METRICS_USERNAME")
METRICS_PASSWORD = os.getenv("METRICS_PASSWORD")

COLLECT_INTERVAL_SECONDS = int(os.getenv("METRICS_COLLECT_INTERVAL", "10"))


# ---------------------------------------------------------
# BASIC AUTH
# ---------------------------------------------------------

def _check_basic_auth(request: Request) -> bool:

    if not METRICS_USERNAME or not METRICS_PASSWORD:
        return True

    auth = request.headers.get("Authorization")

    if not auth or not auth.startswith("Basic "):
        return False

    encoded = auth.split(" ", 1)[1]

    try:
        decoded = base64.b64decode(encoded).decode()
    except Exception:
        return False

    if ":" not in decoded:
        return False

    user, pwd = decoded.split(":", 1)

    return user == METRICS_USERNAME and pwd == METRICS_PASSWORD


# ---------------------------------------------------------
# METRICS ENDPOINT
# ---------------------------------------------------------

async def metrics_endpoint(request: Request):

    if not ENABLE_METRICS:
        return Response(status_code=404)

    if not _check_basic_auth(request):
        return Response(
            status_code=401,
            headers={"WWW-Authenticate": "Basic"},
            content="Unauthorized",
        )

    data = generate_latest(REGISTRY)

    return Response(
        content=data,
        media_type=CONTENT_TYPE_LATEST,
    )


# ---------------------------------------------------------
# BACKGROUND COLLECTOR
# ---------------------------------------------------------

# Reihenfolge = Sammelreihenfolge. Jeder Eintrag läuft einzeln abgesichert:
# ein Fehler in EINER Quelle darf die übrigen Reihen nicht mitnehmen und schon
# gar nicht den Thread beenden (dann fröre das ganze Monitoring unbemerkt ein).
_COLLECTORS = (
    ("sessions", collect_session_metrics),
    ("process_tickets", collect_process_ticket_metrics),
    ("system", collect_system_metrics),
)


def collect_all() -> None:
    """Ein vollständiger Sammeldurchlauf. Wirft nicht."""
    for part, fn in _COLLECTORS:
        run_part(part, fn)


def _collector_thread():

    while True:

        time.sleep(COLLECT_INTERVAL_SECONDS)

        try:
            collect_all()
        except Exception:
            # collect_all fängt bereits alles ab; dieser Gürtel sorgt dafür, dass
            # selbst ein Fehler im Absicherungspfad den Thread nicht beendet.
            pass


# ---------------------------------------------------------
# INITIALIZATION
# ---------------------------------------------------------

def init_metrics(app):
    """Metrik-Endpunkt und Sammel-Thread aufsetzen."""
    if not ENABLE_METRICS:
        return

    app.add_middleware(MetricsMiddleware)

    app.add_api_route("/metrics", metrics_endpoint, methods=["GET"])

    thread = threading.Thread(
        target=_collector_thread,
        daemon=True
    )

    thread.start()