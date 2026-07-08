"""
Auth-/Session-Metriken.

Die aktiven-Sessions-Gauges werden NICHT mehr aus einem eigenen In-Memory-Dict
gespeist, sondern im Collector direkt aus der autoritativen `active_sessions`-
Tabelle (siehe backend/database/sessions.py). Dadurch reflektieren sie Logout,
Force-Logout, Timeout und Server-Neustart automatisch korrekt.
"""

from prometheus_client import Counter, Gauge

from backend.database import sessions as session_store
from backend.utils.logger import logger


# ── Event-Zähler ────────────────────────────────────────────────────────────────

auth_login_attempts_total = Counter(
    "auth_login_attempts_total",
    "Login flow initiations (redirects to the identity provider)",
)

auth_logins_success_total = Counter(
    "auth_logins_success_total",
    "Successful logins",
    ["provider"],
)

auth_login_failed_total = Counter(
    "auth_login_failed_total",
    "Failed logins",
    ["reason"],
)

session_force_logouts_total = Counter(
    "session_force_logouts_total",
    "Sessions terminated by an admin force-logout",
    ["scope"],  # session | user | others
)


# ── Gauges (im Collector aus der DB gesetzt) ────────────────────────────────────

auth_sessions_active = Gauge(
    "auth_sessions_active",
    "Currently active sessions (source: active_sessions table)",
)

auth_users_online = Gauge(
    "auth_users_online",
    "Distinct users with at least one active session",
)


# ── Recorder ────────────────────────────────────────────────────────────────────

def record_login_attempt() -> None:
    auth_login_attempts_total.inc()


def record_login_success(provider: str = "oauth") -> None:
    auth_logins_success_total.labels(provider=provider).inc()


def record_login_failed(reason: str = "unknown") -> None:
    auth_login_failed_total.labels(reason=reason).inc()


def record_force_logout(scope: str, count: int = 1) -> None:
    if count <= 0:
        return
    session_force_logouts_total.labels(scope=scope).inc(count)


# ── Collector (aus der DB) ──────────────────────────────────────────────────────

def collect_session_metrics() -> None:
    """Aktive Sessions + Online-Nutzer aus der DB spiegeln. Best-effort."""
    try:
        rows = session_store.list_active_sessions()
    except Exception:
        logger.exception("Session-Metriken konnten nicht aus der DB gelesen werden")
        return
    auth_sessions_active.set(len(rows))
    auth_users_online.set(len({r.get("user_id") for r in rows if r.get("user_id")}))
