"""
Prozess-Automations-Scheduler (§7): findet fällige Timer und feuert sie.

Läuft als eigener, durch RUN_SCHEDULER gegateter Task – und OFF THE EVENT LOOP
(asyncio.to_thread), weil DB (pymysql) und Mail (requests) synchron/blockierend
sind. Korrektheit gegen Doppel-Feuern garantiert der Idempotenz-Ledger
(process_timer_fires), nicht das Gate: selbst wenn zwei Instanzen sweepen, gewinnt
nur der erste Claim.

sweep_once() ist synchron und rein über Modul-Aliasse verdrahtet (store/fires/
defstore/SENDER) → in Tests mit In-Memory-Fakes bespielbar.
"""
import asyncio
from datetime import datetime, timezone

from backend.database import process_tickets as store
from backend.database import process_timer_fires as fires
from backend.database import process_definitions as defstore
from backend.database.audit_log import record_audit
from backend.schemas.process_definition import ProcessDefinition
from backend.services import process_automations as pa
from backend.services import process_runtime as pr
from backend.services import process_actions as actions
from backend.utils.config import config
from backend.utils.logger import logger

SENDER = actions._default_sender   # in Tests überschreibbar


def _entered_at(runtime: dict) -> str:
    idx = runtime.get("current_index", 0)
    phases = runtime.get("phases", [])
    if 0 <= idx < len(phases):
        return phases[idx].get("entered_at")
    return None


def _process_ticket(row: dict, now: datetime) -> None:
    d = defstore.get_definition(row["process_key"], row["process_version"])
    if not d or not d.get("definition"):
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
    entered = _entered_at(runtime)
    if not entered:
        store.set_next_timer(row["id"], None)
        return

    fmap = fires.fired_map(row["id"], phase.key, epoch)
    for automation, occs in pa.due_timers(phase, entered, now, paused, fmap):
        # Catch-up: alle bis auf die letzte Occurrence nur verbuchen (unterdrückt)
        for occ in occs[:-1]:
            fires.claim(row["id"], phase.key, epoch, automation.id, occ, suppressed=True)
        last = occs[-1]
        if fires.claim(row["id"], phase.key, epoch, automation.id, last):
            changes = actions.run_action(automation.action, row, defn, phase, sender=SENDER)
            actions.apply_action_changes(row, defn, changes, store)
            record_audit(
                action="process_automation_fired", actor_id=None, actor_name="System",
                actor_type="system", entity_type="process_ticket", entity_id=str(row["id"]),
                summary=f"Automation „{automation.id}“ (Occ. {last}) in Phase {phase.key} gefeuert",
                details={"automation": automation.id, "occurrence": last,
                         "action": automation.action.type.value},
            )

    # next_timer_due_at auf Basis der Phase nach evtl. advance neu berechnen
    runtime = row.get("runtime") or {}
    phase = pr.current_phase(defn, runtime)
    if phase is None or pr.is_terminal(runtime):
        store.set_next_timer(row["id"], None)
        return
    epoch = int(runtime.get("epoch", 0))
    entered = _entered_at(runtime)
    fmap = fires.fired_map(row["id"], phase.key, epoch)
    nd = pa.compute_next_timer_due(phase, entered, paused, fmap) if entered else None
    store.set_next_timer(row["id"], nd.isoformat() if nd else None)


def sweep_once(now: datetime = None) -> int:
    """Ein Sweep-Durchlauf. Gibt die Anzahl bearbeiteter Tickets zurück."""
    now = now or datetime.now(timezone.utc)
    due = store.list_due(now.isoformat(), limit=200)
    for row in due:
        try:
            _process_ticket(row, now)
        except Exception:
            logger.exception("Sweep für Ticket #%s fehlgeschlagen", row.get("id"))
    return len(due)


def start(app) -> None:
    """Startet den Scheduler-Loop, wenn RUN_SCHEDULER aktiv ist."""
    if not config.RUN_SCHEDULER:
        logger.info("Prozess-Scheduler deaktiviert (RUN_SCHEDULER=false)")
        return
    interval = max(30, int(config.SCHEDULER_INTERVAL))

    async def _loop():
        while True:
            try:
                n = await asyncio.to_thread(sweep_once)   # off the event loop
                if n:
                    logger.debug("Prozess-Sweep: %s fällige Tickets bearbeitet", n)
            except Exception:
                logger.exception("Prozess-Sweep-Loop-Fehler")
            await asyncio.sleep(interval)

    asyncio.create_task(_loop())
    logger.info("Prozess-Scheduler gestartet (Intervall %ss)", interval)
