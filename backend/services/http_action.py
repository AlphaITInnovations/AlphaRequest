"""Automations-Aktion `http_request`: beliebiger ausgehender API-Aufruf.

URL, Header-Werte und Body dürfen `{{feld.key}}`-Platzhalter aus den Auftrags-
werten tragen (zusätzlich {{title}}, {{id}}). In der URL werden eingesetzte Werte
prozentkodiert, in Headern/Body roh übernommen. Die Definition pflegt die
Admin-Rolle (Prozess-Editor) – dieselbe Vertrauensstellung wie directus_write.

Fehler blockieren den Workflow standardmäßig NICHT: sie werden protokolliert, im
Auftrags-Verlauf und im Audit vermerkt und zusätzlich per Mail an BUG_REPORT_MAIL
gemeldet. Mit onError=block wird der Fehler durchgereicht – im synchronen
on_department_done-Pfad bricht dadurch der Abschluss ab (wie bei directus_write).

Datenschutz: Log/Audit/Verlauf/Mail führen die URL-VORLAGE (mit `{{…}}`), nie die
mit Werten gefüllte URL – so landen eingesetzte Feldwerte (evtl. Tokens/PII) nicht
in den Berichten. Der HTTP-Client ist injizierbar (`client`) – testbar ohne Netz.
"""
from __future__ import annotations

import time
from typing import Callable, Optional
from urllib.parse import quote

import requests

from backend.metrics import engine_metrics
from backend.services import mail_template as mt
from backend.utils.logger import logger


