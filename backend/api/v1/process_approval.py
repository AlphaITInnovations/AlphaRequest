"""
Öffentlicher (unauthentifizierter) Freigabe-Endpunkt für Prozess-Aufträge.

Die JA/NEIN-Knöpfe der Freigabe-Mail zeigen auf
`/api/v1/process-freigabe?token=…`. Bewusst ZWEISTUFIG:

  * **GET** rendert nur eine Bestätigungsseite mit der Frage und beiden
    Antwort-Knöpfen. KEIN Seiteneffekt – Mail-Clients und Sicherheits-Scanner
    laden Links vorab; im Alt-System hätte das eine Einstellung ungewollt
    freigegeben.
  * **POST** trifft die Entscheidung.

Die Seite bietet beide Antworten an, egal welcher Link angeklickt wurde: die
Mail enthält ohnehin beide Tokens, und ein Fehlklick soll nicht in eine falsche
Entscheidung münden. Das Token autorisiert also „entscheiden über (Auftrag,
Phase, Durchlauf)“; die Richtung kommt aus dem Formular.

Der Endpunkt ist die einzige Stelle im Prozess-System ohne angemeldete Person.
Er hält sich deshalb streng an die Regel „nur was im Token steht“: Ticket-ID,
Phase und Epoch werden gegen den echten Zustand geprüft (siehe
services/process_approval.py), und die Wirkung läuft über dieselben Wege wie im
angemeldeten Fall (`engine.transition`, `pr.reject`, `pr.send_back`).
"""
import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from backend.database import process_definitions as defstore
from backend.database import process_tickets as store
from backend.database.audit_log import record_audit
from backend.schemas.process_definition import ProcessDefinition, TriggerType
from backend.services import process_actions as pactions
from backend.services import process_approval as pa
from backend.services import process_engine as engine
from backend.services import process_events as events
from backend.services import process_runtime as pr
from backend.services import process_sequences as seq
from backend.utils.logger import logger
from backend.utils.timeutil import utcnow_iso

router = APIRouter()

# Eigene Templates-Instanz statt `request.app.templates`: der Endpunkt soll ohne
# die komplette App (und damit ohne DB) testbar bleiben.
_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))

CONFIRM_TEMPLATE = "process_approval.html"
RESULT_TEMPLATE = "process_approval_result.html"


# ── Rendern ───────────────────────────────────────────────────────────────────

def _result(request: Request, status: str, *, message: str = "",
            row: Optional[dict] = None) -> HTMLResponse:
    """Ergebnis-/Hinweisseite. Immer 200: ein abgelaufener oder schon benutzter
    Link ist kein Server-Fehler, und eine 5xx-Seite im Postfach hilft niemandem."""
    return _TEMPLATES.TemplateResponse(request, RESULT_TEMPLATE, {
        "status": status,
        "message": message,
        "titel": (row or {}).get("title"),
        "auftrag_id": (row or {}).get("id"),
    })


def _confirm(request: Request, *, token: str, row: dict, phase, spec,
             act: str, reason: str = "", fehler: str = "") -> HTMLResponse:
    return _TEMPLATES.TemplateResponse(request, CONFIRM_TEMPLATE, {
        "token": token,
        "post_url": request.url.path,
        "titel": row.get("title"),
        "auftrag_id": row.get("id"),
        "phase_label": (phase.label or phase.key),
        "frage": spec.question,
        "approve_label": spec.approveLabel,
        "reject_label": spec.rejectLabel,
        "require_reason": spec.requireReason,
        "vorauswahl": act,
        "reason": reason,
        "fehler": fehler,
    })


# ── Laden & Prüfen ────────────────────────────────────────────────────────────

def _pinned_defn(row: dict) -> ProcessDefinition:
    d = defstore.get_definition(row["process_key"], row["process_version"])
    if not d or not d.get("definition"):
        raise pa.ApprovalError("invalid", "Die Prozess-Definition dieses Auftrags "
                                          "ist nicht mehr auffindbar")
    return ProcessDefinition.model_validate(d["definition"])


