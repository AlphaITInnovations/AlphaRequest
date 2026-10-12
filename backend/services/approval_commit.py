"""Freigabe-Entscheidung festschreiben + Wirkung auslösen – GETEILT zwischen dem
öffentlichen Mail-Link-Endpunkt (api/v1/process_approval) und dem externen
Approval-Relay-Worker (services/approval_poller).

Die Entscheidungs-Semantik (Reihenfolge Persist→Wirkung, Rücksprung/Ablehnung,
Verlauf/Audit) darf zwischen beiden Wegen NICHT divergieren – deshalb genau EINE
Stelle. Der sicherheitskritische Kern (Token-Guard, Einmaligkeit, Epoch) liegt in
services/process_approval und wird hier nur ANGEWENDET.

DB/Engine/Events/Audit sind injizierbar (wie process_approval.py DB-frei bleibt):
der Endpunkt reicht seine – in Tests monkeypatchbaren – Modul-Referenzen herein,
der Worker die echten (Default). Gibt (status, row) zurück; status ∈
{approved, rejected, sent_back}. Wirft:
  * seq.SequenceError  – Approve: Entscheidung IST gebucht, nur der Übergang
    scheitert (z. B. erschöpfter Nummernkreis) → Aufrufer meldet/ackt, re-run ist
    idempotent;
  * store.ProcessTicketConflict – Persist-Konflikt, Entscheidung NICHT gebucht →
    Aufrufer behandelt als vorübergehend (erneut versuchen);
  * pa.ApprovalError – inkonsistenter Rücksprung (gepinnte Definition).
"""
import json
from typing import Optional

from backend.database import process_tickets as _store
from backend.database.audit_log import record_audit as _record_audit
from backend.schemas.process_definition import TriggerType
from backend.services import process_actions as _pactions
from backend.services import process_approval as pa
from backend.services import process_engine as _engine
from backend.services import process_events as _events
from backend.services import process_runtime as pr
from backend.utils.logger import logger
from backend.utils.timeutil import utcnow_iso


def _persist_decision(store, row: dict, runtime: dict, values: Optional[dict]) -> dict:
    """Entscheidung festschreiben, BEVOR sie wirkt (Einmaligkeit). Zwei rev-
    geschützte Schreibvorgänge: Runtime zuerst (trägt die Sperre), dann die
    Feldwerte. `next_timer_due_at` wird durchgereicht, sonst nullt update_runtime
    den Timer."""
    fresh = store.update_runtime(
        row["id"], runtime_json=json.dumps(runtime, ensure_ascii=False),
        status=row["status"], next_timer_due_at=row.get("next_timer_due_at"),
        expected_rev=row.get("rev"))
    row = dict(fresh) if fresh else row
    if values is not None:
        fresh = store.update_values(row["id"], json.dumps(values, ensure_ascii=False),
                                    expected_rev=row.get("rev"))
        row = dict(fresh) if fresh else row
    return row


def _extra_details(via: str, metadata: Optional[dict]) -> dict:
    out: dict = {"via": via}
    if metadata:
        # Ein Link ist eine Berechtigung, kein Identitätsnachweis – IP/User-Agent/
        # Hostname belegen keine Person. Deshalb ausdrücklich als unverifiziert.
        out["klick_metadaten"] = metadata
        out["metadaten_unverifiziert"] = True
    return out