class HttpActionError(RuntimeError):
    """Ausgehender API-Aufruf fehlgeschlagen (Netzfehler, Timeout, Status ≥ 400)."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def _stringify(v) -> str:
    """Feldwert für einen API-Aufruf. Leer/None → "" (kein „—" wie in der Mail: ein
    API bekommt einen leeren Wert, keinen Gedankenstrich), Bool → true/false, skalare
    Liste → kommagetrennt, verschachtelte Struktur → "" (in einer URL/einem Body
    hat sie nichts zu suchen)."""
    if v is None or v == "":
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, tuple)):
        return ",".join(_stringify(x) for x in v if not isinstance(x, (dict, list, tuple)))
    if isinstance(v, dict):
        return ""
    return str(v)


def _value_resolver(row: dict) -> Callable[[str], str]:
    """`{{token}}` → roher String aus den Auftragswerten (plus {{title}}/{{id}})."""
    values = row.get("values") or {}

    def one(token: str) -> str:
        if token == "title":
            return str(row.get("title") or "")
        if token == "id":
            return str(row.get("id") or "")
        return _stringify(values.get(token))
    return one


def render_url(url: str, row: dict) -> str:
    """URL-Vorlage mit PROZENTKODIERTEN Feldwerten füllen (sicher für Pfad/Query)."""
    base = _value_resolver(row)
    return mt.substitute(url, lambda tok: quote(base(tok), safe=""))


def render_text(text: Optional[str], row: dict) -> str:
    """Header-Wert/Body-Vorlage mit ROHEN Feldwerten füllen."""
    return mt.substitute(text, _value_resolver(row))


def execute(action, row: dict, defn, phase, *, client=requests,
            on_error: Optional[Callable] = None) -> dict:
    """Führt die http_request-Aktion aus. Gibt changes zurück (aktuell {} – der
    Aufruf ändert keinen Auftragszustand). Bei onError=block wird der Fehler
    durchgereicht, sonst gemeldet und geschluckt."""
    spec = getattr(action, "http", None)
    if spec is None:
        return {}
    method = getattr(spec.method, "value", spec.method)
    report = on_error or _report_failure
    started = time.perf_counter()
    try:
        url = render_url(spec.url, row)
        if not (url.startswith("http://") or url.startswith("https://")):
            # Kann nur passieren, wenn ein Platzhalter das Schema verschoben hat.
            raise HttpActionError("unzulässige URL nach Einsetzen der Platzhalter")
        headers = {h.name: render_text(h.value, row)
                   for h in spec.headers if h.name.strip()}
        data = None
        body_txt = render_text(spec.body, row) if spec.body else ""
        if body_txt:
            data = body_txt.encode("utf-8")
            if not any(k.lower() == "content-type" for k in headers):
                headers["Content-Type"] = ((spec.contentType or "").strip()
                                           or "application/json; charset=utf-8")
        resp = client.request(method, url, headers=headers or None, data=data,
                              timeout=spec.timeoutSeconds)
        status = getattr(resp, "status_code", 0)
        if status >= 400:
            raise HttpActionError(f"HTTP {status}: {_body_snippet(resp)}", status=status)
        engine_metrics.record_http_request(method, "ok", time.perf_counter() - started)
        return {}
    except HttpActionError as exc:
        engine_metrics.record_http_request(method, "error", time.perf_counter() - started)
        if _blocks(spec):
            raise
        report(row, phase, spec, exc)
        return {}
    except requests.RequestException as exc:
        # Nachricht bewusst OHNE str(exc): manche requests-Fehler betten die gefüllte
        # URL ein (evtl. mit Token/PII). Nur der Fehlertyp wandert in den Bericht.
        engine_metrics.record_http_request(method, "error", time.perf_counter() - started)
        wrapped = HttpActionError(f"nicht erreichbar ({type(exc).__name__})")
        if _blocks(spec):
            raise wrapped from exc
        report(row, phase, spec, wrapped)
        return {}


def _blocks(spec) -> bool:
    oe = getattr(spec, "onError", None)
    return str(getattr(oe, "value", oe)) == "block"


def _body_snippet(resp) -> str:
    """Kurzer Ausschnitt der Fehler-Antwort (Meldung der Gegenstelle)."""
    try:
        return (getattr(resp, "text", "") or "")[:200]
    except Exception:
        return ""


# ── Fehlermeldung: Verlauf + Audit + Mail an BUG_REPORT_MAIL ──────────────────

def _report_failure(row: dict, phase, spec, exc: Exception) -> None:
    tid = row.get("id")
    method = getattr(spec.method, "value", spec.method)
    # spec.url ist die VORLAGE (mit {{…}}) – nie die gefüllte URL protokollieren.
    logger.error("API-Aufruf (%s %s) für #%s fehlgeschlagen: %s",
                 method, spec.url, tid, exc)
    details = {"method": method, "url": spec.url, "error": str(exc)[:500]}
    try:
        from backend.database.audit_log import record_audit
        record_audit(action="process_http_request_failed", actor_id=None, actor_name="System",
                     actor_type="system", entity_type="process_ticket", entity_id=str(tid),
                     summary=f"API-Aufruf fehlgeschlagen ({method} {spec.url})",
                     details=details)
    except Exception:
        logger.exception("Audit für API-Fehler nicht schreibbar (#%s)", tid)
    try:
        from backend.services import process_events as events
        events.system(row, "http_request_failed",
                      phase_key=(phase.key if phase else None), details=details)
    except Exception:
        logger.exception("Verlaufseintrag für API-Fehler nicht schreibbar (#%s)", tid)
    _notify_bug_mail(row, spec, exc)


def _notify_bug_mail(row: dict, spec, exc: Exception) -> None:
    from backend.utils.config import config
    to = (getattr(config, "BUG_REPORT_MAIL", "") or "").strip()
    if not to:
        return
    method = getattr(spec.method, "value", spec.method)
    try:
        from backend.services.microsoft_mail import (
            brand_logo_attachment, render_corporate_email, send_mail_app_only,
        )
        title = str(row.get("title") or f"Auftrag #{row.get('id')}")
        send_mail_app_only(
            sender_upn_or_id="alpharequest@alpha-it-innovations.org",
            subject=f"[AlphaRequest] API-Aufruf fehlgeschlagen: {title}",
            kind="http_request_failed",
            body=render_corporate_email(
                subject="API-Aufruf fehlgeschlagen",
                header_subtitle="Automatische Aktion fehlgeschlagen",
                headline=title,
                intro=("Eine Automation konnte einen API-Aufruf nicht ausführen. "
                       "Der Auftrag läuft weiter – bitte manuell prüfen und ggf. nachtragen."),
                info_rows=[("Auftrag", f"#{row.get('id')}"), ("Methode", method),
                           ("Adresse", spec.url), ("Fehler", str(exc)[:300])],
                content="",
            ),
            to_recipients=[to],
            body_type="HTML",
            attachments=[a for a in [brand_logo_attachment()] if a],
        )
    except Exception:
        logger.exception("Fehler-Mail (API-Aufruf) nicht versendbar (#%s)", row.get("id"))
