"""
Persistenz der Prozess-Definitionen (data-driven Workflows).

Eine Definition existiert je (key, version) in genau einem Status:
draft → published → archived. Invarianten (im Handler/hier erzwungen, §4 des
Design-Docs):
  1. Unveränderlich: definition_json ist nur schreibbar, solange status='draft'
     UND kein Ticket (key,version) pinnt. publish friert ein; archived read-only.
  2. Höchstens EINE published-Version pro key: erzwungen über die generierte
     Spalte `published_marker` (= key wenn published sonst NULL) mit UNIQUE.
  3. Atomarer, nebenläufigkeitssicherer Release: conn.begin() + SELECT … FOR
     UPDATE über alle Zeilen des key; die UNIQUE-Spalte fängt Races beim Commit.
  4. Draft-Politik: höchstens ein offener Draft pro key (Create liefert ihn).
  5. Löschschutz: nur draft und ohne referenzierende Tickets löschbar.
"""
import json
from typing import Optional

import pymysql

from backend.database.connection import get_connection, _exec, _fetchone, _fetchall


# ── Fehler-Typen (die API mappt sie auf HTTP) ─────────────────────────────────

class ProcessNotFound(Exception):
    pass


class ProcessKeyExists(Exception):
    pass


class ProcessInvalidState(Exception):
    """Operation im aktuellen Status nicht erlaubt (z.B. PUT auf published)."""


class ProcessVersionInUse(Exception):
    """Version wird von Tickets referenziert – nicht löschbar/änderbar."""


class ProcessVersionConflict(Exception):
    """Optimistic-Concurrency-Konflikt (If-Match) oder paralleler Publish."""


# ── DDL ───────────────────────────────────────────────────────────────────────

