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

from alpharequestmanager.metrics.http_metrics import MetricsMiddleware
from alpharequestmanager.metrics.auth_metrics import (
    configure_session_timeout,
    cleanup_sessions,
)
from alpharequestmanager.metrics.ticket_metrics import collect_ticket_metrics
from alpharequestmanager.metrics.system_metrics import collect_system_metrics


# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------

ENABLE_METRICS = os.getenv("ENABLE_METRICS", "true").lower() == "true"

METRICS_USERNAME = os.getenv("METRICS_USERNAME")
METRICS_PASSWORD = os.getenv("METRICS_PASSWORD")


# ---------------------------------------------------------
# GLOBAL SERVICES
# ---------------------------------------------------------

TICKET_MANAGER = None


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

def _collector_thread():

    while True:

        time.sleep(10)

        try:

            cleanup_sessions()

            if TICKET_MANAGER:
                collect_ticket_metrics(TICKET_MANAGER)

            collect_system_metrics()

        except Exception as e:
            print("Metrics collector error:", e)


# ---------------------------------------------------------
# INITIALIZATION
# ---------------------------------------------------------

def init_metrics(app, session_timeout: int, ticket_manager):

    global TICKET_MANAGER

    if not ENABLE_METRICS:
        return

    TICKET_MANAGER = ticket_manager

    configure_session_timeout(session_timeout)

    app.add_middleware(MetricsMiddleware)

    app.add_api_route("/metrics", metrics_endpoint, methods=["GET"])

    thread = threading.Thread(
        target=_collector_thread,
        daemon=True
    )

    thread.start()