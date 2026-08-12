"""
Anspruchs-Ledger für fortlaufende Nummern (`assign_sequence`, §3.1).

Eine vergebene Nummer ist nicht zurückholbar – deshalb hängt an dieser Tabelle
mehr als reine Persistenz. Zwei UNIQUE-Schlüssel tragen die beiden Zusagen:

1. `UNIQUE(ticket_id, field_key)` – **Idempotenz**. Ein Retry oder ein zweiter
   Klick findet den bestehenden Anspruch und bekommt DIESELBE Nummer, ohne den
   Zähler anzufassen. Ohne diesen Schlüssel würde jeder Wiederholungsversuch
   eine Nummer verbrennen (im Alt-System hing das allein daran, dass jemand
   vorher „ist schon gesetzt?" geprüft hat – ein Race, kein Schutz).
2. `UNIQUE(counter, scope_key, numeric_value)` – **keine Doppelvergabe**. Zwei
   Aufträge können dieselbe Nummer nicht halten. Schlägt dieser Schlüssel an,
   ist der Zählerstand kaputt; das wird als LAUTER Fehler gemeldet
   (`SequenceNumberCollision`) statt still eine zweite Personalnummer derselben
   Person in Umlauf zu bringen.

Der Zählerstand selbst liegt weiterhin dort, wo ihn die Einstellungen pflegen:
in der settings-Zeile COMPANIES (pnr_from/pnr_to/pnr_current je Firma). Er wird
in DERSELBEN Transaktion gesperrt und fortgeschrieben wie der Anspruch – nur so
sind „Nummer gezogen" und „Zähler weitergedreht" untrennbar. Deshalb wird hier
bewusst NICHT `db_assign_personalnummer_for_company` aufgerufen: die Funktion
committet selbst und würde den Anspruch aus dieser Transaktion reißen.
"""
import json
from typing import Callable, Optional

import pymysql

from backend.database.connection import get_connection, _exec, _fetchone
from backend.database.personalnummer import COMPANIES_KEY
from backend.database.settings import normalize_company


class SequenceNumberCollision(Exception):
    """Die berechnete Nummer ist im Nummernkreis bereits vergeben.

    Kein Retry-Fall: der Zähler steht hinter dem Ledger zurück und muss von Hand
    korrigiert werden. Eine stille Weiterschaltung wäre Datenkorruption.
    """