PROCESS_DEFINITIONS_DDL = """
CREATE TABLE IF NOT EXISTS process_definitions (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    `key`            VARCHAR(150) NOT NULL,
    version          INT NOT NULL,
    status           VARCHAR(20) NOT NULL DEFAULT 'draft',
    name             VARCHAR(255) NOT NULL DEFAULT '',
    definition_json  LONGTEXT NOT NULL,
    base_version     INT NULL,
    `published_marker` VARCHAR(150) GENERATED ALWAYS AS (IF(`status`='published', `key`, NULL)) STORED,
    created_by       VARCHAR(255) NULL,
    created_by_name  VARCHAR(255) NULL,
    created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    published_at     DATETIME NULL,
    UNIQUE KEY uq_key_version (`key`, version),
    UNIQUE KEY uq_published (`published_marker`),
    INDEX idx_key_status (`key`, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

_COLS = ("id, `key`, version, status, name, definition_json, base_version, "
         "created_by, created_by_name, created_at, updated_at, published_at")


def ensure_table() -> None:
    conn = get_connection()
    try:
        _exec(conn, PROCESS_DEFINITIONS_DDL)
        conn.commit()
    finally:
        conn.close()


# ── interne Helfer ─────────────────────────────────────────────────────────────

def _row_to_dict(row: Optional[dict]) -> Optional[dict]:
    if not row:
        return None
    out = dict(row)
    for k in ("created_at", "updated_at", "published_at"):
        v = out.get(k)
        out[k] = v.isoformat() if hasattr(v, "isoformat") else v
    try:
        out["definition"] = json.loads(out["definition_json"]) if out.get("definition_json") else None
    except Exception:
        out["definition"] = None
    # ETag = updated_at (für If-Match)
    out["etag"] = out.get("updated_at")
    return out


def _count_pinning_tickets(conn, key: str, version: int) -> int:
    """Wie viele Tickets pinnen (key,version)? 0, falls die Tabelle (noch) fehlt."""
    try:
        row = _fetchone(
            conn,
            "SELECT COUNT(*) AS n FROM process_tickets WHERE process_key=%s AND process_version=%s",
            (key, version),
        )
        return int(row["n"]) if row else 0
    except pymysql.err.OperationalError:
        return 0  # process_tickets existiert noch nicht


def _max_version(conn, key: str) -> int:
    row = _fetchone(conn, "SELECT MAX(version) AS m FROM process_definitions WHERE `key`=%s", (key,))
    return int(row["m"]) if row and row["m"] is not None else 0


def _published_version(conn, key: str) -> Optional[int]:
    row = _fetchone(
        conn,
        "SELECT version FROM process_definitions WHERE `key`=%s AND status='published'",
        (key,),
    )
    return int(row["version"]) if row else None


def _open_draft(conn, key: str) -> Optional[dict]:
    return _fetchone(
        conn,
        f"SELECT {_COLS} FROM process_definitions WHERE `key`=%s AND status='draft' "
        "ORDER BY version DESC LIMIT 1",
        (key,),
    )


# ── Read ───────────────────────────────────────────────────────────────────────

def get_definition(key: str, version: int) -> Optional[dict]:
    conn = get_connection()
    try:
        row = _fetchone(
            conn,
            f"SELECT {_COLS} FROM process_definitions WHERE `key`=%s AND version=%s",
            (key, version),
        )
    finally:
        conn.close()
    return _row_to_dict(row)


def get_published(key: str) -> Optional[dict]:
    conn = get_connection()
    try:
        row = _fetchone(
            conn,
            f"SELECT {_COLS} FROM process_definitions WHERE `key`=%s AND status='published'",
            (key,),
        )
    finally:
        conn.close()
    return _row_to_dict(row)


def list_versions(key: str) -> list[dict]:
    conn = get_connection()
    try:
        rows = _fetchall(
            conn,
            f"SELECT {_COLS} FROM process_definitions WHERE `key`=%s ORDER BY version DESC",
            (key,),
        )
    finally:
        conn.close()
    return [_row_to_dict(r) for r in rows]


def list_published_catalog() -> list[dict]:
    conn = get_connection()
    try:
        rows = _fetchall(
            conn,
            f"SELECT {_COLS} FROM process_definitions WHERE status='published' ORDER BY name, `key`",
        )
    finally:
        conn.close()
    return [_row_to_dict(r) for r in rows]


# ── Write ────────────────────────────────────────────────────────────────────

def create_process(key: str, name: str, definition_json: str,
                   created_by: Optional[str], created_by_name: Optional[str]) -> dict:
    """Neuen Prozess (key) als Draft v1 anlegen. Fehler, wenn key existiert."""
    conn = get_connection()
    try:
        conn.begin()
        row = _fetchone(conn, "SELECT 1 FROM process_definitions WHERE `key`=%s LIMIT 1 FOR UPDATE", (key,))
        if row:
            raise ProcessKeyExists(key)
        _exec(
            conn,
            "INSERT INTO process_definitions (`key`, version, status, name, definition_json, "
            "base_version, created_by, created_by_name) VALUES (%s, 1, 'draft', %s, %s, NULL, %s, %s)",
            (key, name, definition_json, created_by, created_by_name),
        )
        conn.commit()
    except pymysql.err.IntegrityError:
        # Race: zweiter paralleler Create desselben Keys (Gap-Locks koexistieren) →
        # der Verlierer verletzt uq_key_version. Als sauberen 409 zurückgeben.
        conn.rollback()
        raise ProcessKeyExists(key)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_definition(key, 1)


def create_or_get_draft(key: str, created_by: Optional[str], created_by_name: Optional[str]) -> dict:
    """Draft zum Bearbeiten holen/anlegen: gibt es einen offenen Draft, wird er
    zurückgegeben; sonst wird die aktuelle published-Version als neuer Draft
    (version=max+1, base_version=published) geklont."""
    conn = get_connection()
    try:
        conn.begin()
        # Serialisieren gegen parallele Draft-Erzeugung
        _fetchall(conn, "SELECT id FROM process_definitions WHERE `key`=%s FOR UPDATE", (key,))
        existing = _open_draft(conn, key)
        if existing:
            conn.commit()
            return _row_to_dict(existing)

        pub_v = _published_version(conn, key)
        if pub_v is None:
            raise ProcessNotFound(key)
        src = _fetchone(
            conn,
            f"SELECT {_COLS} FROM process_definitions WHERE `key`=%s AND version=%s",
            (key, pub_v),
        )
        new_v = _max_version(conn, key) + 1
        _exec(
            conn,
            "INSERT INTO process_definitions (`key`, version, status, name, definition_json, "
            "base_version, created_by, created_by_name) VALUES (%s, %s, 'draft', %s, %s, %s, %s, %s)",
            (key, new_v, src["name"], src["definition_json"], pub_v, created_by, created_by_name),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_definition(key, new_v)


def update_draft(key: str, version: int, name: str, definition_json: str,
                 if_match: Optional[str] = None) -> dict:
    """Draft-Inhalt aktualisieren. Nur wenn status='draft' und keine pinnenden
    Tickets. If-Match (updated_at) schützt vor Lost-Update."""
    conn = get_connection()
    try:
        conn.begin()
        row = _fetchone(
            conn,
            f"SELECT {_COLS} FROM process_definitions WHERE `key`=%s AND version=%s FOR UPDATE",
            (key, version),
        )
        if not row:
            raise ProcessNotFound(f"{key} v{version}")
        if row["status"] != "draft":
            raise ProcessInvalidState(f"Version ist {row['status']}, nur draft ist editierbar")
        if if_match is not None:
            cur = row["updated_at"]
            cur_iso = cur.isoformat() if hasattr(cur, "isoformat") else str(cur)
            if if_match != cur_iso:
                raise ProcessVersionConflict("Definition wurde zwischenzeitlich geändert")
        if _count_pinning_tickets(conn, key, version) > 0:
            raise ProcessVersionInUse(f"{key} v{version} wird von Tickets referenziert")
        _exec(
            conn,
            "UPDATE process_definitions SET name=%s, definition_json=%s WHERE `key`=%s AND version=%s",
            (name, definition_json, key, version),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_definition(key, version)


def publish(key: str, version: int) -> dict:
    """Draft veröffentlichen: bisherige published → archived, diese → published.
    Guarded + idempotent (published → No-op-Erfolg; archived → Fehler)."""
    conn = get_connection()
    try:
        conn.begin()
        rows = _fetchall(
            conn,
            "SELECT id, version, status FROM process_definitions WHERE `key`=%s FOR UPDATE",
            (key,),
        )
        target = next((r for r in rows if r["version"] == version), None)
        if not target:
            raise ProcessNotFound(f"{key} v{version}")
        if target["status"] == "published":
            conn.commit()
            return get_definition(key, version)   # idempotent
        if target["status"] == "archived":
            raise ProcessInvalidState("archivierte Versionen können nicht veröffentlicht werden")
        # bisherige published-Version archivieren
        for r in rows:
            if r["status"] == "published":
                _exec(conn, "UPDATE process_definitions SET status='archived' WHERE id=%s", (r["id"],))
        _exec(
            conn,
            "UPDATE process_definitions SET status='published', published_at=NOW() WHERE id=%s",
            (target["id"],),
        )
        conn.commit()
    except pymysql.err.IntegrityError:
        conn.rollback()
        raise ProcessVersionConflict("paralleler Publish erkannt")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_definition(key, version)


def duplicate(src_key: str, new_key: str, definition_json: str,
              name: str, created_by: Optional[str], created_by_name: Optional[str]) -> dict:
    """Kopiert eine Definition unter neuem key als Draft v1. definition_json ist
    bereits mit dem neuen key umgeschrieben (durch die API)."""
    return create_process(new_key, name, definition_json, created_by, created_by_name)


def _referenced_group_ids(defn: dict) -> set:
    """Alle Gruppen-IDs, die eine Definition referenziert: Feld-Sichtbarkeit,
    Phasen-Zuständigkeit (group + Abteilungs-Regeln) und Automation-Empfänger
    (`to: "group:<id>"`)."""
    out: set = set()
    for f in defn.get("fields", []) or []:
        vis = f.get("visibility") or {}
        out |= set(vis.get("visibleToGroups") or [])

    def _from_automations(items):
        for a in items or []:
            to = ((a.get("action") or {}).get("to") or "")
            if isinstance(to, str) and to.startswith("group:"):
                out.add(to.split(":", 1)[1])

    _from_automations(defn.get("automations"))
    for p in defn.get("phases", []) or []:
        r = p.get("responsibility") or {}
        if r.get("group"):
            out.add(r["group"])
        for dr in (r.get("rule") or []):
            if dr.get("group"):
                out.add(dr["group"])
        _from_automations(p.get("automations"))
    return out


def _refs_group(defn: dict, gid: str) -> bool:
    return gid in _referenced_group_ids(defn)


def groups_referenced_in_definitions(group_ids: set) -> set:
    """Teilmenge von `group_ids`, die von IRGENDEINER Definitionsversion
    referenziert wird (auch archivierte – gepinnte Tickets nutzen sie).
    Ein Durchlauf über alle Definitionen statt einer Abfrage pro Gruppe."""
    wanted = {g for g in (group_ids or set()) if g}
    if not wanted:
        return set()
    conn = get_connection()
    try:
        rows = _fetchall(conn, "SELECT definition_json FROM process_definitions")
    finally:
        conn.close()
    found: set = set()
    for r in rows:
        try:
            d = json.loads(r["definition_json"])
        except Exception:
            continue
        found |= (_referenced_group_ids(d) & wanted)
        if found == wanted:
            break
    return found


def group_referenced_in_definitions(group_id: str) -> bool:
    """Einzelabfrage (Bequemlichkeit) – intern über die Mengenvariante."""
    return bool(groups_referenced_in_definitions({group_id}))


def delete_version(key: str, version: int) -> None:
    """Löscht eine Version. Nur draft und ohne referenzierende Tickets."""
    conn = get_connection()
    try:
        conn.begin()
        row = _fetchone(
            conn,
            "SELECT status FROM process_definitions WHERE `key`=%s AND version=%s FOR UPDATE",
            (key, version),
        )
        if not row:
            raise ProcessNotFound(f"{key} v{version}")
        if row["status"] != "draft":
            raise ProcessInvalidState("nur draft-Versionen sind löschbar")
        if _count_pinning_tickets(conn, key, version) > 0:
            raise ProcessVersionInUse(f"{key} v{version} wird von Tickets referenziert")
        _exec(conn, "DELETE FROM process_definitions WHERE `key`=%s AND version=%s", (key, version))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
