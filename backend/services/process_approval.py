"""
Freigabe per Mail-Link (`PhaseKind.approval`): Token, Phasen-Guard, Entscheidung.

Die entscheidende Person arbeitet nicht zwingend im System – deshalb trägt die
Freigabe-Mail zwei signierte Links. Zustandslos wie im Alt-System (itsdangerous,
SECRET_KEY, kein Token-Tabelle), aber an drei Stellen bewusst anders:

1. **Kein Seiteneffekt im GET.** Der Link führt nur auf eine Bestätigungsseite;
   entschieden wird per POST. Mail-Clients und Sicherheits-Scanner laden Links
   vorab – im Alt-System hätte das eine Einstellung ungewollt freigegeben.
2. **Epoch im Token.** Payload ist {tid, act, phase, epoch}. Nach einer
   Wiederaufnahme oder einem Rücksprung (beide erhöhen `runtime["epoch"]`) ist
   ein alter, formal noch nicht abgelaufener Link wirkungslos.
3. **Echte Einmaligkeit.** Die Entscheidung steht im Runtime der Phase
   (`pr.set_phase_decision`), nicht im Ticket-Status. Ein zweiter Klick trifft
   auf „bereits bearbeitet“ statt auf einen neuen Phasenwechsel.

Alles hier ist DB-frei: `row` und `defn` reicht der Aufrufer herein.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from backend.schemas.process_definition import (
    ApprovalSpec, PhaseDef, PhaseKind, ProcessDefinition,
)
from backend.services import process_runtime as pr
from backend.services.iso_duration import parse_duration
from backend.utils.config import config

#: Eigener Salt. Gleicher SECRET_KEY wie das Alt-System, aber getrennter
#: Wirkungsraum: ein „freigabe-v1“-Token darf hier nicht gelten und umgekehrt.
SALT = "process-approval-v1"

APPROVE = "approve"
REJECT = "reject"
ACTIONS = (APPROVE, REJECT)

#: Präfix von approval.onReject für den Rücksprung (Schema validiert die Form).
BACK_TO_PREFIX = "back_to:"

#: Die Begründung kommt aus einem offenen Formular ohne Anmeldung – begrenzen,
#: bevor sie in values_json/Verlauf landet (gleiche Grenze wie Nachträge).
MAX_REASON_LEN = 5000

#: Verlaufs-Aktionen dieses Wegs. Kanonische Namen gehören eigentlich nach
#: process_events; solange sie dort fehlen, stehen sie hier an EINER Stelle.
EVENT_DECIDED = "approval_decided"
EVENT_SENT_BACK = "approval_sent_back"
EVENT_NO_RECIPIENT = "approval_no_recipient"

#: Es gibt keine angemeldete Person – im Token steht keine Identität. Der Verlauf
#: nennt deshalb den KANAL statt einen Namen zu erfinden.
ACTOR_NAME = "Freigabe per Mail-Link (ohne Anmeldung)"


class ApprovalError(Exception):
    """Fachlicher Abbruch mit einem Code, den die Ergebnisseite versteht.

    Codes: invalid · expired · superseded · closed · already · reason_required ·
    reason_too_long
    """

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


# ── Token ─────────────────────────────────────────────────────────────────────

def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(config.SECRET_KEY, salt=SALT)


def make_token(ticket_id, action: str, phase_key: str, epoch: int) -> str:
    """Signiertes Token für genau eine Entscheidung in genau einem Durchlauf."""
    if action not in ACTIONS:
        raise ValueError(f"Ungültige Aktion: {action!r}")
    return _serializer().dumps({"tid": int(ticket_id), "act": action,
                                "phase": str(phase_key), "epoch": int(epoch)})


def _shape_ok(data) -> bool:
    return (isinstance(data, dict)
            and isinstance(data.get("tid"), int)
            and data.get("act") in ACTIONS
            and isinstance(data.get("phase"), str) and data["phase"]
            and isinstance(data.get("epoch"), int))


def require_token(token: str) -> tuple[dict, datetime]:
    """Signatur und Form prüfen; gibt (payload, Ausstellungszeit) zurück.

    Das ALTER wird hier NICHT geprüft: die zulässige Gültigkeit steht in
    `approval.linkMaxAge`, und dafür braucht man erst die Definition – die man
    ohne die Ticket-ID aus dem Token nicht laden kann. Zweiter Schritt:
    `assert_fresh`.
    """
    if not token:
        raise ApprovalError("invalid", "Es wurde kein Freigabe-Link übergeben")
    try:
        data, issued_at = _serializer().loads(token, return_timestamp=True)
    except SignatureExpired:                      # Unterklasse von BadSignature
        raise ApprovalError("expired", "Dieser Freigabe-Link ist abgelaufen")
    except BadSignature:
        raise ApprovalError("invalid", "Dieser Freigabe-Link ist ungültig")
    except Exception:
        raise ApprovalError("invalid", "Dieser Freigabe-Link ist ungültig")
    if not _shape_ok(data):
        raise ApprovalError("invalid", "Dieser Freigabe-Link ist ungültig")
    return ({"tid": data["tid"], "act": data["act"],
             "phase": data["phase"], "epoch": data["epoch"]}, issued_at)


def max_age_seconds(spec: ApprovalSpec) -> int:
    """Gültigkeitsdauer aus `approval.linkMaxAge` (Schema hat sie schon geprüft)."""
    return parse_duration(spec.linkMaxAge)


def assert_fresh(issued_at: datetime, spec: ApprovalSpec,
                 now: Optional[datetime] = None) -> None:
    """Alter des Tokens gegen `approval.linkMaxAge` prüfen."""
    now = now or datetime.now(timezone.utc)
    if issued_at.tzinfo is None:
        issued_at = issued_at.replace(tzinfo=timezone.utc)
    if now - issued_at > timedelta(seconds=max_age_seconds(spec)):
        raise ApprovalError("expired", "Dieser Freigabe-Link ist abgelaufen")


def load_token(token: str, *, max_age: Optional[int] = None) -> Optional[dict]:
    """Bequeme Variante für Aufrufer, die nur „gültig oder nicht“ wissen wollen."""
    try:
        payload, issued_at = require_token(token)
    except ApprovalError:
        return None
    if max_age is not None:
        if issued_at.tzinfo is None:
            issued_at = issued_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - issued_at > timedelta(seconds=max_age):
            return None
    return payload


# ── Phasen-Guard ──────────────────────────────────────────────────────────────

def approval_spec_for(defn: ProcessDefinition, phase_key: str) -> Optional[ApprovalSpec]:
    """Freigabe-Block der genannten Phase (unabhängig vom aktuellen Stand).

    Wird für die Ablauf-Prüfung gebraucht: „abgelaufen“ ist eine Eigenschaft des
    Links, nicht des Auftragszustands – die Antwort darf nicht davon abhängen,
    ob der Auftrag inzwischen weitergelaufen ist.
    """
    for p in defn.phases:
        if p.key == phase_key:
            return p.approval
    return None


def approval_context(row: dict, defn: ProcessDefinition,
                     payload: dict) -> tuple[int, PhaseDef, ApprovalSpec]:
    """Gilt dieses Token JETZT für diesen Auftrag? Wirft sonst ApprovalError.

    Geprüft wird in dieser Reihenfolge: richtiges Ticket · nicht terminal ·
    genau diese Phase ist aktiv · richtiger Durchlauf (Epoch) · es ist wirklich
    eine Freigabe-Phase · es wurde noch nicht entschieden.
    """
    if int(payload.get("tid", -1)) != int(row.get("id", -2)):
        raise ApprovalError("invalid", "Der Link gehört nicht zu diesem Auftrag")

    runtime = row.get("runtime") or {}
    if pr.is_terminal(runtime) or row.get("status") in ("archived", "rejected"):
        raise ApprovalError("closed", "Dieser Auftrag ist bereits abgeschlossen "
                                      "oder abgelehnt")

    phase = pr.current_phase(defn, runtime)
    if phase is None or phase.key != payload.get("phase"):
        raise ApprovalError("closed", "Dieser Auftrag steht nicht mehr in dieser "
                                      "Freigabe")
    if int(runtime.get("epoch", 0)) != int(payload.get("epoch", -1)):
        raise ApprovalError("superseded", "Der Auftrag wurde zwischenzeitlich neu "
                                          "gestartet – bitte den aktuellen Link "
                                          "aus der neuesten Mail verwenden")
    if phase.kind != PhaseKind.approval or phase.approval is None:
        raise ApprovalError("invalid", "Diese Phase ist keine Freigabe")

    idx = int(runtime.get("current_index", 0))
    if pr.phase_decision(runtime, idx) is not None:
        raise ApprovalError("already", "Über diesen Auftrag wurde bereits entschieden")
    return idx, phase, phase.approval


# ── Entscheidung ──────────────────────────────────────────────────────────────

def normalize_action(act: Optional[str]) -> str:
    if act not in ACTIONS:
        raise ApprovalError("invalid", "Unbekannte Entscheidung")
    return act


def normalize_reason(spec: ApprovalSpec, act: str, reason: Optional[str]) -> Optional[str]:
    """Begründung prüfen/trimmen. None heißt „keine angegeben“."""
    text = (reason or "").strip()
    if act == REJECT and spec.requireReason and not text:
        raise ApprovalError("reason_required",
                            "Bitte begründen Sie die Ablehnung")
    if len(text) > MAX_REASON_LEN:
        raise ApprovalError("reason_too_long",
                            f"Die Begründung darf höchstens {MAX_REASON_LEN} "
                            f"Zeichen lang sein")
    return text or None


def follow_up(spec: ApprovalSpec) -> tuple[str, Optional[str]]:
    """Was folgt auf ein NEIN? ("reject", None) oder ("send_back", <phase_key>)."""
    if spec.onReject.startswith(BACK_TO_PREFIX):
        return "send_back", spec.onReject[len(BACK_TO_PREFIX):]
    return "reject", None


def decision_values(spec: ApprovalSpec, values: dict, *, act: str,
                    reason: Optional[str]) -> dict:
    """Entscheidung/Begründung in die konfigurierten Feldwerte schreiben.

    Geschrieben wird der ROHE Aktionsname (approve/reject), nicht die
    Beschriftung: Beschriftungen sind Anzeigetext und dürfen sich mit einer
    neuen Prozess-Version ändern, ausgewertet wird aber der Feldwert.
    """
    out = dict(values or {})
    if spec.decisionField:
        out[spec.decisionField] = act
    if spec.reasonField and reason is not None:
        out[spec.reasonField] = reason
    return out


def apply_decision(row: dict, spec: ApprovalSpec, index: int, *, act: str,
                   reason: Optional[str], now_iso: str,
                   by_name: str = ACTOR_NAME) -> tuple[dict, Optional[dict]]:
    """Entscheidung festschreiben: Runtime-Eintrag + optionale Feldwerte.

    Gibt (runtime, values) zurück; `values` ist None, wenn sich durch
    decisionField/reasonField nichts geändert hat – dann spart sich der Aufrufer
    einen Schreibvorgang.

    Reihenfolge im Aufrufer: ERST das hier persistieren, DANN die Wirkung
    (Weiterschalten/Ablehnen/Rücksprung) auslösen. Bricht etwas dazwischen ab,
    ist der Auftrag „entschieden, aber nicht weitergeschaltet“ – das kann ein
    Mensch korrigieren. Umgekehrt wäre eine Doppel-Ausführung möglich.
    """
    runtime = pr.set_phase_decision(
        row.get("runtime") or {}, index, act=act, by=None, by_name=by_name,
        at=now_iso,
        # Steht die Begründung in einem Feld, gehört sie NICHT zusätzlich in den
        # Runtime – der geht ungefiltert an jede Person mit Leserecht (§5.1).
        reason=(None if spec.reasonField else reason),
        reason_in_field=bool(spec.reasonField and reason is not None),
    )
    stored = row.get("values") or {}
    values = decision_values(spec, stored, act=act, reason=reason)
    return runtime, (values if values != stored else None)
