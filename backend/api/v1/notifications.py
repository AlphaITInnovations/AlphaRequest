"""
In-App-Benachrichtigungen (Glocke) der angemeldeten Person.

Jede Person sieht und ändert ausschließlich IHRE Einträge (user_id aus der Session,
nie aus dem Request). Die Einträge entstehen in services/process_notifications aus
dem Verlauf; der Mailversand ist davon unabhängig.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from backend.core.dependencies import get_current_user
from backend.database import user_notifications as store
from backend.schemas.responses import DataResponse

router = APIRouter()


class NotificationOut(BaseModel):
    id: int
    ticket_id: Optional[int] = None
    kind: str
    title: str
    body: Optional[str] = None
    link: Optional[str] = None
    actor_name: Optional[str] = None
    created_at: Optional[str] = None
    read_at: Optional[str] = None


class NotificationListOut(BaseModel):
    items: list[NotificationOut]
    unread: int
    #: Gibt es ältere Einträge (für „Ältere laden")?
    has_more: bool


class UnreadOut(BaseModel):
    unread: int


@router.get("/notifications", response_model=DataResponse[NotificationListOut])
def list_notifications(user: dict = Depends(get_current_user),
                       limit: int = Query(20, ge=1, le=100),
                       before: Optional[int] = Query(None, ge=1)):
    """Neueste zuerst; `before` = id des ältesten bereits geladenen Eintrags."""
    rows = store.list_for_user(user["id"], limit=limit + 1, before_id=before)
    return DataResponse(data=NotificationListOut(
        items=[NotificationOut(**r) for r in rows[:limit]],
        unread=store.unread_count(user["id"]),
        has_more=len(rows) > limit,
    ))


@router.get("/notifications/unread-count", response_model=DataResponse[UnreadOut])
def unread_count(user: dict = Depends(get_current_user)):
    """Für die Zahl an der Glocke (Frontend fragt im Hintergrund ab)."""
    return DataResponse(data=UnreadOut(unread=store.unread_count(user["id"])))


@router.post("/notifications/{notification_id}:read", response_model=DataResponse[UnreadOut])
def mark_read(notification_id: int, user: dict = Depends(get_current_user)):
    store.mark_read(user["id"], notification_id)
    return DataResponse(data=UnreadOut(unread=store.unread_count(user["id"])))


@router.post("/notifications:read-all", response_model=DataResponse[UnreadOut])
def mark_all_read(user: dict = Depends(get_current_user)):
    store.mark_all_read(user["id"])
    return DataResponse(data=UnreadOut(unread=0))
