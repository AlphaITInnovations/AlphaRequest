import threading
import os
import time

from prometheus_client import Gauge


# ---------------------------------------------------------
# SYSTEM METRICS
# ---------------------------------------------------------

process_threads = Gauge(
    "process_threads",
    "Number of active Python threads"
)

process_uptime_seconds = Gauge(
    "process_uptime_seconds",
    "Application uptime in seconds"
)

background_jobs_running = Gauge(
    "background_jobs_running",
    "Currently running background jobs"
)

background_jobs_total = Gauge(
    "background_jobs_total",
    "Total background jobs executed"
)


# ---------------------------------------------------------
# INTERNAL STATE
# ---------------------------------------------------------

START_TIME = time.time()


# ---------------------------------------------------------
# COLLECT SYSTEM METRICS
# ---------------------------------------------------------

def collect_system_metrics():

    # Thread count
    process_threads.set(threading.active_count())

    # Uptime
    uptime = time.time() - START_TIME
    process_uptime_seconds.set(uptime)