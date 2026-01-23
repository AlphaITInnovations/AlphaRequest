from __future__ import annotations
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Body
from pydantic import BaseModel, Field
from alpharequestmanager.core.dependencies import get_current_user

from alpharequestmanager.services.ticket_overview_service import (
    get_overview_groups,
    add_overview_groups_member,
    remove_overview_groups_member,
    is_overview_groups_member,
    save_overview_groups,
)

router = APIRouter(prefix="/api", tags=["ticket-overview-groups"])


def require_admin(user):
    if not user.get("is_admin"):
        raise HTTPException(403, "Admin privileges required")


# ---------------------------------------------------------------------------
# Schemas (optional, aber sauberer als dict)
# ---------------------------------------------------------------------------
class AddMemberPayload(BaseModel):
    user_id: str = Field(..., min_length=1)


class ReplaceMembersPayload(BaseModel):
    members: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# GET: aktuelle Overview-Gruppe (Liste von User-IDs)
# ---------------------------------------------------------------------------
@router.get("/ticket-overview-groups")
async def list_overview_group_members(user=Depends(get_current_user)):
    require_admin(user)
    return {"members": get_overview_groups()}


# ---------------------------------------------------------------------------
# ADD: Member hinzufügen (idempotent; verhindert Duplikate)
# ---------------------------------------------------------------------------
@router.post("/ticket-overview-groups/members")
async def add_overview_group_member(
    payload: AddMemberPayload = Body(...),
    user=Depends(get_current_user),
):
    require_admin(user)

    try:
        added = add_overview_groups_member(payload.user_id)
    except (TypeError, ValueError) as e:
        raise HTTPException(400, str(e))

    return {"ok": True, "added": added, "members": get_overview_groups()}


# ---------------------------------------------------------------------------
# REMOVE: Member entfernen (idempotent; ok auch wenn nicht drin)
# ---------------------------------------------------------------------------
@router.delete("/ticket-overview-groups/members/{user_id}")
async def remove_overview_group_member(
    user_id: str,
    user=Depends(get_current_user),
):
    require_admin(user)

    try:
        removed = remove_overview_groups_member(user_id)
    except (TypeError, ValueError) as e:
        raise HTTPException(400, str(e))

    return {"ok": True, "removed": removed, "members": get_overview_groups()}


# ---------------------------------------------------------------------------
# OPTIONAL: CHECK
# ---------------------------------------------------------------------------
@router.get("/ticket-overview-groups/members/{user_id}")
async def check_overview_group_member(
    user_id: str,
    user=Depends(get_current_user),
):
    require_admin(user)

    try:
        return {"user_id": user_id.strip(), "is_member": is_overview_groups_member(user_id)}
    except (TypeError, ValueError) as e:
        raise HTTPException(400, str(e))


# ---------------------------------------------------------------------------
# OPTIONAL: REPLACE (setzt komplette Liste, bereinigt & unique)
# ---------------------------------------------------------------------------
@router.put("/ticket-overview-groups")
async def replace_overview_group_members(
    payload: ReplaceMembersPayload = Body(...),
    user=Depends(get_current_user),
):
    require_admin(user)

    try:
        save_overview_groups(payload.members)
    except (TypeError, ValueError) as e:
        raise HTTPException(400, str(e))

    return {"ok": True, "members": get_overview_groups()}
