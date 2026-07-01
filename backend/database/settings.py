import json
from typing import Any, Dict, List, Optional

from backend.database.connection import get_connection, _exec, _fetchall, _fetchone


DDL_SETTINGS = """
CREATE TABLE IF NOT EXISTS settings (
    `key`   VARCHAR(255) PRIMARY KEY,
    `value` LONGTEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def _parse_json(raw: Optional[str], fallback):
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except Exception:
        return fallback


# ── Core ──────────────────────────────────────────────────────────────────────

def settings_get(key: str, default=None) -> Any:
    conn = get_connection()
    try:
        row = _fetchone(conn, "SELECT value FROM settings WHERE `key`=%s", (key,))
        if not row:
            return default
        return _parse_json(row["value"], row["value"])
    finally:
        conn.close()


def settings_set(key: str, value: Any) -> None:
    payload = json.dumps(value, ensure_ascii=False)
    conn = get_connection()
    try:
        _exec(
            conn,
            "INSERT INTO settings(`key`,`value`) VALUES(%s,%s) "
            "ON DUPLICATE KEY UPDATE `value`=VALUES(`value`)",
            (key, payload),
        )
        conn.commit()
    finally:
        conn.close()


def settings_all() -> Dict[str, Any]:
    conn = get_connection()
    try:
        rows = _fetchall(conn, "SELECT `key`,`value` FROM settings")
        return {r["key"]: _parse_json(r["value"], r["value"]) for r in rows}
    finally:
        conn.close()


# ── Companies ─────────────────────────────────────────────────────────────────
#
# Firmen werden als Objekte gespeichert:
#   { name, pnr_from, pnr_to, pnr_current, pnr_warned, mandant }
# - pnr_from/pnr_to : vergebbarer Personalnummern-Bereich (inklusive), optional
# - pnr_current     : zuletzt VERGEBENE Nummer (None = noch keine); Laufzeit-Zähler
# - pnr_warned      : True, sobald für diesen Bereich eine Warn-Mail raus ist
# - mandant         : optionale Mandantennummer der Firma
# Altbestand (reine String-Liste) wird beim Lesen automatisch normalisiert.


def _int_or_none(v) -> Optional[int]:
    if v in (None, ""):
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _digits_or_none(v) -> Optional[str]:
    """Grenze als Ziffern-String (bewahrt führende Nullen, z.B. '00896'). None, wenn leer/ungültig."""
    if v in (None, ""):
        return None
    s = str(v).strip()
    return s if s.isdigit() else None


def pnr_width(company: dict) -> int:
    """Stellenanzahl fürs Zero-Padding (aus der breiteren Bereichsgrenze)."""
    f = company.get("pnr_from") or ""
    t = company.get("pnr_to") or ""
    return max(len(str(f)), len(str(t)), 1)


def pnr_format(company: dict, n: int) -> str:
    """Eine numerische Personalnummer als Ziffern-String mit führenden Nullen."""
    return str(n).zfill(pnr_width(company))


def normalize_company(item) -> dict:
    """Ein Firmen-Eintrag (String oder Objekt) → kanonisches Objekt.
    pnr_from/pnr_to werden als Ziffern-STRINGS gehalten (führende Nullen bleiben),
    pnr_current als Zahl (laufender Zähler)."""
    if isinstance(item, str):
        return {"name": item.strip(), "pnr_from": None, "pnr_to": None,
                "pnr_current": None, "pnr_warned": False, "mandant": None}
    if isinstance(item, dict):
        mandant = item.get("mandant")
        mandant = str(mandant).strip() if mandant not in (None, "") else None
        return {
            "name": str(item.get("name", "")).strip(),
            "pnr_from": _digits_or_none(item.get("pnr_from")),
            "pnr_to": _digits_or_none(item.get("pnr_to")),
            "pnr_current": _int_or_none(item.get("pnr_current")),
            "pnr_warned": bool(item.get("pnr_warned", False)),
            "mandant": mandant,
        }
    return {"name": "", "pnr_from": None, "pnr_to": None,
            "pnr_current": None, "pnr_warned": False, "mandant": None}


def get_companies_full() -> List[dict]:
    """Alle Firmen als vollständige Objekte (dedupliziert nach Name)."""
    val = settings_get("COMPANIES")
    if not val:
        return []
    if isinstance(val, str):
        val = [x.strip() for x in val.split(",") if x.strip()]
    if not isinstance(val, list):
        return []
    out: List[dict] = []
    seen = set()
    for item in val:
        c = normalize_company(item)
        if c["name"] and c["name"] not in seen:
            seen.add(c["name"])
            out.append(c)
    return out


def get_companies() -> List[str]:
    """Nur die Firmennamen (für Dropdowns) – rückwärtskompatibel."""
    return [c["name"] for c in get_companies_full()]


def set_companies_full(companies: List[dict]) -> None:
    """
    Firmen speichern. Der Laufzeit-Zähler (pnr_current) wird NIE aus dem Client
    übernommen, sondern aus dem Bestand bewahrt (verhindert versehentliches
    Zurücksetzen und damit doppelte Nummern). Wird der Bereich erweitert
    (pnr_to erhöht), wird das Warn-Flag zurückgesetzt.
    """
    existing = {c["name"]: c for c in get_companies_full()}
    out: List[dict] = []
    seen = set()
    for item in companies:
        c = normalize_company(item)
        if not c["name"] or c["name"] in seen:
            continue
        seen.add(c["name"])
        prev = existing.get(c["name"])
        if prev:
            c["pnr_current"] = prev["pnr_current"]
            extended = c["pnr_to"] is not None and (
                prev["pnr_to"] is None or int(c["pnr_to"]) > int(prev["pnr_to"])
            )
            c["pnr_warned"] = False if extended else prev["pnr_warned"]
        else:
            c["pnr_current"] = None
            c["pnr_warned"] = False
        out.append(c)
    settings_set("COMPANIES", out)


def set_companies(companies: List[str]) -> None:
    """Nur Namen setzen (Altpfad) – bestehende Bereiche/Zähler bleiben erhalten."""
    set_companies_full([{"name": n} for n in companies])


# ── Ninja Token ───────────────────────────────────────────────────────────────

def get_ninja_token() -> Optional[dict]:
    tok = settings_get("NINJA_TOKEN")
    return tok if isinstance(tok, dict) else None


def set_ninja_token(token: Optional[dict]) -> None:
    settings_set("NINJA_TOKEN", token)