def commit_decision(row: dict, defn, idx: int, phase, spec, *, act: str,
                    reason: Optional[str], now_iso: Optional[str] = None,
                    by: Optional[str] = None, by_name: str = pa.ACTOR_NAME,
                    via: str = "mail_link", metadata: Optional[dict] = None,
                    store=None, engine=None, events=None,
                    pactions=None, record_audit=None):
    # Abhängigkeiten zur AUFRUFZEIT auflösen (Default = Modul-Globals): so wirkt ein
    # monkeypatch der Modul-Globals in Tests, und der Endpunkt reicht trotzdem seine
    # eigenen (monkeypatchbaren) Referenzen herein. Default-Parameter würden die
    # Original-Module bei Funktionsdefinition einfrieren.
    store = store if store is not None else _store
    engine = engine if engine is not None else _engine
    events = events if events is not None else _events
    pactions = pactions if pactions is not None else _pactions
    record_audit = record_audit if record_audit is not None else _record_audit
    now = now_iso or utcnow_iso()
    folge, ziel = pa.follow_up(spec) if act == pa.REJECT else ("advance", None)

    runtime, values = pa.apply_decision(row, spec, idx, act=act, reason=reason,
                                        now_iso=now, by=by, by_name=by_name)
    row = _persist_decision(store, row, runtime, values)

    extra = _extra_details(via, metadata)
    # Verlauf: Begründung nur, wenn sie NICHT in ein Feld geschrieben wurde (§5.1).
    events.system(row, pa.EVENT_DECIDED, actor_name=by_name, phase_key=phase.key,
                  body=(None if spec.reasonField else reason),
                  details={"act": act, "follow_up": folge,
                           "reason_in_field": bool(spec.reasonField and reason), **extra})
    record_audit(action="process_approval_decided", actor_id=by, actor_name=by_name,
                 actor_type="system", entity_type="process_ticket",
                 entity_id=str(row.get("id")),
                 summary=f"Freigabe „{phase.label or phase.key}“: {act}",
                 details={"phase": phase.key, "act": act, "follow_up": folge,
                          "target_phase": ziel,
                          "epoch": (row.get("runtime") or {}).get("epoch"), **extra})

    if act == pa.APPROVE:
        # NIE pr.advance direkt: nur die Engine lässt on_exit/on_enter, die
        # Benachrichtigung der nächsten Stelle und das Neustempeln der Timer laufen.
        engine.transition(row, defn, expected_rev=row.get("rev"))
        return "approved", row
    if folge == "send_back":
        return "sent_back", _send_back(store, engine, pactions, events, row, defn,
                                       phase, ziel, reason, now, by_name, via)
    return "rejected", _reject(store, pactions, events, row, defn, phase, reason,
                               by_name, via)


def _reject(store, pactions, events, row, defn, phase, reason, by_name, via) -> dict:
    runtime = pr.reject(row["runtime"])
    fresh = store.update_runtime(row["id"],
                                 runtime_json=json.dumps(runtime, ensure_ascii=False),
                                 status="rejected", expected_rev=row.get("rev"))
    if fresh:
        row = dict(fresh)
    events.system(row, events.REJECTED, actor_name=by_name, phase_key=phase.key,
                  details={"via": via})
    try:
        pactions.notify_rejection(row, defn, reason=reason, by_name=by_name)
    except Exception:
        logger.exception("Ablehnungs-Mail für #%s fehlgeschlagen", row.get("id"))
    return row


def _send_back(store, engine, pactions, events, row, defn, phase, ziel, reason,
               now, by_name, via) -> dict:
    try:
        runtime, status = pr.send_back(defn, row["runtime"], now, ziel or "",
                                       row.get("values") or {})
    except ValueError as exc:
        raise pa.ApprovalError("error", str(exc))
    fresh = store.update_runtime(row["id"],
                                 runtime_json=json.dumps(runtime, ensure_ascii=False),
                                 status=status, expected_rev=row.get("rev"))
    if fresh:
        row = dict(fresh)
    ziel_phase = pr.current_phase(defn, row.get("runtime") or {})
    events.system(row, pa.EVENT_SENT_BACK, actor_name=by_name, phase_key=phase.key,
                  details={"to_phase": ziel, "via": via})
    # Zielphase wird ERNEUT betreten: on_enter-Automationen + Timer müssen laufen.
    engine.run_inline(row, defn, ziel_phase, {TriggerType.on_enter})
    try:
        pactions.notify_sent_back(row, defn, ziel_phase, reason=reason, by_name=by_name)
    except Exception:
        logger.exception("Nachbesserungs-Mail für #%s fehlgeschlagen", row.get("id"))
    try:
        engine.restamp(row, defn)
    except Exception:
        logger.exception("Timer-Stempel nach Rücksprung von #%s fehlgeschlagen",
                         row.get("id"))
    return row
