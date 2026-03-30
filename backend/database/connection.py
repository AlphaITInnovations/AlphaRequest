"""
Shared DB connection helpers.
Importiert von database.py UND users.py – kein circular import.
"""
import os
from typing import Any, Tuple
import pymysql
from pymysql.cursors import DictCursor
from sqlalchemy.engine import make_url


def get_connection():
    dsn = os.getenv("MARIADB_DSN")
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