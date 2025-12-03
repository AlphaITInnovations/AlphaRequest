from fastapi import APIRouter, HTTPException, Depends, Body
from alpharequestmanager.core.dependencies import get_current_user
from alpharequestmanager.database import database as db
from alpharequestmanager.utils.logger import logger
import uuid
from fastapi import Request

router = APIRouter(prefix="/api", tags=["ticket-groups"])


def require_admin(user):
    if not user.get("is_admin"):
        raise HTTPException(403, "Admin privileges required")


# ------------------------------------------------------------------------------
# LIST
# ------------------------------------------------------------------------------
@router.get("/groups")
async def list_groups(user=Depends(get_current_user)):
    require_admin(user)
    return db.get_groups()


# ------------------------------------------------------------------------------
# CREATE
# ------------------------------------------------------------------------------
@router.post("/groups")
async def create_group(
    payload: dict = Body(...),
    user=Depends(get_current_user)
):
    require_admin(user)

    name = payload.get("name", "").strip()
    if not name:
        raise HTTPException(400, "Group 'name' is required")

    groups = db.get_groups()

    # Unique name
    if any(g["name"].lower() == name.lower() for g in groups):
        raise HTTPException(400, f"Group name '{name}' already exists")

    new_group = {
        "id": uuid.uuid4().hex,
        "name": name,
        "members": []
    }

    groups.append(new_group)
    db.save_groups(groups)

    return new_group


# ------------------------------------------------------------------------------
# UPDATE (name + members)
# ------------------------------------------------------------------------------
@router.put("/groups/{group_id}")
async def update_group(
    request: Request,
    group_id: str,
    payload: dict = Body(...),

    user=Depends(get_current_user)
):
    require_admin(user)

    name = payload.get("name", "").strip()
    members = payload.get("members", [])

    # AD-Userliste (User-Cache aus app.state)
    user_cache = request.app.state.user_cache
    valid_ids = {u["id"] for u in user_cache}

    # Validierung
    for m in members:
        if m not in valid_ids:
            raise HTTPException(400, f"Invalid user ID '{m}' in members")

    groups = db.get_groups()

    for g in groups:
        if g["id"] == group_id:
            g["name"] = name
            if members is not None:
                g["members"] = members

            db.save_groups(groups)
            return g

    raise HTTPException(404, "Group not found")


# ------------------------------------------------------------------------------
# DELETE GROUP
# ------------------------------------------------------------------------------
@router.delete("/groups/{group_id}")
async def delete_group(group_id: str, user=Depends(get_current_user)):
    require_admin(user)

    groups = db.get_groups()
    updated = [g for g in groups if g["id"] != group_id]

    if len(updated) == len(groups):
        raise HTTPException(404, "Group not found")

    db.save_groups(updated)
    return {"ok": True}


# ------------------------------------------------------------------------------
# ADD MEMBER
# ------------------------------------------------------------------------------
@router.post("/groups/{group_id}/members")
async def add_member(
    request: Request,
    group_id: str,
    payload: dict = Body(...),
    user=Depends(get_current_user)
):
    require_admin(user)

    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(400, "user_id required")

    user_cache = request.app.state.user_cache
    valid_ids = {u["id"] for u in user_cache}

    if user_id not in valid_ids:
        raise HTTPException(400, f"Invalid user ID '{user_id}'")

    groups = db.get_groups()

    for g in groups:
        if g["id"] == group_id:
            if user_id not in g["members"]:
                g["members"].append(user_id)
            db.save_groups(groups)
            return g

    raise HTTPException(404, "Group not found")



# ------------------------------------------------------------------------------
# REMOVE MEMBER
# ------------------------------------------------------------------------------
@router.delete("/groups/{group_id}/members/{user_id}")
async def remove_member_from_group(
    group_id: str,
    user_id: str,
    user=Depends(get_current_user)
):
    require_admin(user)

    groups = db.get_groups()

    group = next((g for g in groups if g["id"] == group_id), None)
    if not group:
        raise HTTPException(404, "Group not found")

    if user_id not in group["members"]:
        raise HTTPException(400, f"User '{user_id}' not in group")

    group["members"] = [m for m in group["members"] if m != user_id]
    db.save_groups(groups)

    return group
