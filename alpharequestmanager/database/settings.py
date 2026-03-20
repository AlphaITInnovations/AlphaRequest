import json
from typing import Any, Dict, List, Optional

from alpharequestmanager.database.connection import get_connection, _exec, _fetchall, _fetchone


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

def get_companies() -> List[str]:
    val = settings_get("COMPANIES")
    if not val:
        return []
    if isinstance(val, list):
        return [str(v) for v in val]
    if isinstance(val, str):
        return [x.strip() for x in val.split(",") if x.strip()]
    return []


def set_companies(companies: List[str]) -> None:
    settings_set("COMPANIES", companies)


# ── Ninja Token ───────────────────────────────────────────────────────────────

def get_ninja_token() -> Optional[dict]:
    tok = settings_get("NINJA_TOKEN")
    return tok if isinstance(tok, dict) else None


def set_ninja_token(token: Optional[dict]) -> None:
    settings_set("NINJA_TOKEN", token)