"""
Idempotenz-Ledger für Timer-/Automation-Feuerungen (§7).

Garantiert Fire-once – auch über mehrere Scheduler-Instanzen (dev+prod, Worker):
Ein Feuern wird durch INSERT „geclaimt"; der UNIQUE-Schlüssel
(ticket_id, phase_key, epoch, automation_id, occurrence) lässt einen zweiten
Claim scheitern. `epoch` wird bei Reopen erhöht (kein Löschen alter Marker → Audit).
`suppressed` markiert Catch-up-Occurrences, die nur verbucht, aber nicht ausgeführt
wurden (Missed-Window-Politik).
"""
import pymysql

from backend.database.connection import get_connection, _exec, _fetchall


PROCESS_TIMER_FIRES_DDL = """
CREATE TABLE IF NOT EXISTS process_timer_fires (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    ticket_id      INT NOT NULL,
    phase_key      VARCHAR(100) NOT NULL,
    epoch          INT NOT NULL DEFAULT 0,
    automation_id  VARCHAR(100) NOT NULL,
    occurrence     INT NOT NULL,
    suppressed     TINYINT(1) NOT NULL DEFAULT 0,
    fired_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_fire (ticket_id, phase_key, epoch, automation_id, occurrence)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""
# uq_fire beginnt mit ticket_id und deckt Abfragen nach Ticket bereits ab – ein
# separater idx_ticket wäre ein reines Duplikat (zweiter B-Baum pro INSERT).

PROCESS_TIMER_FIRES_MIGRATIONS = [
    "ALTER TABLE process_timer_fires DROP INDEX IF EXISTS idx_ticket",
]


def ensure_table() -> None:
    conn = get_connection()
    try:
        _exec(conn, PROCESS_TIMER_FIRES_DDL)
        conn.commit()
    finally:
        conn.close()


def claim(ticket_id: int, phase_key: str, epoch: int, automation_id: str,
          occurrence: int, suppressed: bool = False) -> bool:
    """Versucht, (…occurrence) exklusiv zu belegen. True = geclaimt (jetzt feuern),
    False = bereits belegt (nichts tun)."""
    conn = get_connection()
    try:
        _exec(
            conn,
            "INSERT INTO process_timer_fires (ticket_id, phase_key, epoch, automation_id, "
            "occurrence, suppressed) VALUES (%s,%s,%s,%s,%s,%s)",
            (ticket_id, phase_key, epoch, automation_id, occurrence, 1 if suppressed else 0),
        )
        conn.commit()
        return True
    except pymysql.err.IntegrityError:
        conn.rollback()
        return False
    finally:
        conn.close()


def fired_map(ticket_id: int, phase_key: str, epoch: int) -> dict:
    """{automation_id: höchste bereits gefeuerte Occurrence} für (Ticket, Phase, Epoch)."""
    conn = get_connection()
    try:
        rows = _fetchall(
            conn,
            "SELECT automation_id, MAX(occurrence) AS mx FROM process_timer_fires "
            "WHERE ticket_id=%s AND phase_key=%s AND epoch=%s GROUP BY automation_id",
            (ticket_id, phase_key, epoch),
        )
    finally:
        conn.close()
    return {r["automation_id"]: int(r["mx"]) for r in rows}
