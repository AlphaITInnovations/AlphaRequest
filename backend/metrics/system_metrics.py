import threading
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