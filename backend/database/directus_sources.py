"""Konfigurierte Directus-Quellen für Auswahl-Felder.

Eine Quelle beschreibt, WAS aus Directus geholt wird: Collection, Wert-Feld,
Label-Vorlage, die zu ladenden Felder (dot-Pfade für Relationen wie
`firma.name`), optional Filter/Sortierung/Limit. Prozess-Felder vom Typ
`directus` referenzieren eine Quelle über ihren `key`.

Persistenz wie bei Firmen/Gruppen: EIN JSON-Blob im key-value-`settings`-Store
(Schlüssel DIRECTUS_SOURCES) – admin-verwaltete, überschaubare Liste, kein
eigenes Table/Migration nötig.

Die reine Logik (Normalisieren, dot-Pfade auflösen, Label rendern, Optionen
bauen) steht bewusst DB-frei hier, damit sie ohne Datenbank testbar ist.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from backend.database.settings import settings_get, settings_set

SETTINGS_KEY = "DIRECTUS_SOURCES"

#: {{ pfad.mit.punkten }} in der Label-Vorlage.
_VAR_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}")

#: erlaubte Zeichen im Quellen-Schlüssel (stabiler Slug).
_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

_LIMIT_DEFAULT = 200
_LIMIT_MAX = 1000


class SourceError(ValueError):
    """Ungültige Quellen-Konfiguration (sprechende Meldung für die API)."""


# ── Normalisierung / Validierung ──────────────────────────────────────────────

def _str(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _str_list(v: Any) -> list[str]:
    if not isinstance(v, (list, tuple)):
        return []
    out: list[str] = []
    for x in v:
        s = _str(x)
        if s and s not in out:
            out.append(s)
    return out


def normalize_source(raw: dict) -> dict:
    """Kanonische, validierte Form einer Quelle. Wirft SourceError bei Pflicht-
    verstößen (key/collection/valueField/labelTemplate)."""
    if not isinstance(raw, dict):
        raise SourceError("Quelle ist kein Objekt")
    key = _str(raw.get("key")).lower()
    if not _KEY_RE.match(key):
        raise SourceError(f"Ungültiger Schlüssel „{raw.get('key')}“ "
                          "(nur a–z, 0–9, _ und -, Beginn alphanumerisch)")
    collection = _str(raw.get("collection"))
    value_field = _str(raw.get("valueField"))
    label_template = _str(raw.get("labelTemplate"))
    if not collection:
        raise SourceError(f"Quelle „{key}“: collection fehlt")
    if not value_field:
        raise SourceError(f"Quelle „{key}“: valueField fehlt")
    if not label_template:
        raise SourceError(f"Quelle „{key}“: labelTemplate fehlt")

    flt = raw.get("filter")
    if flt is not None and not isinstance(flt, dict):
        raise SourceError(f"Quelle „{key}“: filter muss ein Objekt sein")

    limit = raw.get("limit")
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = _LIMIT_DEFAULT
    limit = max(1, min(_LIMIT_MAX, limit))

    return {
        "key": key,
        "label": _str(raw.get("label")) or key,
        "collection": collection,
        "valueField": value_field,
        "labelTemplate": label_template,
        "fields": _str_list(raw.get("fields")),
        "filter": flt or None,
        "sort": _str_list(raw.get("sort")),
        "limit": limit,
    }


# ── dot-Pfade / Label / Optionen ──────────────────────────────────────────────

def resolve_path(record: Any, path: str) -> Any:
    """Wert an einem dot-Pfad (`firma.name`). None, wenn ein Zwischenschritt fehlt
    oder keine Verzweigung erlaubt (Listen/o2m werden bewusst nicht aufgelöst)."""
    cur = record
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _scalar(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Ja" if v else "Nein"
    if isinstance(v, (list, dict)):
        return ""
    return str(v)


def render_label(template: str, record: dict) -> str:
    """Label-Vorlage mit Datensatzwerten füllen ({{pfad}} → Wert)."""
    return _VAR_RE.sub(lambda m: _scalar(resolve_path(record, m.group(1))), template or "")


def template_paths(template: str) -> list[str]:
    """Alle dot-Pfade, die in der Label-Vorlage vorkommen (ohne Dopplung)."""
    seen: list[str] = []
    for m in _VAR_RE.finditer(template or ""):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def query_fields(source: dict) -> list[str]:
    """Directus-Feldliste, die für Optionen/Snapshot geladen werden muss:
    Wert-Feld + Label-Pfade + explizit konfigurierte Felder (dedupliziert)."""
    fields: list[str] = []
    for f in [source.get("valueField", ""), *template_paths(source.get("labelTemplate", "")),
              *source.get("fields", [])]:
        if f and f not in fields:
            fields.append(f)
    return fields


def build_option(record: dict, source: dict) -> dict:
    """Eine Auswahl-Option: {value, label, record}. `value` ist der Wert des
    Wert-Felds, `label` die gerenderte Vorlage (Fallback: der Wert selbst),
    `record` der Rohdatensatz (für Snapshot/Auto-Fill der Zielfelder)."""
    value = _scalar(resolve_path(record, source["valueField"]))
    label = render_label(source["labelTemplate"], record).strip() or value
    return {"value": value, "label": label, "record": record}


def build_options(records: list[dict], source: dict) -> list[dict]:
    return [build_option(r, source) for r in records if isinstance(r, dict)]


# ── Persistenz (settings-Blob) ────────────────────────────────────────────────

def get_all() -> list[dict]:
    """Alle konfigurierten Quellen (kanonisch). Unlesbare Einträge werden
    übersprungen statt alles scheitern zu lassen."""
    raw = settings_get(SETTINGS_KEY, [])
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for entry in raw:
        try:
            out.append(normalize_source(entry))
        except SourceError:
            continue
    return out


def get(key: str) -> Optional[dict]:
    key = _str(key).lower()
    for s in get_all():
        if s["key"] == key:
            return s
    return None


def set_all(sources: list[dict]) -> list[dict]:
    """Ganze Liste ersetzen (bulk-replace wie bei Firmen). Normalisiert jede
    Quelle und lehnt doppelte Schlüssel ab. Gibt die kanonische Liste zurück."""
    if not isinstance(sources, list):
        raise SourceError("Erwartet eine Liste von Quellen")
    cleaned: list[dict] = []
    seen: set[str] = set()
    for entry in sources:
        s = normalize_source(entry)
        if s["key"] in seen:
            raise SourceError(f"Doppelter Schlüssel „{s['key']}“")
        seen.add(s["key"])
        cleaned.append(s)
    settings_set(SETTINGS_KEY, cleaned)
    return cleaned
