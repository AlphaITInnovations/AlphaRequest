"""
Gemeinsame Ausführungs-Schicht für Prozess-Tickets.

Request-Pfad (api/v1/process_tickets.py) UND Scheduler nutzen AUSSCHLIESSLICH
diese Funktionen, damit „Phase betreten", „Automation feuern" und „Timer neu
stempeln" nicht zweimal existieren und auseinanderlaufen können.

Verantwortlichkeiten:
  * guard_passes  – wertet den (bis dahin nur validierten) Automation-Guard aus
  * fire          – Guard → Action ausführen → Zustandsänderungen anwenden → Audit
  * run_inline    – nicht-Timer-Trigger (on_enter/on_exit/on_field_change)
  * restamp       – next_timer_due_at aus dem ECHTEN Ledger-Stand berechnen
  * transition    – on_exit → advance (persistiert) → on_enter → restamp,
                    inkl. verketteter auto_advance mit Tiefenbegrenzung

`store`, `fires` und `SENDER` sind Modul-Aliasse (Tests ersetzen sie).
"""
import json
from typing import Optional

from backend.database import process_tickets as store
from backend.database import process_timer_fires as fires
from backend.database.audit_log import record_audit
from backend.schemas.process_definition import ProcessDefinition, PhaseDef, TriggerType
from backend.services import process_actions as actions
from backend.services import process_automations as pa
from backend.services import process_events as events
from backend.services import process_runtime as pr
from backend.services import process_sequences as sequences
from backend.services.condition_dsl import evaluate
from backend.utils.logger import logger
from backend.utils.timeutil import utcnow_iso

SENDER = actions._default_sender      # in Tests überschreibbar
MAX_CHAINED_ADVANCES = 10             # Schutz gegen auto_advance-Endlosketten


# ── Hilfen ────────────────────────────────────────────────────────────────────

def entered_at(runtime: dict) -> Optional[str]:
    idx = runtime.get("current_index", 0)
    phases = runtime.get("phases", [])
    if 0 <= idx < len(phases):
        return phases[idx].get("entered_at")
    return None


def guard_passes(automation, row: dict) -> bool:
    """Guard der Automation auswerten (fehlender Guard = feuern)."""
    if not automation.guard:
        return True
    try:
        return bool(evaluate(automation.guard, row.get("values") or {}))
    except Exception:
        # Fail-closed: ein kaputter Guard darf nicht ungewollt feuern.
        logger.exception("Guard von Automation „%s“ nicht auswertbar – wird NICHT gefeuert",
                         automation.id)
        return False


def _audit_fired(row: dict, phase: PhaseDef, automation, occurrence: Optional[int]) -> None:
    details = {"automation": automation.id, "occurrence": occurrence,
               "trigger": automation.trigger.type.value,
               "action": automation.action.type.value}
    # Der frei gewählte Anlass-Text der Automation wandert mit in den Verlauf –
    # das pauschale Etikett „Erinnerung" war für eine ERSTMALIGE Benachrichtigung
    # (z. B. Weiterreichen des Basis-Tickets) schlicht falsch.
    if getattr(automation.action, "template", None):
        details["template"] = automation.action.template
    record_audit(
        action="process_automation_fired", actor_id=None, actor_name="System",
        actor_type="system", entity_type="process_ticket", entity_id=str(row["id"]),
        summary=(f"Automation „{automation.id}“"
                 + (f" (Occ. {occurrence})" if occurrence is not None else "")
                 + f" in Phase {phase.key} gefeuert"),
        details=details,
    )
    # Auch im Verlauf sichtbar machen: eine Eskalation, die niemand im Ticket
    # sieht, wirkt wie „es ist nichts passiert" (das Audit liest nur der Admin).
    events.system(row, events.AUTOMATION_FIRED, phase_key=phase.key, details=details)


