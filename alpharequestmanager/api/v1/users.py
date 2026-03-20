from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel
from alpharequestmanager.core.dependencies import get_current_user
from alpharequestmanager.schemas.responses import DataResponse

router = APIRouter()


class UserEntry(BaseModel):
    id: str
    displayName: str
    mail: str | None = None


class UserListResponse(BaseModel):
    users: list[UserEntry]


@router.get("/users", response_model=DataResponse[UserListResponse])
def list_users(request: Request, user: dict = Depends(get_current_user)):
    """Gibt alle gecachten AD-User zurück – für Dropdowns im Frontend."""
    user_cache = getattr(request.app.state, "user_cache", [])
    users = [
        UserEntry(
            id=u.get("id", ""),
            displayName=u.get("displayName", ""),
            mail=u.get("mail") or u.get("email"),
        )
        for u in user_cache
        if u.get("id") and u.get("displayName")
    ]
    return DataResponse(data=UserListResponse(users=users))