def _load(token: str):
    """Token → (row, defn, payload, index, phase, spec). Wirft ApprovalError.

    Reihenfolge mit Absicht: erst Signatur, dann Ablauf, dann Zustand. „Der Link
    ist abgelaufen“ ist eine Eigenschaft des Links – die Antwort darf nicht davon
    abhängen, ob der Auftrag inzwischen weitergelaufen ist.
    """
    payload, issued_at = pa.require_token(token)
    row = store.get(int(payload["tid"]))
    if not row:
        raise pa.ApprovalError("invalid", "Diesen Auftrag gibt es nicht mehr")
    defn = _pinned_defn(row)

    spec_fuer_alter = pa.approval_spec_for(defn, payload["phase"])
    if spec_fuer_alter is None:
        raise pa.ApprovalError("invalid", "Diese Phase ist keine Freigabe")
    pa.assert_fresh(issued_at, spec_fuer_alter)

    idx, phase, spec = pa.approval_context(row, defn, payload)
    return row, defn, payload, idx, phase, spec


# ── Endpunkte ─────────────────────────────────────────────────────────────────

@router.get("/process-freigabe", response_class=HTMLResponse)
def show_approval(request: Request, token: str = Query("")):
    """Bestätigungsseite. Ändert NICHTS – auch nicht bei mehrfachem Aufruf."""
    try:
        row, _defn, payload, _idx, phase, spec = _load(token)
    except pa.ApprovalError as exc:
        return _result(request, exc.code, message=exc.message)
    return _confirm(request, token=token, row=row, phase=phase, spec=spec,
                    act=payload["act"])


@router.post("/process-freigabe", response_class=HTMLResponse)
def submit_approval(request: Request, token: str = Form(""), act: str = Form(""),
                    reason: str = Form("")):
    """Die eigentliche Entscheidung."""
    try:
        row, defn, _payload, idx, phase, spec = _load(token)
    except pa.ApprovalError as exc:
        return _result(request, exc.code, message=exc.message)

    try:
        act = pa.normalize_action(act)
    except pa.ApprovalError as exc:
        return _result(request, exc.code, message=exc.message)
    try:
        grund = pa.normalize_reason(spec, act, reason)
    except pa.ApprovalError as exc:
        # Reparierbarer Eingabefehler → zurück auf die Bestätigungsseite, nicht
        # auf eine Sackgasse.
        return _confirm(request, token=token, row=row, phase=phase, spec=spec,
                        act=act, reason=reason, fehler=exc.message)

    try:
        return _decide(request, row, defn, idx, phase, spec, act=act, grund=grund)
    except store.ProcessTicketConflict:
        # Jemand war schneller (Bearbeitung im System oder ein zweiter Klick).
        return _result(request, "already",
                       message="Der Auftrag wurde zwischenzeitlich geändert – "
                               "die Entscheidung wurde nicht übernommen.",
                       row=row)
    except pa.ApprovalError as exc:
        return _result(request, exc.code, message=exc.message, row=row)
    except Exception:
        logger.exception("Freigabe per Mail-Link für #%s fehlgeschlagen", row.get("id"))
        return _result(request, "error",
                       message="Die Entscheidung konnte nicht gespeichert werden. "
                               "Bitte wenden Sie sich an die IT.",
                       row=row)


# ── Wirkung ───────────────────────────────────────────────────────────────────

def _persist_decision(row: dict, runtime: dict, values: Optional[dict]) -> dict:
    """Entscheidung festschreiben, BEVOR sie wirkt (Einmaligkeit).

    Zwei Schreibvorgänge, beide mit rev-Guard: Runtime zuerst (der trägt die
    Sperre), danach die Feldwerte. `next_timer_due_at` wird ausdrücklich
    durchgereicht – ohne das würde `update_runtime` den Timer auf NULL setzen.
    """
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


def _audit(row: dict, phase, act: str, folge: str, ziel: Optional[str]) -> None:
    record_audit(
        action="process_approval_decided", actor_id=None, actor_name=pa.ACTOR_NAME,
        actor_type="system", entity_type="process_ticket", entity_id=str(row.get("id")),
        summary=f"Freigabe „{phase.label or phase.key}“ per Mail-Link: {act}",
        details={"phase": phase.key, "act": act, "follow_up": folge,
                 "target_phase": ziel, "epoch": (row.get("runtime") or {}).get("epoch")},
    )


