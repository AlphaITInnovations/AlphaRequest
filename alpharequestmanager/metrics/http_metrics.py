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

http_requests_in_progress = Gauge(
    "http_requests_in_progress",
    "In-progress HTTP requests",
    ["method", "route"],
)

http_exceptions_total = Counter(
    "http_exceptions_total",
    "Unhandled exceptions",
    ["route", "exception"],
)


# ---------------------------------------------------------
# ROUTE NORMALIZATION
# ---------------------------------------------------------

def normalize_path(path: str) -> str:
    """
    Prevent high-cardinality labels in Prometheus.

    Example:
    /tickets/123/delete -> /tickets/:id/delete
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
# METRICS MIDDLEWARE
# ---------------------------------------------------------

class MetricsMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):

        method = request.method
        route = normalize_path(request.url.path)

        http_requests_in_progress.labels(
            method=method,
            route=route
        ).inc()

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