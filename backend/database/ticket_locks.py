"""
Edit-Locks für Tickets – pessimistisches Sperren der Bearbeitungsansicht, damit
nicht zwei Personen gleichzeitig dasselbe Ticket bearbeiten (Race Conditions beim
Speichern). DB-basiert, damit der Lock über mehrere Backend-Replikas hinweg gilt.

Tabelle: ticket_locks
  - ticket_id    INT  PRIMARY KEY
  - user_id      VARCHAR(255)   (Inhaber)
  - user_name    VARCHAR(255)   (Anzeigename, denormalisiert für das Popup)
  - acquired_at  DATETIME       (erstmaliges Sperren)
  - heartbeat_at DATETIME       (letztes Lebenszeichen des Editors)

Ein Lock gilt als AKTIV, solange das letzte Heartbeat jünger als LOCK_TTL_SECONDS
ist. Schließt jemand den Tab, läuft der Lock nach Ablauf der TTL automatisch ab
(und kann übernommen werden). Admins können ihn jederzeit sofort aufheben.
"""

import pymysql

from backend.database.connection import get_connection, _exec, _fetchone


# Ein Lock ohne Heartbeat innerhalb dieser Zeit gilt als verwaist (übernehmbar).
LOCK_TTL_SECONDS = 180


TICKET_LOCKS_DDL = """
CREATE TABLE IF NOT EXISTS ticket_locks (
    ticket_id    INT           NOT NULL,
    user_id      VARCHAR(255)  NOT NULL,
    user_name    VARCHAR(255)  NULL,
    acquired_at  DATETIME      NOT NULL,
    heartbeat_at DATETIME      NOT NULL,
    PRIMARY KEY (ticket_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def ensure_table() -> None:
    conn = get_connection()
    try:
        _exec(conn, TICKET_LOCKS_DDL)
        conn.commit()
    finally:
        conn.close()


def _me(user_id: str, user_name: str | None) -> dict:
    return {"locked": True, "is_me": True, "holder_id": user_id,
            "holder_name": user_name, "age_seconds": 0}


def acquire_lock(ticket_id: int, user_id: str, user_name: str | None) -> dict:
    """
    Versucht, den Lock zu erhalten. Erfolg, wenn frei, bereits eigener oder
    abgelaufen (Übernahme). Rückgabe-Dict:
      { locked, is_me, holder_id, holder_name, age_seconds }
    is_me=False → jemand anderes hält einen aktiven Lock (holder_* = diese Person).
    """
    conn = get_connection()
    try:
        cur = conn.cursor()

        # 1) Frischer Lock (häufigster Fall) – atomar via PRIMARY KEY.
        try:
            cur.execute(
                "INSERT INTO ticket_locks (ticket_id, user_id, user_name, acquired_at, heartbeat_at) "
                "VALUES (%s, %s, %s, NOW(), NOW())",
                (ticket_id, user_id, user_name),
            )
            conn.commit()
            return _me(user_id, user_name)
        except pymysql.err.IntegrityError:
            conn.rollback()

        # 2) Zeile existiert → exklusiv sperren und entscheiden.
        cur.execute(
            "SELECT user_id, user_name, TIMESTAMPDIFF(SECOND, heartbeat_at, NOW()) AS age "
            "FROM ticket_locks WHERE ticket_id = %s FOR UPDATE",
            (ticket_id,),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(
                "INSERT INTO ticket_locks (ticket_id, user_id, user_name, acquired_at, heartbeat_at) "
                "VALUES (%s, %s, %s, NOW(), NOW())",
                (ticket_id, user_id, user_name),
            )
            conn.commit()
            return _me(user_id, user_name)

        age = row["age"]
        is_mine = row["user_id"] == user_id
        is_stale = age is not None and age > LOCK_TTL_SECONDS

        if is_mine or is_stale:
            # Eigenen erneuern bzw. verwaisten übernehmen (acquired_at neu nur bei Übernahme).
            cur.execute(
                "UPDATE ticket_locks SET user_id = %s, user_name = %s, "
                "acquired_at = IF(%s, acquired_at, NOW()), heartbeat_at = NOW() "
                "WHERE ticket_id = %s",
                (user_id, user_name, 1 if is_mine else 0, ticket_id),
            )
            conn.commit()
            return _me(user_id, user_name)

        conn.commit()
        return {"locked": True, "is_me": False, "holder_id": row["user_id"],
                "holder_name": row["user_name"], "age_seconds": age}
    finally:
        conn.close()


def get_active_lock(ticket_id: int) -> dict | None:
    """Aktiven Lock zurückgeben oder None (frei bzw. abgelaufen)."""
    conn = get_connection()
    try:
        row = _fetchone(
            conn,
            "SELECT user_id, user_name, acquired_at, "
            "TIMESTAMPDIFF(SECOND, heartbeat_at, NOW()) AS age "
            "FROM ticket_locks WHERE ticket_id = %s",
            (ticket_id,),
        )
    finally:
        conn.close()
    if not row:
        return None
    age = row["age"]
    if age is not None and age > LOCK_TTL_SECONDS:
        return None
    return {"holder_id": row["user_id"], "holder_name": row["user_name"], "age_seconds": age}


def refresh_lock(ticket_id: int, user_id: str) -> bool:
    """Heartbeat. True, wenn der Lock noch dem User gehört (und erneuert wurde)."""
    conn = get_connection()
    try:
        cur = _exec(
            conn,
            "UPDATE ticket_locks SET heartbeat_at = NOW() WHERE ticket_id = %s AND user_id = %s",
            (ticket_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def release_lock(ticket_id: int, user_id: str) -> None:
    """Eigenen Lock freigeben (nur wenn er einem selbst gehört)."""
    conn = get_connection()
    try:
        _exec(conn, "DELETE FROM ticket_locks WHERE ticket_id = %s AND user_id = %s", (ticket_id, user_id))
        conn.commit()
    finally:
        conn.close()


def force_release_lock(ticket_id: int) -> None:
    """Admin-Override: Lock unabhängig vom Inhaber aufheben."""
    conn = get_connection()
    try:
        _exec(conn, "DELETE FROM ticket_locks WHERE ticket_id = %s", (ticket_id,))
        conn.commit()
    finally:
        conn.close()
