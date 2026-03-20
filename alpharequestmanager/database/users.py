from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from alpharequestmanager.database.connection import (
    get_connection, _exec, _fetchone, _fetchall,
)

# ── Roles & Permissions ───────────────────────────────────────────────────────

ROLE_NONE    = "none"
ROLE_VIEWER  = "viewer"
ROLE_MANAGER = "manager"
ROLE_ADMIN   = "admin"
VALID_ROLES  = {ROLE_NONE, ROLE_VIEWER, ROLE_MANAGER, ROLE_ADMIN}

PERM_VIEW   = "view"
PERM_MANAGE = "manage"
PERM_ADMIN  = "admin"

ROLE_PERMISSIONS: dict[str, list[str]] = {
    ROLE_NONE:    [],
    ROLE_VIEWER:  [PERM_VIEW],
    ROLE_MANAGER: [PERM_VIEW, PERM_MANAGE],
    ROLE_ADMIN:   [PERM_VIEW, PERM_MANAGE, PERM_ADMIN],
}

# ── DDL ───────────────────────────────────────────────────────────────────────

USERS_DDL = """
CREATE TABLE IF NOT EXISTS app_users (
    microsoft_id       VARCHAR(255) PRIMARY KEY,
    display_name       VARCHAR(255) NOT NULL,
    email              VARCHAR(255) NOT NULL,
    role               VARCHAR(32)  NOT NULL DEFAULT 'none',
    extra_permissions  LONGTEXT     NOT NULL DEFAULT '[]',
    created_at         VARCHAR(64)  NOT NULL,
    last_login         VARCHAR(64)  NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

# ── Model ─────────────────────────────────────────────────────────────────────

@dataclass
class AppUser:
    microsoft_id:      str
    display_name:      str
    email:             str
    role:              str
    extra_permissions: List[str]
    created_at:        str
    last_login:        str

    @classmethod
    def from_row(cls, row: dict) -> "AppUser":
        extra = row.get("extra_permissions") or "[]"
        try:
            parsed_extra = json.loads(extra) if isinstance(extra, str) else extra
        except Exception:
            parsed_extra = []
        return cls(
            microsoft_id=row["microsoft_id"],
            display_name=row["display_name"],
            email=row["email"],
            role=row["role"],
            extra_permissions=parsed_extra if isinstance(parsed_extra, list) else [],
            created_at=row["created_at"],
            last_login=row["last_login"],
        )

    @property
    def permissions(self) -> List[str]:
        base = ROLE_PERMISSIONS.get(self.role, [])
        combined = list(base)
        for p in self.extra_permissions:
            if p not in combined:
                combined.append(p)
        return combined

    def has_permission(self, perm: str) -> bool:
        return perm in self.permissions


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.utcnow().isoformat()


# ── CRUD ──────────────────────────────────────────────────────────────────────

def upsert_user(
    microsoft_id: str,
    display_name: str,
    email: str,
    role: Optional[str] = None,
) -> AppUser:
    now          = _now()
    initial_role = role if role in VALID_ROLES else ROLE_NONE
    is_admin     = role == ROLE_ADMIN

    conn = get_connection()
    try:
        _exec(conn, """
            INSERT INTO app_users
                (microsoft_id, display_name, email, role, extra_permissions, created_at, last_login)
            VALUES
                (%s, %s, %s, %s, '[]', %s, %s)
            ON DUPLICATE KEY UPDATE
                display_name = VALUES(display_name),
                email        = VALUES(email),
                last_login   = VALUES(last_login),
                role         = IF(%s, VALUES(role), role)
        """, (microsoft_id, display_name, email, initial_role, now, now, is_admin))
        conn.commit()
    finally:
        conn.close()

    return get_user(microsoft_id)


def get_user(microsoft_id: str) -> Optional[AppUser]:
    conn = get_connection()
    try:
        row = _fetchone(conn,
            "SELECT * FROM app_users WHERE microsoft_id = %s", (microsoft_id,))
        return AppUser.from_row(row) if row else None
    finally:
        conn.close()


def list_users() -> list[AppUser]:
    conn = get_connection()
    try:
        rows = _fetchall(conn, "SELECT * FROM app_users ORDER BY display_name")
        return [AppUser.from_row(r) for r in rows]
    finally:
        conn.close()


def set_user_role(microsoft_id: str, role: str) -> AppUser:
    if role not in VALID_ROLES:
        raise ValueError(f"Ungültige Rolle: {role!r}. Erlaubt: {VALID_ROLES}")
    conn = get_connection()
    try:
        _exec(conn,
            "UPDATE app_users SET role = %s WHERE microsoft_id = %s",
            (role, microsoft_id))
        conn.commit()
    finally:
        conn.close()
    return get_user(microsoft_id)


def get_user_permissions(microsoft_id: str) -> List[str]:
    user = get_user(microsoft_id)
    return user.permissions if user else []


def set_extra_permissions(microsoft_id: str, perms: List[str]) -> None:
    conn = get_connection()
    try:
        _exec(conn,
            "UPDATE app_users SET extra_permissions = %s WHERE microsoft_id = %s",
            (json.dumps(perms, ensure_ascii=False), microsoft_id))
        conn.commit()
    finally:
        conn.close()


def add_extra_permission(microsoft_id: str, perm: str) -> AppUser:
    user = get_user(microsoft_id)
    if not user:
        raise ValueError(f"User {microsoft_id!r} nicht gefunden")
    extras = user.extra_permissions
    if perm not in extras:
        set_extra_permissions(microsoft_id, extras + [perm])
    return get_user(microsoft_id)


def remove_extra_permission(microsoft_id: str, perm: str) -> AppUser:
    user = get_user(microsoft_id)
    if not user:
        raise ValueError(f"User {microsoft_id!r} nicht gefunden")
    set_extra_permissions(microsoft_id, [p for p in user.extra_permissions if p != perm])
    return get_user(microsoft_id)