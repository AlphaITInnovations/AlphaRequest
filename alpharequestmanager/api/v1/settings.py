import re
import uuid
from fastapi import APIRouter, Depends, HTTPException, Body, Request
from pydantic import BaseModel
from typing import Optional
from alpharequestmanager.core.dependencies import get_current_user
from alpharequestmanager.database import database as db
from alpharequestmanager.schemas.responses import DataResponse
from alpharequestmanager.services.ticket_permissions import (
    load_ticket_permissions, set_ticket_permissions_safe,
)
from alpharequestmanager.services.microsoft_mail import send_test_mail
from alpharequestmanager.utils.config import config
from alpharequestmanager.utils.logger import logger
from alpharequestmanager.models.models import TicketType
from alpharequestmanager.utils.ticket_labels import TICKET_LABELS

router = APIRouter()

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def require_admin(user: dict):
    if not user.get("is_admin"):
        raise HTTPException(403, "Admin-Rechte erforderlich")


# ── ENV / Config ───────────────────────────────────────────────────────────────

class EnvResponse(BaseModel):
    general: dict
    microsoft: dict
    session: dict


@router.get("/settings/env", response_model=DataResponse[EnvResponse])
def get_env(user: dict = Depends(get_current_user)):
    require_admin(user)
    return DataResponse(data=EnvResponse(
        general={
            "APP_ENV":     {"value": config.APP_ENV,          "sensitive": False},
            "PORT":        {"value": config.PORT,             "sensitive": False},
            "HTTPS":       {"value": bool(config.HTTPS),      "sensitive": False},
            "TICKET_MAIL": {"value": config.TICKET_MAIL or "—","sensitive": False},
        },
        microsoft={
            "CLIENT_ID":     {"is_set": bool(config.CLIENT_ID),     "sensitive": True},
            "CLIENT_SECRET": {"is_set": bool(config.CLIENT_SECRET),  "sensitive": True},
            "TENANT_ID":     {"is_set": bool(config.TENANT_ID),      "sensitive": True},
            "REDIRECT_URI":  {"value": config.REDIRECT_URI or "—",  "sensitive": False},
            "SCOPE":         {"value": ", ".join(config.SCOPE) if config.SCOPE else "—", "sensitive": False},
            "ADMIN_GROUP_ID":{"is_set": bool(config.ADMIN_GROUP_ID), "sensitive": True},
        },
        session={
            "SESSION_TIMEOUT": {"value": config.SESSION_TIMEOUT, "sensitive": False},
            "SECRET_KEY":      {"is_set": bool(config.SECRET_KEY), "sensitive": True},
        },
    ))


# ── Companies ──────────────────────────────────────────────────────────────────

class CompaniesOut(BaseModel):
    companies: list[str]

class CompaniesIn(BaseModel):
    companies: list[str]


def _normalize_companies(items: list[str]) -> list[str]:
    seen, out = set(), []
    for raw in items:
        v = str(raw).strip()
        if v and v.casefold() not in seen:
            seen.add(v.casefold())
            out.append(v)
    return out


@router.get("/settings/companies", response_model=DataResponse[CompaniesOut])
def get_companies(user: dict = Depends(get_current_user)):
    require_admin(user)
    return DataResponse(data=CompaniesOut(companies=db.get_companies()))


@router.put("/settings/companies", response_model=DataResponse[CompaniesOut])
def set_companies(payload: CompaniesIn, user: dict = Depends(get_current_user)):
    require_admin(user)
    normalized = _normalize_companies(payload.companies)
    if not normalized:
        raise HTTPException(422, "Mindestens eine Firma erforderlich")
    try:
        db.set_companies(normalized)
    except Exception as e:
        logger.exception("Failed to update companies: %s", e)
        raise HTTPException(500, "Fehler beim Speichern")
    return DataResponse(data=CompaniesOut(companies=db.get_companies()))


# ── Ticket Permissions ─────────────────────────────────────────────────────────

class TicketTypeInfo(BaseModel):
    key: str
    label: str
    allowed_users: list[str]

class PermissionsOut(BaseModel):
    types: list[TicketTypeInfo]

class PermissionsIn(BaseModel):
    permissions: dict[str, list[str]]


@router.get("/settings/permissions", response_model=DataResponse[PermissionsOut])
def get_permissions(user: dict = Depends(get_current_user)):
    require_admin(user)
    perms = load_ticket_permissions()
    types = [
        TicketTypeInfo(
            key=t.value,
            label=TICKET_LABELS.get(t, t.value),
            allowed_users=perms.get(t.value, []),
        )
        for t in TicketType
    ]
    return DataResponse(data=PermissionsOut(types=types))


@router.put("/settings/permissions", response_model=DataResponse[PermissionsOut])
def set_permissions(payload: PermissionsIn, user: dict = Depends(get_current_user)):
    require_admin(user)
    set_ticket_permissions_safe(payload.permissions)
    return get_permissions(user)


# ── Groups (Fachabteilungen) ───────────────────────────────────────────────────

class GroupOut(BaseModel):
    id: str
    name: str
    members: list[str]
    distributions: list[str]

class GroupCreate(BaseModel):
    name: str
    distributions: list[str] = []

class GroupUpdate(BaseModel):
    name: str
    members: list[str]
    distributions: list[str]