def _decide(request: Request, row: dict, defn: ProcessDefinition, idx: int, phase,
            spec, *, act: str, grund: Optional[str]) -> HTMLResponse:
    now = utcnow_iso()
    folge, ziel = pa.follow_up(spec) if act == pa.REJECT else ("advance", None)

    runtime, values = pa.apply_decision(row, spec, idx, act=act, reason=grund,
                                        now_iso=now)
    row = _persist_decision(row, runtime, values)

    # Verlauf: OHNE handelnde Person (im Token steht keine Identität) – der
    # Eintrag nennt deshalb den Kanal. Die Begründung steht nur dann im Eintrag,
    # wenn sie NICHT in ein Feld geschrieben wurde; sonst wäre der Verlauf ein
    # Zweitkanal an der Feld-Sichtbarkeit vorbei (§5.1).
    events.system(row, pa.EVENT_DECIDED, actor_name=pa.ACTOR_NAME,
                  phase_key=phase.key,
                  body=(None if spec.reasonField else grund),
                  details={"act": act, "via": "mail_link", "follow_up": folge,
                           "reason_in_field": bool(spec.reasonField and grund)})
    _audit(row, phase, act, folge, ziel)

    if act == pa.APPROVE:
        # NIEMALS pr.advance direkt: nur die Engine lässt on_exit/on_enter, die
        # Benachrichtigung der nächsten Stelle und das Neustempeln der Timer laufen.
        try:
            engine.transition(row, defn, expected_rev=row.get("rev"))
        except seq.SequenceError as exc:
            # Die Freigabe IST verbucht (steht schon im Runtime), nur der Übergang
            # scheitert – z. B. weil der Nummernkreis erschöpft ist. Das gehört als
            # verständliche Seite an die entscheidende Person, nicht als Traceback.
            logger.error("Freigabe #%s: Nummern-Vergabe fehlgeschlagen: %s",
                         row.get("id"), exc)
            return _result(request, "error", message=str(exc), row=row)
        return _result(request, "approved", row=row)

    if folge == "send_back":
        return _send_back(request, row, defn, phase, ziel, grund=grund, now=now)
    return _reject(request, row, defn, phase, grund=grund)


def _reject(request: Request, row: dict, defn: ProcessDefinition, phase,
            *, grund: Optional[str]) -> HTMLResponse:
    runtime = pr.reject(row["runtime"])
    fresh = store.update_runtime(row["id"],
                                 runtime_json=json.dumps(runtime, ensure_ascii=False),
                                 status="rejected", expected_rev=row.get("rev"))
    if fresh:
        row = dict(fresh)
    events.system(row, events.REJECTED, actor_name=pa.ACTOR_NAME,
                  phase_key=phase.key, details={"via": "mail_link"})
    try:
        pactions.notify_rejection(row, defn, reason=grund, by_name=pa.ACTOR_NAME)
    except Exception:
        logger.exception("Ablehnungs-Mail für #%s fehlgeschlagen", row.get("id"))
    return _result(request, "rejected", row=row)


def _send_back(request: Request, row: dict, defn: ProcessDefinition, phase,
               ziel: Optional[str], *, grund: Optional[str], now: str) -> HTMLResponse:
    try:
        runtime, status = pr.send_back(defn, row["runtime"], now, ziel or "",
                                       row.get("values") or {})
    except ValueError as exc:
        # Das Schema prüft `back_to:` beim Veröffentlichen – hier kann das nur
        # noch an einer inkonsistenten gepinnten Definition liegen.
        raise pa.ApprovalError("error", str(exc))
    fresh = store.update_runtime(row["id"],
                                 runtime_json=json.dumps(runtime, ensure_ascii=False),
                                 status=status, expected_rev=row.get("rev"))
    if fresh:
        row = dict(fresh)
    ziel_phase = pr.current_phase(defn, row.get("runtime") or {})
    events.system(row, pa.EVENT_SENT_BACK, actor_name=pa.ACTOR_NAME,
                  phase_key=phase.key,
                  details={"to_phase": ziel, "via": "mail_link"})

    # Die Zielphase wird ERNEUT betreten: on_enter-Automationen und Timer müssen
    # laufen, sonst wartet die Stelle auf nichts.
    engine.run_inline(row, defn, ziel_phase, {TriggerType.on_enter})
    try:
        pactions.notify_sent_back(row, defn, ziel_phase, reason=grund,
                                  by_name=pa.ACTOR_NAME)
    except Exception:
        logger.exception("Nachbesserungs-Mail für #%s fehlgeschlagen", row.get("id"))
    try:
        engine.restamp(row, defn)
    except Exception:
        logger.exception("Timer-Stempel nach Rücksprung von #%s fehlgeschlagen",
                         row.get("id"))
    return _result(request, "sent_back", row=row,
                   message=f"Der Auftrag liegt wieder in der Phase "
                           f"„{(ziel_phase.label or ziel_phase.key) if ziel_phase else ziel}“.")
