"""Ausgehender Abhol-Worker für den EXTERNEN Freigabe-Relay (AlphaApprove).

AlphaRequest wählt NUR raus: der Worker hängt per Long-Poll an `GET /pending`
(Bearer-API-Key), verifiziert jeden Token SELBST (maßgeblich, nicht received_at),
wendet die Entscheidung über den geteilten Kern (services/approval_commit) an und
bestätigt per `POST /ack` {ids:[…]} – erst NACH dem Commit. Kein Inbound ins
interne Netz.

Fehler-Einordnung (Vertrag):
  * PermanentError → in die Fehlerablage (Audit) + trotzdem ACK (kommt nie sinnvoll
    wieder): Signatur/iss/aud/Form/abgelaufen, Hülle≠Token, veraltete Epoch/Phase,
    Auftrag zu/unbekannt, Gegenentscheidung liegt vor.
  * alles andere (DB weg, Deadlock, rev-Konflikt) → VORÜBERGEHEND: nicht ACKen, die
    übrigen Einträge weiter verarbeiten, nach Backoff erneut (ab after=0).
Idempotent: eine bereits gebuchte, gleichlautende Entscheidung gilt als Erfolg.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from backend.database import process_definitions as defstore
from backend.database import process_tickets as store
from backend.database.audit_log import record_audit
from backend.schemas.process_definition import ProcessDefinition
from backend.services import approval_commit
from backend.services import approval_jwt
from backend.services import process_actions as pactions
from backend.services import process_approval as pa
from backend.services import process_runtime as pr
from backend.services import process_sequences as seq
from backend.services.approval_jwt import TokenInvalid, make_verifier  # noqa: F401 (Re-Export)
from backend.utils.config import config
from backend.utils.logger import logger

#: Es gibt keine angemeldete Person – der Verlauf nennt den KANAL, kein Name wird
#: erfunden. (Externer Weg, abgegrenzt vom internen Mail-Link.)
EXTERNAL_ACTOR = "Freigabe per externem Mail-Link (ohne Anmeldung)"


class PermanentError(Exception):
    """Eintrag ist dauerhaft unbrauchbar → Fehlerablage + ACK (kein Retry)."""


# ── Anwenden eines Eintrags ───────────────────────────────────────────────────

def _metadata(decision: dict) -> dict:
    return {"ip": decision.get("client_ip"), "user_agent": decision.get("user_agent"),
            "hostname": decision.get("hostname"), "lang": decision.get("lang"),
            "received_at": decision.get("received_at"), "quelle_id": decision.get("id")}


def _already_applied(row: dict, defn, claims: dict) -> bool:
    """Ist genau diese Entscheidung (Phase, Epoch, Richtung) bereits im Runtime
    gebucht? Dann ist eine erneute Zustellung idempotent. Bei abweichender Epoch
    (zwischenzeitlich neuer Durchlauf) oder abweichender Richtung (Gegen-
    entscheidung) → False (dauerhaft unbrauchbar)."""
    rt = row.get("runtime") or {}
    if int(rt.get("epoch", 0)) != int(claims.get("epoch", -1)):
        return False
    for i, p in enumerate(defn.phases):
        if p.key == claims.get("phase"):
            dec = pr.phase_decision(rt, i)
            return bool(dec and dec.get("act") == claims.get("act"))
    return False


def apply_decision_entry(claims: dict, decision: dict) -> None:
    """Verifizierte Claims + Hülle anwenden. Wirft PermanentError (dauerhaft) bzw.
    lässt vorübergehende Fehler (ProcessTicketConflict/DB) durch (→ Retry)."""
    tid = int(claims["tid"])
    act = claims["act"]
    row = store.get(tid)
    if not row:
        raise PermanentError("Auftrag unbekannt")
    d = defstore.get_definition(row["process_key"], row["process_version"])
    if not d or not d.get("definition"):
        raise PermanentError("Prozess-Definition nicht auffindbar")
    try:
        defn = ProcessDefinition.model_validate(d["definition"])
    except Exception as exc:
        # Eine gepinnte Definition, die nicht mehr validiert, bessert sich bei Retry
        # NIE – dauerhaft, sonst würde der Eintrag ewig erneut abgeholt.
        raise PermanentError(f"Prozess-Definition ungültig: {exc}")

    try:
        idx, phase, spec = pa.approval_context(row, defn, claims)
    except pa.ApprovalError as exc:
        # Idempotenz nach fehlgeschlagenem ACK: wurde GENAU diese Entscheidung
        # (Phase, Durchlauf/Epoch, Richtung) schon gebucht, gilt die erneute
        # Zustellung als Erfolg – auch wenn der Auftrag inzwischen weitergelaufen ist
        # („closed" statt „already"). Eine Gegenentscheidung oder ein neuer Durchlauf
        # (abweichende Epoch) trifft das NICHT → dauerhaft unbrauchbar.
        if _already_applied(row, defn, claims):
            return
        raise PermanentError(f"{exc.code}: {exc.message}")

    # „Freigegeben/Abgelehnt von": die zuständige Fachabteilung der Phase (z. B.
    # „FreigabeHerrLutz"), sonst der Kanal (es gibt keine angemeldete Person).
    by_name = pactions.responsible_department_name(phase, row.get("values")) or EXTERNAL_ACTOR
    try:
        # reject extern = OHNE Begründung (bewusst, Punkt 2 des Vertrags).
        approval_commit.commit_decision(
            row, defn, idx, phase, spec, act=act, reason=None,
            by_name=by_name, via="mail_link_external", metadata=_metadata(decision))
    except seq.SequenceError as exc:
        # Entscheidung IST gebucht, nur der Übergang scheitert (z. B. Nummernkreis
        # erschöpft). Re-Run wäre idempotent → hier als Erfolg (ACK), Mensch
        # korrigiert den Nummernkreis.
        logger.error("Freigabe (extern) #%s: Nummern-Vergabe fehlgeschlagen: %s", tid, exc)
        return


# ── Stapelverarbeitung ────────────────────────────────────────────────────────

def _envelope_matches(decision: dict, claims: dict) -> bool:
    return (decision.get("tid") == claims.get("tid")
            and decision.get("act") == claims.get("act")
            and decision.get("phase") == claims.get("phase")
            and decision.get("epoch") == claims.get("epoch"))


def process_batch(decisions, verify: Callable[[str], dict], apply, quarantine):
    """Jeden Eintrag EINZELN: verifizieren → Hülle abgleichen → anwenden. Gibt
    (ack_ids, retry_ids). Ein Eintrag wird NUR bestätigt, wenn er angewendet ODER
    nachweislich in der Fehlerablage gelandet ist – scheitert die Fehlerablage (Audit
    kurz weg), kommt er in retry statt verloren bestätigt zu werden. Ein kaputter
    Eintrag blockiert die anderen NICHT."""
    ack, retry = [], []

    def to_quarantine(d, reason: str) -> None:
        try:
            quarantine(d, reason)
            ack.append(d.get("id"))
        except Exception:
            logger.exception("Fehlerablage für %s fehlgeschlagen – später erneut", d.get("id"))
            retry.append(d.get("id"))

    for d in decisions:
        try:
            claims = verify(d.get("token", ""))
        except Exception as exc:                    # Signatur/iss/aud/Form/abgelaufen
            to_quarantine(d, f"Token ungültig: {exc}")
            continue
        if not _envelope_matches(d, claims):
            to_quarantine(d, "Hülle weicht vom Token ab (tid/act/phase/epoch)")
            continue
        try:
            apply(claims, d)
            ack.append(d.get("id"))
        except PermanentError as exc:
            to_quarantine(d, str(exc))
        except Exception:                           # vorübergehend (DB/Deadlock/rev)
            logger.exception("Externe Freigabe %s vorübergehend fehlgeschlagen", d.get("id"))
            retry.append(d.get("id"))
    return ack, retry


# ── Long-Poll-Schleife ────────────────────────────────────────────────────────

def run(client, base: str, api_key: str, verify, apply, quarantine, *,
        wait: int = 30, backoff: int = 5, max_backoff: int = 300,
        should_stop: Optional[Callable[[], bool]] = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic) -> None:
    """Dauerschleife: abholen → verarbeiten → bestätigen.

    Der Cursor (`after`) läuft AUCH bei Fehlern weiter – AlphaApprove liefert höchstens
    100 Einträge je Abruf; blieben die ersten 100 offen stecken, würde alles dahinter
    nie verarbeitet. Fehlgeschlagene Einträge bekommen stattdessen eine eigene,
    wachsende Wartezeit (5 s, 10 s, 20 s … bis max_backoff). Erst wenn eine
    Wiederholung fällig ist und der Vorlauf leer bleibt, wird der Cursor auf 0 gesetzt,
    um die fälligen Einträge erneut zu holen. Nach einem Neustart beginnt der Cursor
    bei 0, damit alles noch Unbestätigte erneut kommt (apply ist idempotent)."""
    headers = {"Authorization": f"Bearer {api_key}"}
    cursor = 0                                     # nach Neustart: alles Unbestätigte erneut
    retry_state: dict = {}                         # id -> (Fehlversuche, frühester nächster Versuch)

    while not (should_stop and should_stop()):
        next_due = min((due for _, due in retry_state.values()), default=None)
        poll_wait = wait if next_due is None else max(0, min(wait, int(next_due - clock())))
        try:
            resp = client.get(f"{base}/pending", params={"after": cursor, "wait": poll_wait},
                              headers=headers, timeout=poll_wait + 10)
            # Ein 5xx mit JSON-Fehlerkörper würde sonst durch resp.json() rutschen und
            # als „nichts offen" gelten → heiße Schleife. Status prüfen.
            if getattr(resp, "status_code", 200) >= 400:
                raise RuntimeError(f"/pending HTTP {resp.status_code}")
            data = resp.json()
        except Exception:
            logger.exception("Approval-Poll (/pending) fehlgeschlagen")
            sleep(backoff)
            continue

        decisions = data.get("decisions") or []
        if not decisions:
            if next_due is not None and next_due <= clock():
                cursor = 0                         # Durchgang zu Ende → fällige Wiederholungen von vorn
            else:
                sleep(backoff)                     # Drossel, falls Long-Poll/Proxy sofort leer antwortet
            continue

        now = clock()
        # Einträge, deren Wartezeit noch läuft, in diesem Durchgang überspringen (bleiben unbestätigt).
        due_now = [d for d in decisions if retry_state.get(d.get("id"), (0, 0.0))[1] <= now]
        ack, retry = process_batch(due_now, verify, apply, quarantine)

        if ack:
            try:
                r = client.post(f"{base}/ack", json={"ids": ack}, headers=headers, timeout=30)
                # Bei 5xx gilt /ack sonst als gesendet → Einträge kommen sofort wieder und
                # werden pausenlos neu bestätigt. Status prüfen, damit der Backoff greift.
                r.raise_for_status()
            except Exception:
                logger.exception("Approval-ACK fehlgeschlagen – Einträge kommen erneut")
                sleep(backoff)
                continue                           # Cursor NICHT weiter; apply ist idempotent
            for did in ack:
                retry_state.pop(did, None)

        for did in retry:
            n = retry_state.get(did, (0, 0.0))[0] + 1
            retry_state[did] = (n, now + min(backoff * 2 ** (n - 1), max_backoff))

        cursor = data.get("cursor", cursor)        # immer weiter – auch wenn auf dieser Seite etwas fehlschlug


# ── Produktions-Verdrahtung ───────────────────────────────────────────────────

def _quarantine(decision: dict, reason: str) -> None:
    """Fehlerablage = Audit-Log (durabel, kein neues Schema). KEIN try/except: scheitert
    der Audit-Eintrag (DB kurz weg), muss der Fehler nach oben – process_batch ackt den
    Eintrag dann NICHT, sondern versucht es später erneut. Sonst wäre die Entscheidung
    bei AlphaApprove als erledigt markiert und spurlos verloren."""
    logger.error("Externe Freigabe %s dauerhaft unbrauchbar: %s", decision.get("id"), reason)
    record_audit(
        action="process_approval_external_quarantined", actor_id=None,
        actor_name=EXTERNAL_ACTOR, actor_type="system", entity_type="process_ticket",
        entity_id=str(decision.get("tid")),
        summary=f"Externe Freigabe-Entscheidung verworfen: {reason}",
        details={"reason": reason, "quelle_id": decision.get("id"),
                 "tid": decision.get("tid"), "act": decision.get("act"),
                 "phase": decision.get("phase"), "epoch": decision.get("epoch"),
                 "klick_metadaten": _metadata(decision), "metadaten_unverifiziert": True})


def is_configured() -> bool:
    # Der Signierschlüssel kommt immer (DB-Schlüssel wird bei Bedarf erzeugt, oder
    # Datei-Override) – darum zählt APPROVAL_PRIVATE_KEY_PATH NICHT mehr zum Schalter.
    return bool(config.APPROVAL_BASE_URL and config.APPROVAL_API_KEY
                and config.APPROVAL_ISSUER and config.APPROVAL_AUDIENCE)


def _live_verifier():
    """Verifizierer, der den AKTUELLEN Public Key je Token auflöst (nicht einmal beim
    Start einfriert). So greift eine Schlüssel-Rotation über die Einstellungen sofort,
    ohne App-Neustart – alte Links werden danach korrekt als ungültig verworfen, neue
    (mit dem neuen Key signierte) verifizieren."""
    iss, aud = config.APPROVAL_ISSUER, config.APPROVAL_AUDIENCE
    grace = int(config.APPROVAL_MAX_PICKUP_DELAY)

    def verify(token: str) -> dict:
        return make_verifier(approval_jwt.public_key(), iss, aud,
                             clock_leeway=30, pickup_grace=grace)(token)
    return verify


def start_worker() -> Optional[threading.Thread]:
    """Den Abhol-Worker als Daemon-Thread starten, wenn der externe Relay
    konfiguriert ist. Gibt den Thread zurück (oder None)."""
    if not is_configured():
        logger.info("Externer Approval-Relay nicht konfiguriert – Worker bleibt aus")
        return None
    import requests

    verify = _live_verifier()
    base = config.APPROVAL_BASE_URL.rstrip("/")

    def loop():
        session = requests.Session()
        logger.info("Externer Approval-Worker gestartet (%s)", base)
        while True:
            try:
                run(session, base, config.APPROVAL_API_KEY, verify,
                    apply_decision_entry, _quarantine, wait=30, backoff=5)
            except Exception:
                logger.exception("Approval-Worker abgestürzt – Neustart in 10 s")
                time.sleep(10)

    t = threading.Thread(target=loop, name="approval-worker", daemon=True)
    t.start()
    return t
