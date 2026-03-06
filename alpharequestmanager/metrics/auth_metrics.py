from typing import Dict
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

auth_session_duration_seconds = Histogram(
    "auth_session_duration_seconds",
    "Session duration",
    buckets=(60,300,600,1800,3600,7200,14400,28800),
)


# ---------------------------------------------------------
# INTERNAL SESSION STATE
# ---------------------------------------------------------

_sessions: Dict[str, Dict] = {}

_sessions_lock = threading.Lock()

SESSION_TIMEOUT = 3600


# ---------------------------------------------------------
# LOGIN ATTEMPT
# ---------------------------------------------------------

def record_login_attempt():
    """
    Called before redirecting to Microsoft login.
    """
    auth_login_attempts_total.inc()


# ---------------------------------------------------------
# LOGIN SUCCESS
# ---------------------------------------------------------

def record_login_success(request: Request):

    sid = request.session.get("sid")

    if not sid:
        return

    now = time.time()

    with _sessions_lock:

        _sessions[sid] = {
            "login_time": now,
            "last_activity": now,
        }

    auth_logins_success_total.labels(
        provider="oauth"
    ).inc()

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

    auth_sessions_active.set(len(_sessions))


# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------

def configure_session_timeout(timeout: int):

    global SESSION_TIMEOUT

    SESSION_TIMEOUT = timeout