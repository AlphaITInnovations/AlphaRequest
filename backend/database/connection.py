"""
Shared DB connection helpers.
Importiert von database.py UND users.py – kein circular import.

Verbindungen kommen aus einem Pool (SQLAlchemy QueuePool um pymysql). Vorher
öffnete jeder Aufruf eine eigene TCP-/Auth-Verbindung – ein einzelner Request
kostete so leicht ein Dutzend Handshakes. `conn.close()` gibt die Verbindung
an den Pool zurück (die Aufrufer bleiben unverändert).
"""
import os
import threading
from typing import Any, Tuple

import pymysql
from pymysql.cursors import DictCursor
from sqlalchemy.dialects.mysql import pymysql as _pymysql_dialect
from sqlalchemy.engine import make_url
from sqlalchemy.pool import QueuePool

# pre_ping braucht einen Dialekt: ein nackter Pool kennt do_ping() nicht und
# wirft beim ERSTEN Wiederverwenden einer Verbindung
# "NotImplementedError: The ping feature requires that a dialect is passed".
_DIALECT = _pymysql_dialect.dialect()

_pool = None
_pool_dsn = None
_lock = threading.Lock()

POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
POOL_MAX_OVERFLOW = int(os.getenv("DB_POOL_MAX_OVERFLOW", "10"))
POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "1800"))   # < MySQL wait_timeout


def _connect_raw(dsn: str):
    url = make_url(dsn)
    return pymysql.connect(
        host=url.host,
        port=url.port or 3306,
        user=url.username,
        password=url.password,
        database=url.database,
        cursorclass=DictCursor,
        autocommit=False,
        charset=url.query.get("charset", ["utf8mb4"])[0],
    )


def _get_pool(dsn: str):
    """Pool je DSN (einmalig aufgebaut, danach wiederverwendet)."""
    global _pool, _pool_dsn
    if _pool is not None and _pool_dsn == dsn:
        return _pool
    with _lock:
        if _pool is None or _pool_dsn != dsn:
            if _pool is not None:
                try:
                    _pool.dispose()
                except Exception:
                    pass
            _pool = QueuePool(
                lambda: _connect_raw(dsn),
                pool_size=POOL_SIZE,
                max_overflow=POOL_MAX_OVERFLOW,
                recycle=POOL_RECYCLE,
                pre_ping=True,          # tote Verbindungen still ersetzen
                dialect=_DIALECT,       # nötig für pre_ping (do_ping)
                reset_on_return="rollback",
            )
            _pool_dsn = dsn
    return _pool


def get_connection():
    """Verbindung aus dem Pool. `close()` gibt sie zurück (kein echtes Schließen)."""
    dsn = os.getenv("MARIADB_DSN")
    return _get_pool(dsn).connect()


def _exec(conn, sql: str, params: Tuple[Any, ...] = ()):
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur


def _fetchall(conn, sql: str, params: Tuple[Any, ...] = ()):
    cur = _exec(conn, sql, params)
    rows = cur.fetchall()
    cur.close()
    return rows


def _fetchone(conn, sql: str, params: Tuple[Any, ...] = ()):
    cur = _exec(conn, sql, params)
    row = cur.fetchone()
    cur.close()
    return row
