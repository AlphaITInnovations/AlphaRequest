import os
import time
import base64
import threading
from typing import Dict

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    Summary,
    generate_latest,
    CONTENT_TYPE_LATEST,
    ProcessCollector,
    PlatformCollector,
    GCCollector,
)

# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------

ENABLE_METRICS = os.getenv("ENABLE_METRICS", "false").lower() == "true"

METRICS_USERNAME = os.getenv("METRICS_USERNAME")
METRICS_PASSWORD = os.getenv("METRICS_PASSWORD")

# ---------------------------------------------------------
# REGISTRY
# ---------------------------------------------------------

registry = CollectorRegistry()

# Default runtime collectors
ProcessCollector(registry=registry)
PlatformCollector(registry=registry)
GCCollector(registry=registry)

# ---------------------------------------------------------
# HTTP METRICS
# ---------------------------------------------------------

http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "route", "status"],
    registry=registry,
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
    buckets=(
        0.005,
        0.01,
        0.025,
        0.05,
        0.1,
        0.25,
        0.5,
        1,
        2.5,
        5,
        10,
    ),
    registry=registry,
)

http_requests_in_progress = Gauge(
    "http_requests_in_progress",
    "Active HTTP requests",
    ["method", "route"],
    registry=registry,
)

http_exceptions_total = Counter(
    "http_exceptions_total",
    "Total uncaught exceptions",
    ["route", "exception"],
    registry=registry,
)

# ---------------------------------------------------------
# AUTH METRICS
# ---------------------------------------------------------

auth_logins_total = Counter(
    "auth_logins_total",
    "Total login attempts",
    ["result", "provider"],
    registry=registry,
)

auth_sessions_active = Gauge(
    "auth_sessions_active",
    "Active authenticated sessions",
    registry=registry,
)

auth_login_failures_total = Counter(
    "auth_login_failures_total",
    "Login failures",
    ["reason"],
    registry=registry,
)

# ---------------------------------------------------------
# TICKET LIFECYCLE METRICS
# ---------------------------------------------------------

tickets_created_total = Counter(
    "tickets_created_total",
    "Total tickets created",
    ["type"],
    registry=registry,
)

tickets_closed_total = Counter(
    "tickets_closed_total",
    "Total tickets closed",
    ["type", "status"],
    registry=registry,
)

tickets_current = Gauge(
    "tickets_current",
    "Current number of tickets",
    ["status"],
    registry=registry,
)

tickets_by_type = Gauge(
    "tickets_by_type",
    "Tickets grouped by type",
    ["type"],
    registry=registry,
)

tickets_open = Gauge(
    "tickets_open",
    "Open tickets",
    ["type"],
    registry=registry,
)

ticket_resolution_seconds = Histogram(
    "ticket_resolution_seconds",
    "Ticket resolution time",
    ["type"],
    buckets=(
        60,
        300,
        600,
        1800,
        3600,
        7200,
        14400,
        28800,
        86400,
    ),
    registry=registry,
)

# ---------------------------------------------------------
# SYSTEM LOAD METRICS
# ---------------------------------------------------------

background_jobs_running = Gauge(
    "background_jobs_running",
    "Background jobs currently running",
    registry=registry,
)

background_jobs_total = Counter(
    "background_jobs_total",
    "Background jobs executed",
    ["result"],
    registry=registry,
)

# ---------------------------------------------------------
# INTERNAL SESSION TRACKING
# ---------------------------------------------------------

SESSION_TIMEOUT = 3600
TICKET_MANAGER = None

_sessions: Dict[str, float] = {}
_sessions_lock = threading.Lock()

# ---------------------------------------------------------
# ROUTE NORMALIZATION
# ---------------------------------------------------------


def normalize_path(path: str) -> str:
    """
    Prevent high cardinality in Prometheus labels.
    """

    parts = path.strip("/").split("/")
    normalized = []

    for p in parts:
        if p.isdigit():
            normalized.append(":id")
        else:
            normalized.append(p)

    return "/" + "/".join(normalized)


# ---------------------------------------------------------
# MIDDLEWARE
# ---------------------------------------------------------


class MetricsMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):

        if not ENABLE_METRICS:
            return await call_next(request)

        method = request.method
        route = normalize_path(request.url.path)

        http_requests_in_progress.labels(method=method, route=route).inc()

        start = time.perf_counter()
        status = "500"

        try:

            response: Response = await call_next(request)
            status = str(response.status_code)
            return response

        except Exception as exc:

            http_exceptions_total.labels(
                route=route,
                exception=exc.__class__.__name__,
            ).inc()

            raise

        finally:

            duration = time.perf_counter() - start

            http_requests_total.labels(
                method=method,
                route=route,
                status=status,
            ).inc()

            http_request_duration_seconds.labels(
                method=method,
                route=route,
            ).observe(duration)

            http_requests_in_progress.labels(
                method=method,
                route=route,
            ).dec()


# ---------------------------------------------------------
# SESSION TRACKING
# ---------------------------------------------------------


def record_login_success(request: Request):

    if not ENABLE_METRICS:
        return

    sid = request.session.get("sid")
    if not sid:
        return

    with _sessions_lock:
        _sessions[sid] = time.time()

    auth_logins_total.labels(
        result="success",
        provider="oauth",
    ).inc()

    _update_active_sessions()


def record_login_failure(reason: str):

    if not ENABLE_METRICS:
        return

    auth_login_failures_total.labels(reason=reason).inc()

    auth_logins_total.labels(
        result="failure",
        provider="oauth",
    ).inc()


def record_logout(request: Request):

    if not ENABLE_METRICS:
        return

    sid = request.session.get("sid")

    if not sid:
        return

    with _sessions_lock:
        _sessions.pop(sid, None)

    _update_active_sessions()


def update_last_activity(request: Request):

    if not ENABLE_METRICS:
        return

    sid = request.session.get("sid")

    if not sid:
        return

    with _sessions_lock:
        _sessions[sid] = time.time()


def _cleanup_sessions():

    now = time.time()
    timeout = now - SESSION_TIMEOUT

    with _sessions_lock:

        expired = [
            sid
            for sid, ts in _sessions.items()
            if ts < timeout
        ]

        for sid in expired:
            _sessions.pop(sid, None)

    _update_active_sessions()


def _update_active_sessions():

    with _sessions_lock:
        auth_sessions_active.set(len(_sessions))


# ---------------------------------------------------------
# BUSINESS METRICS COLLECTOR
# ---------------------------------------------------------


def _collect_ticket_metrics():

    if not ENABLE_METRICS or TICKET_MANAGER is None:
        return

    tickets = TICKET_MANAGER.list_all()

    status_count: Dict[str, int] = {}
    type_count: Dict[str, int] = {}

    for t in tickets:

        status = getattr(t.status, "value", "unknown")
        status_count[status] = status_count.get(status, 0) + 1

        ttype = getattr(t, "title", "unknown")
        type_count[ttype] = type_count.get(ttype, 0) + 1

    total = sum(status_count.values())

    for status, count in status_count.items():
        tickets_current.labels(status=status).set(count)

    for ttype, count in type_count.items():
        tickets_by_type.labels(type=ttype).set(count)

    open_count = status_count.get("pending", 0) + status_count.get("in_progress", 0)

    tickets_open.labels(type="all").set(open_count)


# ---------------------------------------------------------
# BACKGROUND COLLECTOR
# ---------------------------------------------------------


def _collector_thread():

    while True:

        time.sleep(10)

        try:
            _cleanup_sessions()
            _collect_ticket_metrics()
        except Exception:
            pass


# ---------------------------------------------------------
# METRICS AUTH
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
# /metrics ENDPOINT
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

    data = generate_latest(registry)

    return Response(
        content=data,
        media_type=CONTENT_TYPE_LATEST,
    )


# ---------------------------------------------------------
# INITIALIZATION
# ---------------------------------------------------------


def init_metrics(app, session_timeout: int, ticket_manager):

    global SESSION_TIMEOUT
    global TICKET_MANAGER

    if not ENABLE_METRICS:
        return

    SESSION_TIMEOUT = session_timeout
    TICKET_MANAGER = ticket_manager

    app.add_middleware(MetricsMiddleware)

    app.add_api_route(
        "/metrics",
        metrics_endpoint,
        methods=["GET"],
    )

    auth_sessions_active.set(0)

    thread = threading.Thread(
        target=_collector_thread,
        daemon=True,
    )

    thread.start()