class MemberIn(BaseModel):
    user_id: str


def _validate_emails(emails: list[str]) -> list[str]:
    cleaned = []
    for m in emails:
        m = m.strip().lower()
        if not EMAIL_REGEX.match(m):
            raise HTTPException(400, f"Ungültige E-Mail: '{m}'")
        cleaned.append(m)
    return list(set(cleaned))


@router.get("/settings/groups", response_model=DataResponse[list[GroupOut]])
def list_groups(user: dict = Depends(get_current_user)):
    require_admin(user)
    groups = db.get_groups()
    for g in groups:
        g.setdefault("distributions", [])
    return DataResponse(data=[GroupOut(**g) for g in groups])


@router.post("/settings/groups", response_model=DataResponse[GroupOut], status_code=201)
def create_group(payload: GroupCreate, user: dict = Depends(get_current_user)):
    require_admin(user)
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "Name erforderlich")
    groups = db.get_groups()
    if any(g["name"].lower() == name.lower() for g in groups):
        raise HTTPException(400, f"Gruppe '{name}' existiert bereits")
    new = {"id": uuid.uuid4().hex, "name": name, "members": [],
           "distributions": _validate_emails(payload.distributions)}
    groups.append(new)
    db.save_groups(groups)
    return DataResponse(data=GroupOut(**new))


@router.put("/settings/groups/{group_id}", response_model=DataResponse[GroupOut])
def update_group(
    group_id: str, payload: GroupUpdate,
    request: Request, user: dict = Depends(get_current_user),
):
    require_admin(user)
    valid_ids = {u["id"] for u in request.app.state.user_cache}
    for m in payload.members:
        if m not in valid_ids:
            raise HTTPException(400, f"Ungültige User-ID '{m}'")
    groups = db.get_groups()
    for g in groups:
        if g["id"] == group_id:
            g["name"] = payload.name.strip()
            g["members"] = payload.members
            g["distributions"] = _validate_emails(payload.distributions)
            db.save_groups(groups)
            return DataResponse(data=GroupOut(**g))
    raise HTTPException(404, "Gruppe nicht gefunden")


@router.delete("/settings/groups/{group_id}", status_code=204)
def delete_group(group_id: str, user: dict = Depends(get_current_user)):
    require_admin(user)
    groups = db.get_groups()
    updated = [g for g in groups if g["id"] != group_id]
    if len(updated) == len(groups):
        raise HTTPException(404, "Gruppe nicht gefunden")
    db.save_groups(updated)


@router.post("/settings/groups/{group_id}/members", response_model=DataResponse[GroupOut])
def add_member(
    group_id: str, payload: MemberIn,
    request: Request, user: dict = Depends(get_current_user),
):
    require_admin(user)
    valid_ids = {u["id"] for u in request.app.state.user_cache}
    if payload.user_id not in valid_ids:
        raise HTTPException(400, f"Ungültige User-ID '{payload.user_id}'")
    groups = db.get_groups()
    for g in groups:
        if g["id"] == group_id:
            if payload.user_id not in g["members"]:
                g["members"].append(payload.user_id)
            db.save_groups(groups)
            return DataResponse(data=GroupOut(**g))
    raise HTTPException(404, "Gruppe nicht gefunden")


@router.delete("/settings/groups/{group_id}/members/{user_id}", response_model=DataResponse[GroupOut])
def remove_member(
    group_id: str, user_id: str, user: dict = Depends(get_current_user),
):
    require_admin(user)
    groups = db.get_groups()
    for g in groups:
        if g["id"] == group_id:
            if user_id not in g["members"]:
                raise HTTPException(400, "User nicht in Gruppe")
            g["members"] = [m for m in g["members"] if m != user_id]
            db.save_groups(groups)
            return DataResponse(data=GroupOut(**g))
    raise HTTPException(404, "Gruppe nicht gefunden")


# ── Test Mail ──────────────────────────────────────────────────────────────────

class TestMailIn(BaseModel):
    to: str

class TestMailOut(BaseModel):
    ok: bool
    message: str


@router.post("/settings/test-mail", response_model=DataResponse[TestMailOut])
def send_testmail(payload: TestMailIn, user: dict = Depends(get_current_user)):
    require_admin(user)
    to = payload.to.strip()
    if not EMAIL_REGEX.match(to):
        raise HTTPException(400, "Ungültige E-Mail-Adresse")
    try:
        send_test_mail(to)
        return DataResponse(data=TestMailOut(ok=True, message=f"Testmail an {to} gesendet"))
    except Exception as e:
        logger.exception("Test mail failed: %s", e)
        raise HTTPException(500, f"Fehler beim Senden: {e}")


# ── Personalnummer Reset ───────────────────────────────────────────────────────

class ResetOut(BaseModel):
    message: str


@router.post("/settings/personalnummer/reset", response_model=DataResponse[ResetOut])
def reset_personalnummer(user: dict = Depends(get_current_user)):
    require_admin(user)
    try:
        from alpharequestmanager.services.personalnummer_generator import reset_personalnummer as _reset
        _reset()
        return DataResponse(data=ResetOut(message="Personalnummer wurde zurückgesetzt"))
    except Exception as e:
        raise HTTPException(500, f"Fehler beim Zurücksetzen: {e}")