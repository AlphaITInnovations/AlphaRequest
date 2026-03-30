from typing import Dict, List
import threading
import time

from fastapi import Request
from prometheus_client import Counter, Gauge, Histogram


# ---------------------------------------------------------
# METRICS
# ---------------------------------------------------------

auth_login_attempts_total = Counter(
    "auth_login_attempts_total",
    "Total login attempts",
)

auth_logins_success_total = Counter(
    "auth_logins_success_total",
    "Successful logins",
    ["provider"],
)

auth_sessions_active = Gauge(
    "auth_sessions_active",
    "Currently active authenticated sessions",
)

auth_sessions_active_by_user = Gauge(
    "auth_sessions_active_by_user",
    "Active sessions per user",
    ["display_name"],
)

auth_session_duration_seconds = Histogram(
    "auth_session_duration_seconds",
    "Session duration",
    buckets=(60, 300, 600, 1800, 3600, 7200, 14400, 28800),
)


# ---------------------------------------------------------
# INTERNAL SESSION STATE
# ---------------------------------------------------------

_sessions: Dict[str, Dict] = {}

_sessions_lock = threading.Lock()

SESSION_TIMEOUT = 3600


# ---------------------------------------------------------
# HELPER: Sync per-user gauge from _sessions
# ---------------------------------------------------------

def _sync_user_gauges():
    """
    Rebuild the per-user gauge from scratch.
    Must be called while holding _sessions_lock.
    """
    # Clear all label sets, then re-count
    auth_sessions_active_by_user._metrics.clear()

    counts: Dict[str, int] = {}
    for s in _sessions.values():
        name = s.get("display_name", "Unknown")
        counts[name] = counts.get(name, 0) + 1

    for name, count in counts.items():
        auth_sessions_active_by_user.labels(display_name=name).set(count)


# ---------------------------------------------------------
# LOGIN ATTEMPT
# ---------------------------------------------------------

def record_login_attempt():
    auth_login_attempts_total.inc()


# ---------------------------------------------------------
# LOGIN SUCCESS
# ---------------------------------------------------------

def record_login_success(request: Request):

    sid = request.session.get("sid")
    if not sid:
        return

    display_name = request.session.get("user", {}).get("displayName", "Unknown")

    now = time.time()

    with _sessions_lock:
        _sessions[sid] = {
            "login_time": now,
            "last_activity": now,
            "display_name": display_name,
        }
        _sync_user_gauges()

    auth_logins_success_total.labels(provider="oauth").inc()
    auth_sessions_active.set(len(_sessions))


# ---------------------------------------------------------
# USER ACTIVITY
# ---------------------------------------------------------

def update_last_activity(request: Request):

    sid = request.session.get("sid")
    if not sid:
        return

    with _sessions_lock:
        session = _sessions.get(sid)
        if session:
            session["last_activity"] = time.time()


# ---------------------------------------------------------
# LOGOUT
# ---------------------------------------------------------

def record_logout(request: Request):

    sid = request.session.get("sid")
    if not sid:
        return

    with _sessions_lock:
        session = _sessions.pop(sid, None)
        if session:
            duration = time.time() - session["login_time"]
            auth_session_duration_seconds.observe(duration)
        _sync_user_gauges()

    auth_sessions_active.set(len(_sessions))


# ---------------------------------------------------------
# SESSION CLEANUP
# ---------------------------------------------------------

def cleanup_sessions():

    now = time.time()

    with _sessions_lock:
        expired = []

        for sid, session in _sessions.items():
            if now - session["last_activity"] > SESSION_TIMEOUT:
                duration = now - session["login_time"]
                auth_session_duration_seconds.observe(duration)
                expired.append(sid)

        for sid in expired:
            _sessions.pop(sid, None)

        _sync_user_gauges()

    auth_sessions_active.set(len(_sessions))


# ---------------------------------------------------------
# API HELPER
# ---------------------------------------------------------

def get_active_users() -> List[str]:
    """Return display names of all currently active sessions."""
    with _sessions_lock:
        return [s["display_name"] for s in _sessions.values()]


# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------

def configure_session_timeout(timeout: int):
    global SESSION_TIMEOUT
    SESSION_TIMEOUT = timeout