def _audit_failed(row: dict, automation, exc: Exception) -> None:
    record_audit(
        action="process_automation_failed", actor_id=None, actor_name="System",
        actor_type="system", entity_type="process_ticket", entity_id=str(row["id"]),
        summary=f"Automation „{automation.id}“ fehlgeschlagen: {type(exc).__name__}",
        details={"automation": automation.id, "error": str(exc)[:500]},
    )


# ── Feuern ────────────────────────────────────────────────────────────────────

def fire(automation, row: dict, defn: ProcessDefinition, phase: PhaseDef,
         occurrence: Optional[int] = None) -> bool:
    """Führt eine Automation aus (Guard bereits geprüft). Gibt zurück, ob ein
    auto_advance angefordert wurde. Wirft nicht – Fehler werden auditiert."""
    try:
        changes = actions.run_action(automation.action, row, defn, phase, sender=SENDER)
        actions.apply_action_changes(row, defn, changes, store)
        _audit_fired(row, phase, automation, occurrence)
        return bool(changes.get("advance"))
    except Exception as exc:
        logger.exception("Automation „%s“ für Ticket #%s fehlgeschlagen",
                         automation.id, row.get("id"))
        _audit_failed(row, automation, exc)
        return False


def run_inline(row: dict, defn: ProcessDefinition, phase: Optional[PhaseDef],
               trigger_types: set, changed_fields: Optional[set] = None) -> bool:
    """Nicht-Timer-Automations der Phase ausführen. Gibt zurück, ob ein
    auto_advance angefordert wurde."""
    if phase is None:
        return False
    wants_advance = False
    # Prozessweite Automations gelten in jeder Phase, danach die phasen-eigenen.
    for a in list(defn.automations) + list(phase.automations):
        if a.trigger.type not in trigger_types:
            continue
        if a.trigger.type == TriggerType.on_field_change:
            if not changed_fields or a.trigger.field not in changed_fields:
                continue
        if not guard_passes(a, row):
            continue
        wants_advance |= fire(a, row, defn, phase)
    return wants_advance


# ── Timer neu stempeln ────────────────────────────────────────────────────────

def restamp(row: dict, defn: Optional[ProcessDefinition]) -> None:
    """next_timer_due_at der AKTUELLEN Phase setzen – auf Basis des echten
    Ledger-Stands (nicht eines leeren fired_map)."""
    tid = row["id"]
    if defn is None:
        store.set_next_timer(tid, None)
        return
    runtime = row.get("runtime") or {}
    phase = pr.current_phase(defn, runtime)
    if phase is None or pr.is_terminal(runtime):
        store.set_next_timer(tid, None)
        row["next_timer_due_at"] = None
        return
    ent = entered_at(runtime)
    if not ent:
        store.set_next_timer(tid, None)
        row["next_timer_due_at"] = None
        return
    epoch = int(runtime.get("epoch", 0))
    paused = int(runtime.get("sla_paused_ms", 0))
    fmap = fires.fired_map(tid, phase.key, epoch)
    nd = pa.compute_next_timer_due(phase, ent, paused, fmap, extra=defn.automations)
    value = nd.isoformat() if nd else None
    store.set_next_timer(tid, value)
    row["next_timer_due_at"] = value


# ── Phasenübergang ────────────────────────────────────────────────────────────

