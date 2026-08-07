"""
Prozess-Automations-Scheduler (§7): findet fällige Timer und feuert sie.

Läuft als eigener, durch RUN_SCHEDULER gegateter Task – und OFF THE EVENT LOOP
(asyncio.to_thread), weil DB (pymysql) und Mail (requests) synchron/blockierend
sind. Korrektheit gegen Doppel-Feuern garantiert der Idempotenz-Ledger
(process_timer_fires), nicht das Gate: selbst wenn zwei Instanzen sweepen, gewinnt
nur der erste Claim.

Ausgeführt wird über process_engine (dieselben Pfade wie der Request) – der
Scheduler kümmert sich nur um Auswahl, Claim und Fehlerrobustheit.
"""
import asyncio
from datetime import datetime, timedelta, timezone

from backend.database import process_tickets as store
from backend.database import process_timer_fires as fires
from backend.database import process_definitions as defstore
from backend.schemas.process_definition import ProcessDefinition
from backend.services import process_automations as pa
from backend.services import process_engine as engine
from backend.services import process_runtime as pr
from backend.utils.config import config
from backend.utils.logger import logger

SWEEP_LIMIT = 200
ERROR_BACKOFF_MIN = 15     # bei Fehlern Timer nach hinten schieben (kein Hot-Loop)


def _process_ticket(row_stale: dict, now: datetime) -> None:
    # Frisch lesen: die Liste kann Minuten alt sein (blockierender Mailversand).
    row = store.get(row_stale["id"]) or row_stale
    d = defstore.get_definition(row["process_key"], row["process_version"])
    if not d or not d.get("definition"):
        logger.error("Gepinnte Definition %s v%s fehlt – Ticket #%s wird nicht mehr geplant",
                     row.get("process_key"), row.get("process_version"), row.get("id"))
        store.set_next_timer(row["id"], None)
        return

    defn = ProcessDefinition.model_validate(d["definition"])
    runtime = row.get("runtime") or {}
    phase = pr.current_phase(defn, runtime)
    if phase is None or pr.is_terminal(runtime):
        store.set_next_timer(row["id"], None)
        return

    epoch = int(runtime.get("epoch", 0))
    paused = int(runtime.get("sla_paused_ms", 0))
    ent = engine.entered_at(runtime)
    if not ent:
        store.set_next_timer(row["id"], None)
        return

    fmap = fires.fired_map(row["id"], phase.key, epoch)
    for automation, occs in pa.due_timers(phase, ent, now, paused, fmap, extra=defn.automations):
        last = occs[-1]
        # Guard vor dem Claim: geblockte Occurrences bleiben ungeclaimt, damit sie
        # feuern können, sobald die Bedingung zutrifft.
        if not engine.guard_passes(automation, row):
            continue
        # Catch-up: übersprungene Occurrences nur verbuchen (kein Mail-Sturm).
        for occ in occs[:-1]:
            fires.claim(row["id"], phase.key, epoch, automation.id, occ, suppressed=True)
        if fires.claim(row["id"], phase.key, epoch, automation.id, last):
            if engine.fire(automation, row, defn, phase, occurrence=last):
                engine.transition(row, defn)      # auto_advance: on_exit/on_enter inklusive
                break                              # Phase gewechselt → Timer neu bewerten

    engine.restamp(row, defn)


def sweep_once(now: datetime = None) -> int:
    """Ein Sweep-Durchlauf. Gibt die Anzahl betrachteter Tickets zurück."""
    now = now or datetime.now(timezone.utc)
    due = store.list_due(now.isoformat(), limit=SWEEP_LIMIT)
    for row in due:
        try:
            _process_ticket(row, now)
        except Exception:
            # Selbstheilend: Timer nach hinten schieben, sonst blockiert dieses
            # Ticket bei jedem Sweep erneut das LIMIT-Fenster.
            logger.exception("Sweep für Ticket #%s fehlgeschlagen – Backoff %s min",
                             row.get("id"), ERROR_BACKOFF_MIN)
            try:
                store.set_next_timer(row["id"],
                                     (now + timedelta(minutes=ERROR_BACKOFF_MIN)).isoformat())
            except Exception:
                logger.exception("Backoff für Ticket #%s konnte nicht gesetzt werden", row.get("id"))
    return len(due)


def sweep_until_drained(now: datetime = None, max_batches: int = 20) -> int:
    """Sweept, bis keine volle Seite mehr zurückkommt – damit ein Rückstau
    abfließt, statt über Stunden verteilt zu werden."""
    total = 0
    for _ in range(max_batches):
        n = sweep_once(now)
        total += n
        if n < SWEEP_LIMIT:
            break
    return total


def start(app) -> None:
    """Startet den Scheduler-Loop, wenn RUN_SCHEDULER aktiv ist."""
    if not config.RUN_SCHEDULER:
        logger.info("Prozess-Scheduler deaktiviert (RUN_SCHEDULER=false)")
        return
    interval = max(30, int(config.SCHEDULER_INTERVAL))

    async def _loop():
        while True:
            try:
                n = await asyncio.to_thread(sweep_until_drained)   # off the event loop
                if n:
                    logger.debug("Prozess-Sweep: %s fällige Tickets bearbeitet", n)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Prozess-Sweep-Loop-Fehler")
            await asyncio.sleep(interval)

    # Referenz halten: sonst kann CPython den Task wegräumen (und beim Shutdown
    # wird er sauber abgebrochen).
    task = asyncio.create_task(_loop())
    if app is not None:
        app.state.process_scheduler_task = task
    logger.info("Prozess-Scheduler gestartet (Intervall %ss)", interval)
    return task


async def stop(app) -> None:
    """Scheduler-Task beim Shutdown abbrechen (kein doppelter Loop nach Reload)."""
    task = getattr(getattr(app, "state", None), "process_scheduler_task", None)
    if task is None:
        return
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass
