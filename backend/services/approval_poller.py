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

    try:
        # reject extern = OHNE Begründung (bewusst, Punkt 2 des Vertrags).
        approval_commit.commit_decision(
            row, defn, idx, phase, spec, act=act, reason=None,
            by_name=EXTERNAL_ACTOR, via="mail_link_external", metadata=_metadata(decision))
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
    (ack_ids, retry_ids). Ein kaputter Eintrag blockiert die anderen NICHT."""
    ack, retry = [], []
    for d in decisions:
        did = d.get("id")
        try:
            claims = verify(d.get("token", ""))
        except Exception as exc:                    # Signatur/iss/aud/Form/abgelaufen
            quarantine(d, f"Token ungültig: {exc}")
            ack.append(did)
            continue
        if not _envelope_matches(d, claims):
            quarantine(d, "Hülle weicht vom Token ab (tid/act/phase/epoch)")
            ack.append(did)
            continue
        try:
            apply(claims, d)
            ack.append(did)
        except PermanentError as exc:
            quarantine(d, str(exc))
            ack.append(did)
        except Exception:                           # vorübergehend (DB/Deadlock/rev)
            logger.exception("Externe Freigabe %s vorübergehend fehlgeschlagen", did)
            retry.append(did)
    return ack, retry


# ── Long-Poll-Schleife ────────────────────────────────────────────────────────

def run(client, base: str, api_key: str, verify, apply, quarantine, *,
        wait: int = 30, backoff: int = 5, should_stop: Optional[Callable[[], bool]] = None,
        sleep: Callable[[float], None] = time.sleep) -> None:
    """Dauerschleife: abholen → verarbeiten → bestätigen. `after=0` fragt immer den
    kompletten unbestätigten Rückstau ab (Long-Poll blockiert, wenn nichts offen
    ist); so kommen vorübergehend fehlgeschlagene Einträge erneut, ohne dass ein
    advancender Cursor sie überspringt."""
    headers = {"Authorization": f"Bearer {api_key}"}
    while not (should_stop and should_stop()):
        try:
            resp = client.get(f"{base}/pending?after=0&wait={wait}",
                              headers=headers, timeout=wait + 10)
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
            # Long-Poll-Timeout ODER (bei verletztem Long-Poll/Proxy) sofortige leere
            # Antwort → drosseln, damit der öffentliche Dienst nicht beschossen wird.
            sleep(backoff)
            continue
        ack, retry = process_batch(decisions, verify, apply, quarantine)
        if ack:
            try:
                client.post(f"{base}/ack", json={"ids": ack}, headers=headers, timeout=30)
            except Exception:
                logger.exception("Approval-ACK fehlgeschlagen – Einträge kommen erneut")
                sleep(backoff)
                continue
        if retry:
            sleep(backoff)                          # vorübergehende Fehler gedrosselt erneut


# ── Produktions-Verdrahtung ───────────────────────────────────────────────────

def _quarantine(decision: dict, reason: str) -> None:
    """Fehlerablage = Audit-Log (durabel, kein neues Schema). Danach wird ge-ackt."""
    logger.error("Externe Freigabe %s dauerhaft unbrauchbar: %s", decision.get("id"), reason)
    try:
        record_audit(
            action="process_approval_external_quarantined", actor_id=None,
            actor_name=EXTERNAL_ACTOR, actor_type="system", entity_type="process_ticket",
            entity_id=str(decision.get("tid")),
            summary=f"Externe Freigabe-Entscheidung verworfen: {reason}",
            details={"reason": reason, "quelle_id": decision.get("id"),
                     "tid": decision.get("tid"), "act": decision.get("act"),
                     "phase": decision.get("phase"), "epoch": decision.get("epoch"),
                     "klick_metadaten": _metadata(decision), "metadaten_unverifiziert": True})
    except Exception:
        logger.exception("Quarantäne-Audit für %s fehlgeschlagen", decision.get("id"))


def is_configured() -> bool:
    return bool(config.APPROVAL_BASE_URL and config.APPROVAL_PRIVATE_KEY_PATH
                and config.APPROVAL_API_KEY and config.APPROVAL_ISSUER
                and config.APPROVAL_AUDIENCE)


def start_worker() -> Optional[threading.Thread]:
    """Den Abhol-Worker als Daemon-Thread starten, wenn der externe Relay
    konfiguriert ist. Gibt den Thread zurück (oder None)."""
    if not is_configured():
        logger.info("Externer Approval-Relay nicht konfiguriert – Worker bleibt aus")
        return None
    import requests

    verify = make_verifier(approval_jwt.public_key(), config.APPROVAL_ISSUER,
                           config.APPROVAL_AUDIENCE,
                           leeway=30 + int(config.APPROVAL_MAX_PICKUP_DELAY))
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