def transition(row: dict, defn: ProcessDefinition, *, expected_rev: Optional[int] = None,
               now_iso: Optional[str] = None, actor: Optional[dict] = None,
               _depth: int = 0) -> str:
    """Aktuelle Phase abschließen und die nächste betreten:
    on_exit → advance (persistiert) → on_enter → Timer neu stempeln.
    Ein von on_enter ausgelöstes auto_advance wird (begrenzt) weiterverfolgt.
    Gibt den neuen Ticket-Status zurück.

    `actor` (optional) landet im Verlauf. Ohne Angabe gilt der Übergang als
    System-Aktion – so wie beim Scheduler und bei verketteten auto_advance."""
    now_iso = now_iso or utcnow_iso()
    old_phase = pr.current_phase(defn, row.get("runtime") or {})
    if old_phase is not None:
        # Fortlaufende Nummern, die mit dem Abschluss DIESER Phase fällig werden,
        # vor dem Übergang vergeben – bewusst NICHT über fire(): dort wird jede
        # Action-Exception weggefangen, ein erschöpfter Nummernkreis würde den
        # Auftrag stillschweigend ohne Nummer weiterschalten. Hier bricht der
        # Fehler den Übergang ab (API → 4xx, Scheduler → Backoff).
        vergeben = sequences.assign_due_sequences(defn, row, old_phase, actor=actor,
                                                  store=store)
        if vergeben and expected_rev is not None:
            # Die Vergabe hat selbst (rev-geschützt) geschrieben – sonst kollidierte
            # der Übergang gleich mit der eigenen Nummern-Schreibung.
            expected_rev = row.get("rev")
        run_inline(row, defn, old_phase, {TriggerType.on_exit})

    # Werte mitgeben: die neue Phase entscheidet damit, WELCHE Fachabteilungen
    # beteiligt sind (bedingte Regeln werden erst beim Eintritt ausgewertet).
    runtime, status = pr.advance(defn, row.get("runtime") or {}, now_iso,
                                 row.get("values") or {})
    fresh = store.update_runtime(row["id"], runtime_json=json.dumps(runtime, ensure_ascii=False),
                                 status=status, expected_rev=expected_rev)
    if fresh:
        row.update(fresh)
    else:
        row["runtime"], row["status"] = runtime, status

    # Endzustand erreicht → Durchsatz-Zähler. pr.advance ist der EINZIGE Weg nach
    # „archived", deshalb genügt diese eine Stelle.
    if status == "archived":
        from backend.metrics.process_metrics import record_process_terminal
        record_process_terminal("archived")

    new_phase = pr.current_phase(defn, row.get("runtime") or {})
    # Verlauf: Phasenwechsel ist das wichtigste Ereignis am Auftrag. Details
    # tragen nur Phasen-Keys, keine Feldwerte – also nichts zu redigieren.
    ev_details = {"from_phase": old_phase.key if old_phase else None,
                  "to_phase": new_phase.key if new_phase else None,
                  "status": row.get("status", status)}
    if actor is not None:
        events.record(row, events.ADVANCED,
                      actor_id=actor.get("id"),
                      actor_name=(actor.get("displayName") or actor.get("email")
                                  or actor.get("id") or "—"),
                      phase_key=ev_details["from_phase"], details=ev_details)
    else:
        events.system(row, events.ADVANCED, phase_key=ev_details["from_phase"],
                      details={**ev_details, "auto": True})

    # Zuständige Stelle automatisch informieren – ohne das erfährt niemand, dass
    # Arbeit ansteht (das Alt-System hat an sechs Stellen gemailt). Abschaltbar
    # je Phase über responsibility.notifyOnEnter.
    if new_phase is not None:
        try:
            recips = actions.notify_phase_entry(row, defn, new_phase, sender=SENDER)
            if recips:
                record_audit(
                    action="process_phase_notified", actor_id=None, actor_name="System",
                    actor_type="system", entity_type="process_ticket", entity_id=str(row["id"]),
                    summary=f"Phase „{new_phase.label or new_phase.key}“ – "
                            f"{len(recips)} Empfänger benachrichtigt",
                    details={"phase": new_phase.key, "recipients": recips},
                )
        except Exception:
            logger.exception("Phasen-Benachrichtigung für #%s fehlgeschlagen", row.get("id"))

    wants_advance = run_inline(row, defn, new_phase, {TriggerType.on_enter})
    restamp(row, defn)

    if wants_advance and not pr.is_terminal(row.get("runtime") or {}):
        if _depth + 1 >= MAX_CHAINED_ADVANCES:
            logger.error("auto_advance-Kette für Ticket #%s abgebrochen (Tiefe %s)",
                         row.get("id"), _depth + 1)
            return row.get("status", status)
        return transition(row, defn, now_iso=now_iso, _depth=_depth + 1)
    return row.get("status", status)
