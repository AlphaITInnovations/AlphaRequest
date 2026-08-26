"""Anbindung an Directus (internes Stammdaten-System) als LESE-Quelle für
Auswahl-Felder in Prozessen (Kostenstelle, Niederlassung …).

Bewusst dünn und synchron (requests): URL bauen, Bearer-Token, Timeout, den
Directus-`{"data": …}`-Envelope auspacken, Fehler in `DirectusError` übersetzen.
Nur Lesen – der Token ist ein statischer Directus-Service-Token mit Leserechten
(config.DIRECTUS_URL / config.DIRECTUS_TOKEN).

`is_configured()` trägt die fail-soft-Politik: ist Directus nicht eingerichtet,
sollen die Aufrufer (Options-/Introspektions-Endpunkte) eine leere Auswahl
zeigen statt abzustürzen. Die reinen Datenpfade werfen `DirectusError`; das
Übersetzen in HTTP-Antworten bzw. leere Listen ist Sache der API-Schicht.
"""
from __future__ import annotations

import json
from typing import Any, Optional

import requests

from backend.utils.config import config
from backend.utils.logger import logger

#: System-Collections/-Präfix, die in der Auswahl nichts zu suchen haben.
_SYSTEM_PREFIX = "directus_"


class DirectusError(RuntimeError):
    """Directus nicht erreichbar oder Fehlerantwort.

    Trägt – wenn vorhanden – den HTTP-Statuscode, damit die API-Schicht z. B.
    ein 502 (Directus down) von einem 404 (Collection gibt es nicht) trennen kann.
    """

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def is_configured() -> bool:
    """True, wenn URL UND Token gesetzt sind – sonst ist die Anbindung inaktiv."""
    return bool(config.DIRECTUS_URL and config.DIRECTUS_TOKEN)


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {config.DIRECTUS_TOKEN}", "Accept": "application/json"}


def _error_message(resp: "requests.Response") -> str:
    """Directus meldet Fehler als {"errors":[{"message": …}]} – die erste Meldung
    herausziehen, sonst den (gekürzten) Rohtext."""
    try:
        errs = resp.json().get("errors") or []
        if errs:
            first = errs[0]
            return str(first.get("message") if isinstance(first, dict) else first)
    except Exception:
        pass
    return (resp.text or f"HTTP {resp.status_code}")[:200]


def _request(path: str, params: Optional[dict] = None) -> Any:
    """GET auf {DIRECTUS_URL}{path} und den `data`-Teil zurückgeben.

    Wirft `DirectusError` bei fehlender Konfiguration, Netz-/Timeout-Fehler,
    HTTP-Fehlerstatus oder nicht-JSON-Antwort.
    """
    if not is_configured():
        raise DirectusError("Directus ist nicht konfiguriert (DIRECTUS_URL/DIRECTUS_TOKEN fehlen)")
    url = f"{config.DIRECTUS_URL}{path}"
    try:
        resp = requests.get(url, headers=_headers(), params=params or {},
                            timeout=config.DIRECTUS_TIMEOUT)
    except requests.RequestException as exc:
        raise DirectusError(f"Directus nicht erreichbar: {exc}") from exc
    if resp.status_code >= 400:
        raise DirectusError(f"Directus {resp.status_code}: {_error_message(resp)}",
                            status=resp.status_code)
    try:
        body = resp.json()
    except ValueError as exc:
        raise DirectusError(f"Directus-Antwort ist kein JSON: {exc}") from exc
    return body.get("data") if isinstance(body, dict) else body


# ── Introspektion (für die Verwaltungs-Oberfläche) ────────────────────────────

def list_collections() -> list[dict]:
    """Auswählbare Collections: ohne System-Collections (`directus_*`) und ohne
    reine Ordner (in Directus ist `schema == null` ein Präsentations-Ordner, keine
    echte Tabelle). Liefert [{collection, note, icon, hidden}]."""
    data = _request("/collections") or []
    out: list[dict] = []
    for c in data:
        name = c.get("collection")
        if not name or str(name).startswith(_SYSTEM_PREFIX):
            continue
        if c.get("schema") is None:            # Ordner/Gruppe, keine Tabelle
            continue
        meta = c.get("meta") or {}
        out.append({
            "collection": name,
            "note": meta.get("note"),
            "icon": meta.get("icon"),
            "hidden": bool(meta.get("hidden")),
        })
    out.sort(key=lambda x: x["collection"])
    return out


def list_fields(collection: str) -> list[dict]:
    """Felder einer Collection: [{field, type, note, primaryKey, relatedCollection}].

    `relatedCollection` (aus `schema.foreign_key_table`) benennt bei einer
    Many-to-One-Beziehung die Ziel-Collection – so lassen sich dot-Pfade wie
    `firma.name` in der Oberfläche anbieten.
    """
    data = _request(f"/fields/{collection}") or []
    out: list[dict] = []
    for f in data:
        field = f.get("field")
        if not field:
            continue
        schema = f.get("schema") or {}
        meta = f.get("meta") or {}
        out.append({
            "field": field,
            "type": f.get("type"),
            "note": meta.get("note"),
            "primaryKey": bool(schema.get("is_primary_key")),
            "relatedCollection": schema.get("foreign_key_table"),
        })
    return out


# ── Datenabfrage (für Optionslisten + Snapshot) ───────────────────────────────

def query_items(collection: str, *, fields: Optional[list[str]] = None,
                filter: Optional[dict] = None, sort: Optional[list[str]] = None,
                limit: int = 100, search: Optional[str] = None) -> list[dict]:
    """Items einer Collection lesen.

    `fields` ist die Directus-Feldliste (dot-Pfade wie `firma.name` erlaubt und
    erwünscht – so kommen relationale Werte gleich mit), `filter` ein
    Directus-Filter-dict, `sort` z. B. ["nummer"], `search` Volltextsuche.
    """
    params: dict[str, Any] = {"limit": limit}
    if fields:
        params["fields"] = ",".join(fields)
    if sort:
        params["sort"] = ",".join(sort)
    if search:
        params["search"] = search
    if filter:
        params["filter"] = json.dumps(filter, ensure_ascii=False)
    data = _request(f"/items/{collection}", params=params)
    return data if isinstance(data, list) else []


def status() -> dict:
    """Verbindungs-Status für die Verwaltungs-Oberfläche.

    {configured, ok, error}: `configured` sagt, ob URL+Token gesetzt sind; `ok`
    ist erst True, wenn Directus auch antwortet. Wirft nie – die Oberfläche soll
    den Zustand anzeigen können, ohne einen Fehler zu behandeln.
    """
    if not is_configured():
        return {"configured": False, "ok": False, "error": None}
    try:
        _request("/server/info")
        return {"configured": True, "ok": True, "error": None}
    except DirectusError as exc:
        logger.warning("Directus-Status: %s", exc)
        return {"configured": True, "ok": False, "error": str(exc)}
