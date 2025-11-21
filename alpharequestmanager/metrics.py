# metrics.py
import os
import threading
import time
from typing import Optional, Dict
import base64

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

# ---------------------------------------------------------
# ACTIVATE METRICS ONLY IF ENABLE_METRICS=true
# ---------------------------------------------------------
ENABLE_METRICS = os.getenv("ENABLE_METRICS", "false").lower() == "true"

# ---------------------------------------------------------
# PROMETHEUS REGISTRY
# ---------------------------------------------------------
registry = CollectorRegistry()

# ---------------------------------------------------------
# TECHNICAL METRICS
# ---------------------------------------------------------
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status_code"],
    registry=registry,
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path", "status_code"],
    registry=registry,
)

http_requests_in_progress = Gauge(
    "http_requests_in_progress",
    "In-progress HTTP requests",
    ["method", "path"],
    registry=registry,
)

http_exceptions_total = Counter(
    "http_exceptions_total",
    "Total exceptions during request handling",
    ["path", "exception"],
    registry=registry,
)

# ---------------------------------------------------------
# BUSINESS METRICS (Ticketsystem)
# ---------------------------------------------------------
tickets_created_total = Counter(
    "tickets_created_total",
    "Total created tickets",
    ["type", "domain", "company"],
    registry=registry,
)
tickets_total = Gauge(
    "tickets_total",
    "Total number of tickets in the system",
    registry=registry,
)

tickets_status_total = Gauge(
    "tickets_status_total",
    "Number of tickets per status",
    ["status"],
    registry=registry,
)

tickets_by_type = Gauge(
    "tickets_by_type",
    "Number of tickets per type",
    ["type"],
    registry=registry,
)

tickets_by_company = Gauge(
    "tickets_by_company",
    "Number of tickets per company",
    ["company"],
    registry=registry,
)

tickets_by_domain = Gauge(
    "tickets_by_domain",
    "Number of tickets per email domain",
    ["domain"],
    registry=registry,
)

tickets_open_total = Gauge(
    "tickets_open_total",
    "Total currently open tickets",
    ["type", "company"],
    registry=registry,
)

# ---------------------------------------------------------
# EXTENDED METRICS
# ---------------------------------------------------------
login_failures_total = Counter(
    "login_failures_total",
    "Login failures during authentication",
    ["reason"],
    registry=registry,
)

active_users_total = Gauge(
    "active_users_total",
    "Number of currently active users",
    registry=registry,
)

# ---------------------------------------------------------
# INTERNAL STATE
# ---------------------------------------------------------
_active_sessions_lock = threading.Lock()
_active_sessions: Dict[str, float] = {}  # sid → last_activity_ts

SESSION_TIMEOUT = 3600  # overwritten when init_metrics() called
TICKET_MANAGER = None


# ---------------------------------------------------------
# PATH NORMALIZER
# ---------------------------------------------------------
def normalize_path(path: str) -> str:
    # Normalizes dynamic routes like /tickets/123/delete → /tickets/:id/delete
    parts = path.rstrip("/").split("/")
    norm = []
    for p in parts:
        if p.isdigit():
            norm.append(":id")
        else:
            norm.append(p)
    return "/".join(norm)


# ---------------------------------------------------------
# REQUEST MIDDLEWARE
# ---------------------------------------------------------
class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not ENABLE_METRICS:
            return await call_next(request)

        method = request.method
        path = normalize_path(request.url.path)
        http_requests_in_progress.labels(method=method, path=path).inc()

        start_time = time.perf_counter()
        status = "500"

        try:
            response: Response = await call_next(request)
            status = str(response.status_code)
            return response
        except Exception as exc:
            http_exceptions_total.labels(path=path, exception=exc.__class__.__name__).inc()
            raise
        finally:
            elapsed = time.perf_counter() - start_time
            http_request_duration_seconds.labels(
                method=method, path=path, status_code=status
            ).observe(elapsed)

            http_requests_total.labels(
                method=method, path=path, status_code=status
            ).inc()

            http_requests_in_progress.labels(method=method, path=path).dec()


# ---------------------------------------------------------
# ACTIVE USER TRACKING (HYBRID)
# ---------------------------------------------------------
def record_login_success(request: Request):
    """
    Called in server.py after successful login.
    """
    if not ENABLE_METRICS:
        return

    sid = request.session.get("sid")
    if not sid:
        return

    ts = int(time.time())

    with _active_sessions_lock:
        _active_sessions[sid] = ts

    _update_active_users()


def record_logout(request: Request):
    """
    Called when user logs out.
    """
    if not ENABLE_METRICS:
        return

    sid = request.session.get("sid")
    if not sid:
        return

    with _active_sessions_lock:
        _active_sessions.pop(sid, None)

    _update_active_users()

def record_login_failure(reason: str):
    """
    Increments the login_failures_total counter.
    Called whenever authentication fails (OAuth, token exchange, etc.).
    """
    if not ENABLE_METRICS:
        return
    login_failures_total.labels(reason=reason).inc()


def update_last_activity(request: Request):
    """
    Called on every request by server.py (already in get_current_user).
    """
    if not ENABLE_METRICS:
        return

    sid = request.session.get("sid")
    if not sid:
        return

    with _active_sessions_lock:
        _active_sessions[sid] = int(time.time())