PROCESS_SEQUENCE_CLAIMS_DDL = """
CREATE TABLE IF NOT EXISTS process_sequence_claims (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    ticket_id     INT NOT NULL,
    field_key     VARCHAR(150) NOT NULL,
    `counter`     VARCHAR(64) NOT NULL,
    scope_key     VARCHAR(128) NOT NULL,
    numeric_value BIGINT NOT NULL,
    `value`       VARCHAR(64) NOT NULL,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_claim (ticket_id, field_key),
    UNIQUE KEY uq_number (`counter`, scope_key, numeric_value)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

# Keine In-Place-Migrationen: die Tabelle ist neu, das DDL ist ihr ganzer Stand.
PROCESS_SEQUENCE_CLAIMS_MIGRATIONS: list[str] = []

_COLS = ("id, ticket_id, field_key, `counter`, scope_key, numeric_value, `value`, created_at")

_SELECT_CLAIM = (f"SELECT {_COLS} FROM process_sequence_claims "
                 "WHERE ticket_id=%s AND field_key=%s")


def _to_dict(row: Optional[dict]) -> Optional[dict]:
    if not row:
        return None
    out = dict(row)
    created = out.get("created_at")
    out["created_at"] = created.isoformat() if hasattr(created, "isoformat") else created
    out["numeric_value"] = int(out["numeric_value"])
    out["value"] = str(out["value"])
    return out


def get_claim(ticket_id: int, field_key: str) -> Optional[dict]:
    """Bestehender Anspruch eines Auftrags auf ein Feld (None = noch keiner)."""
    conn = get_connection()
    try:
        return _to_dict(_fetchone(conn, _SELECT_CLAIM, (ticket_id, field_key)))
    finally:
        conn.close()


def claim_company_sequence(*, ticket_id: int, field_key: str, counter: str,
                           allocate: Callable[[list], tuple[list, dict]]) -> dict:
    """Die nächste Nummer aus dem FIRMEN-Nummernkreis belegen – eine Transaktion.

    Ablauf (Reihenfolge ist Absicht: erst Anspruch, dann Zähler – überall gleich,
    also kein Deadlock-Zyklus):
      1. bestehenden Anspruch `FOR UPDATE` lesen → vorhanden? zurückgeben, den
         Zähler NICHT anfassen;
      2. sonst die settings-Zeile COMPANIES `FOR UPDATE` lesen (= Zählerstand);
      3. `allocate(companies)` rechnet die nächste Nummer aus (reine Logik,
         `compute_next_personalnummer`) und liefert den neuen Zählerstand;
      4. Anspruch einfügen, Zähler zurückschreiben, commit.

    `allocate` bekommt die normalisierten Firmen-Dicts und gibt
    `(firmen, belegung)` zurück; `belegung` braucht mindestens
    `{"value": str, "numeric_value": int, "scope_key": str}`. Eigene Ausnahmen
    (z.B. Nummernkreis erschöpft) rollen die Transaktion zurück und werden
    durchgereicht – der Zähler bleibt dann unangetastet.

    Rückgabe: der Anspruch + `reused` (True = bestand schon) + `allocation`
    (die Belegung, nur beim ERSTEN Mal – daran hängt die Warn-Schwelle).
    """
    conn = get_connection()
    try:
        conn.begin()
        row = _fetchone(conn, _SELECT_CLAIM + " FOR UPDATE", (ticket_id, field_key))
        if row:
            # Nichts geändert → Sperren sofort freigeben. Genau hier entsteht die
            # Idempotenz: derselbe (Auftrag, Feld) bekommt seine Nummer erneut,
            # ohne dass der Zähler eine weitere verbrennt.
            conn.rollback()
            return {**_to_dict(row), "reused": True, "allocation": None}

        srow = _fetchone(conn, "SELECT `value` FROM settings WHERE `key`=%s FOR UPDATE",
                         (COMPANIES_KEY,))
        try:
            raw = json.loads(srow["value"]) if srow and srow["value"] else []
        except Exception:
            raw = []
        if not isinstance(raw, list):
            raw = []
        companies = [normalize_company(x) for x in raw]

        companies, alloc = allocate(companies)
        value = str(alloc["value"])
        numeric = int(alloc["numeric_value"])
        scope = str(alloc["scope_key"])

        _exec(
            conn,
            "INSERT INTO process_sequence_claims "
            "(ticket_id, field_key, `counter`, scope_key, numeric_value, `value`) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (ticket_id, field_key, counter, scope, numeric, value),
        )
        _exec(
            conn,
            "INSERT INTO settings(`key`,`value`) VALUES(%s,%s) "
            "ON DUPLICATE KEY UPDATE `value`=VALUES(`value`)",
            (COMPANIES_KEY, json.dumps(companies, ensure_ascii=False)),
        )
        conn.commit()
        return {"ticket_id": ticket_id, "field_key": field_key, "counter": counter,
                "scope_key": scope, "numeric_value": numeric, "value": value,
                "reused": False, "allocation": alloc}
    except pymysql.err.IntegrityError as exc:
        conn.rollback()
        # Zwei Möglichkeiten, und sie sind fachlich völlig verschieden:
        # (a) uq_claim – ein paralleler Request war schneller. Er hat committet
        #     (sonst hätte unser INSERT auf der Sperre gewartet), also liegt der
        #     Anspruch jetzt da: zurückgeben, fertig.
        # (b) uq_number – die Nummer gibt es schon. Der Zähler hinkt dem Ledger
        #     hinterher; weitermachen hieße dieselbe Personalnummer zweimal zu
        #     vergeben. Deshalb laut scheitern.
        row = _fetchone(conn, _SELECT_CLAIM, (ticket_id, field_key))
        if row:
            return {**_to_dict(row), "reused": True, "allocation": None}
        raise SequenceNumberCollision(
            f"Nummernkreis „{counter}“: die berechnete Nummer ist bereits vergeben "
            f"(Anspruchs-Ledger und Zählerstand laufen auseinander)."
        ) from exc
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
