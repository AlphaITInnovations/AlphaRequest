import re
import time

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from prometheus_client import Counter, Histogram, Gauge


# ---------------------------------------------------------
# HTTP METRICS
# ---------------------------------------------------------

http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "route", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)

# Nur nach Methode – NICHT nach route: der In-progress-Gauge wird VOR dem Routing
# erhöht (das Route-Muster steht da noch nicht fest). Ein route-Label müsste hier
# den Rohpfad tragen und würde die Kardinalität aufblähen (Scanner).
http_requests_in_progress = Gauge(
    "http_requests_in_progress",
    "In-progress HTTP requests",
    ["method"],
)

http_exceptions_total = Counter(
    "http_exceptions_total",
    "Unhandled exceptions",
    ["route", "exception"],
)


# ---------------------------------------------------------
# ROUTE NORMALIZATION
# ---------------------------------------------------------

# GUID (mit Bindestrichen, z.B. Azure oid) bzw. langer Hex-String (z.B. Session-sid = uuid4().hex).
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_HEX_RE = re.compile(r"^[0-9a-fA-F]{16,}$")


def _is_opaque_id(segment: str) -> bool:
    """True für Segmente, die eine ID sind (Zahl, GUID, langer Hex-String)."""
    return bool(segment) and (
        segment.isdigit() or _UUID_RE.match(segment) is not None or _HEX_RE.match(segment) is not None
    )


def normalize_path(path: str) -> str:
    """
    Prevent high-cardinality labels in Prometheus.

    Beispiele:
      /tickets/123/delete                 -> /tickets/:id/delete
      /admin/sessions/9f3a...ab           -> /admin/sessions/:id   (Hex-sid)
      /admin/sessions/user/<guid>         -> /admin/sessions/user/:id
    """

    parts = path.strip("/").split("/")
    normalized = [":id" if _is_opaque_id(p) else p for p in parts]

    return "/" + "/".join(normalized)


#: Sammel-Label für Anfragen, die auf KEINE definierte Route passen (404-Scan) –
#: hält die Kardinalität an der Zahl echter Endpunkte fest.
_UNMATCHED = "__unmatched__"


def route_label(request: Request) -> str:
    """Ein KARDINALITÄTS-SICHERES route-Label: das gematchte Route-MUSTER (z. B.
    /process-tickets/{ticket_id}), NICHT der Rohpfad. Sonst erzeugt ein Scanner, der
    beliebige Pfade abklappert, unbegrenzt viele Zeitreihen (Speicher-DoS aufs
    Monitoring). Wird erst NACH dem Routing aufgerufen (Muster steht dann fest).

    Robuste Auflösung in Stufen: (1) `scope["route"].path`, falls die Starlette-
    Version es setzt; (2) Rekonstruktion aus den `path_params` (Werte im Pfad durch
    `:name` ersetzt); (3) ID-Normalisierung für parameterlose Treffer; (4) sonst
    `__unmatched__`."""
    scope = getattr(request, "scope", {}) or {}
    tmpl = getattr(scope.get("route"), "path", None)
    if tmpl:
        return tmpl
    path = scope.get("path") or request.url.path
    params = scope.get("path_params") or {}
    if params:
        for name, val in params.items():
            if val is not None:
                path = path.replace(str(val), f":{name}", 1)
        return path
    if scope.get("endpoint") is not None:
        return normalize_path(path)
    return _UNMATCHED


# ---------------------------------------------------------
# METRICS MIDDLEWARE
# ---------------------------------------------------------

class MetricsMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):

        method = request.method

        http_requests_in_progress.labels(method=method).inc()

        start = time.perf_counter()
        status = "500"

        try:

            response: Response = await call_next(request)
            status = str(response.status_code)

            return response

        except Exception as exc:

            # route erst NACH dem Routing bestimmen (Muster steht dann fest).
            http_exceptions_total.labels(
                route=route_label(request),
                exception=exc.__class__.__name__,
            ).inc()

            raise

        finally:

            duration = time.perf_counter() - start
            route = route_label(request)

            http_requests_total.labels(
                method=method,
                route=route,
                status=status,
            ).inc()

            http_request_duration_seconds.labels(
                method=method,
                route=route,
            ).observe(duration)

            http_requests_in_progress.labels(method=method).dec()