def _cleanup_sessions():
    now = time.time()
    timeout_limit = now - SESSION_TIMEOUT

    with _active_sessions_lock:
        to_remove = [sid for sid, ts in _active_sessions.items() if ts < timeout_limit]
        for sid in to_remove:
            _active_sessions.pop(sid, None)

    _update_active_users()


def _update_active_users():
    with _active_sessions_lock:
        active_users_total.set(len(_active_sessions))


# ---------------------------------------------------------
# BUSINESS METRICS COLLECTOR
# ---------------------------------------------------------
def _collect_business_metrics():
    if not ENABLE_METRICS or TICKET_MANAGER is None:
        return

    from alpharequestmanager.models import RequestStatus
    import json

    tickets = TICKET_MANAGER.list_all_tickets()

    status_count: dict[str, int] = {}
    type_count: dict[str, int] = {}
    company_count: dict[str, int] = {}
    domain_count: dict[str, int] = {}
    open_count: dict[tuple[str, str], int] = {}

    for t in tickets:
        # Status
        st = getattr(t.status, "value", None) or "unknown"
        status_count[st] = status_count.get(st, 0) + 1

        # Type
        ttype = t.title or "Unbekannt"
        type_count[ttype] = type_count.get(ttype, 0) + 1

        # Owner info
        info = json.loads(t.owner_info) if t.owner_info else {}
        email = (info.get("email") or "").strip()
        domain = email.split("@", 1)[1] if "@" in email else ""
        company = info.get("company") or ""

        company_count[company] = company_count.get(company, 0) + 1
        domain_count[domain] = domain_count.get(domain, 0) + 1

        # Open tickets (pending)
        if st == RequestStatus.pending.value:
            key = (ttype, company)
            open_count[key] = open_count.get(key, 0) + 1

    # ---- Gauges setzen ----

    # Tickets total
    tickets_total.set(sum(status_count.values()))

    # Status explizit setzen (auch 0, damit nichts „hängen bleibt“)
    for st in ["pending", "approved", "rejected"]:
        tickets_status_total.labels(status=st).set(status_count.get(st, 0))

    # Typen
    for ttype, val in type_count.items():
        tickets_by_type.labels(type=ttype).set(val)

    # Companies
    for company, val in company_count.items():
        tickets_by_company.labels(company=company).set(val)

    # Domains
    for domain, val in domain_count.items():
        tickets_by_domain.labels(domain=domain).set(val)

    # Open tickets
    for (ttype, company), val in open_count.items():
        tickets_open_total.labels(type=ttype, company=company).set(val)



# ---------------------------------------------------------
# BACKGROUND THREAD
# ---------------------------------------------------------
def _collector_thread():
    while True:
        time.sleep(10)
        _cleanup_sessions()
        _collect_business_metrics()


# ---------------------------------------------------------
# /metrics ENDPOINT
# ---------------------------------------------------------
def _check_basic_auth(request: Request) -> bool:
    username = os.getenv("METRICS_USERNAME")
    password = os.getenv("METRICS_PASSWORD")

    # kein Auth gewünscht
    if not username or not password:
        return True

    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Basic "):
        return False

    encoded = auth.split(" ", 1)[1]
    decoded = base64.b64decode(encoded).decode("utf-8")

    if ":" not in decoded:
        return False

    user, pwd = decoded.split(":", 1)

    return user == username and pwd == password



async def metrics_endpoint(request: Request):
    if not ENABLE_METRICS:
        return Response(status_code=404)

    if not _check_basic_auth(request):
        return Response(
            status_code=401,
            headers={"WWW-Authenticate": "Basic realm=\"Metrics\""},
            content="Unauthorized",
        )

    data = generate_latest(registry)
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)



# ---------------------------------------------------------
# INITIALIZATION (called from server.py)
# ---------------------------------------------------------
def init_metrics(app, session_timeout: int, ticket_manager):
    """
    Call in server.py AFTER FastAPI instance creation.
    """
    global SESSION_TIMEOUT, TICKET_MANAGER

    if not ENABLE_METRICS:
        return

    SESSION_TIMEOUT = session_timeout
    TICKET_MANAGER = ticket_manager

    # Middleware
    app.add_middleware(MetricsMiddleware)

    # Endpoint
    app.add_api_route("/metrics", metrics_endpoint, methods=["GET"])
    active_users_total.set(0)

    # Initialize statuses
    for st in ["pending", "approved", "rejected"]:
        tickets_status_total.labels(status=st).set(0)

    # Initialize counters for "known labels"
    login_failures_total.labels(reason="auth_callback_exception").inc(0)
    login_failures_total.labels(reason="invalid_credentials").inc(0)
    login_failures_total.labels(reason="token_exchange_failed").inc(0)

    # A default domain/company/type can be bootstrapped as empty
    tickets_by_type.labels(type="none").set(0)
    tickets_by_company.labels(company="none").set(0)
    tickets_by_domain.labels(domain="none").set(0)
    tickets_open_total.labels(type="none", company="none").set(0)
    # Background thread
    thread = threading.Thread(target=_collector_thread, daemon=True)
    thread.start()


