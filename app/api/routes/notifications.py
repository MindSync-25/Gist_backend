from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.avatar_signing import build_avatar_display_url
from app.core.database import get_db
from app.models.user import User
from app.schemas.notification import (
    NotificationOut,
    NotificationReadAllOut,
    NotificationReadOut,
    NotificationUnreadCountOut,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[NotificationOut]:
    rows = db.execute(
        text(
            """
            SELECT
                n.id,
                n.recipient_user_id,
                n.actor_user_id,
                n.notification_type,
                n.entity_type,
                n.entity_id,
                n.payload,
                n.is_read,
                n.created_at,
                n.read_at,
                u.display_name AS actor_display_name,
                u.avatar_url AS actor_avatar_url
            FROM notifications n
            LEFT JOIN users u ON u.id = n.actor_user_id
            WHERE n.recipient_user_id = :recipient_user_id
              AND (:unread_only = FALSE OR n.is_read = FALSE)
            ORDER BY n.created_at DESC, n.id DESC
            LIMIT :limit
            OFFSET :offset
            """
        ),
        {
            "recipient_user_id": int(current_user.id),
            "unread_only": bool(unread_only),
            "limit": int(limit),
            "offset": int(offset),
        },
    ).mappings().all()

    out: list[NotificationOut] = []
    for row in rows:
        avatar_display_url, avatar_display_expires_at = build_avatar_display_url(row.get("actor_avatar_url"))
        out.append(
            NotificationOut(
                id=int(row["id"]),
                recipient_user_id=int(row["recipient_user_id"]),
                actor_user_id=int(row["actor_user_id"]) if row["actor_user_id"] is not None else None,
                actor_display_name=row.get("actor_display_name"),
                actor_avatar_url=row.get("actor_avatar_url"),
                actor_avatar_display_url=avatar_display_url,
                actor_avatar_display_expires_at=avatar_display_expires_at,
                notification_type=str(row["notification_type"]),
                entity_type=row.get("entity_type"),
                entity_id=int(row["entity_id"]) if row["entity_id"] is not None else None,
                payload=row.get("payload") or {},
                is_read=bool(row["is_read"]),
                created_at=row["created_at"],
                read_at=row.get("read_at"),
            )
        )
    return out


@router.get("/unread-count", response_model=NotificationUnreadCountOut)
def unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationUnreadCountOut:
    count = db.execute(
        text(
            """
            SELECT COUNT(*)::bigint AS unread_count
            FROM notifications
            WHERE recipient_user_id = :recipient_user_id
              AND is_read = FALSE
            """
        ),
        {"recipient_user_id": int(current_user.id)},
    ).scalar_one()

    return NotificationUnreadCountOut(unread_count=int(count))


@router.patch("/{notification_id}/read", response_model=NotificationReadOut)
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationReadOut:
    row = db.execute(
        text(
            """
            UPDATE notifications
            SET is_read = TRUE,
                read_at = NOW()
            WHERE id = :notification_id
              AND recipient_user_id = :recipient_user_id
              AND is_read = FALSE
            RETURNING id
            """
        ),
        {
            "notification_id": int(notification_id),
            "recipient_user_id": int(current_user.id),
        },
    ).first()
    db.commit()

    return NotificationReadOut(
        ok=True,
        notification_id=int(notification_id if row is None else row[0]),
        is_read=True,
    )


@router.patch("/read-all", response_model=NotificationReadAllOut)
def mark_all_notifications_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationReadAllOut:
    result = db.execute(
        text(
            """
            UPDATE notifications
            SET is_read = TRUE,
                read_at = NOW()
            WHERE recipient_user_id = :recipient_user_id
              AND is_read = FALSE
            """
        ),
        {"recipient_user_id": int(current_user.id)},
    )
    db.commit()
    marked = int(result.rowcount or 0)
    return NotificationReadAllOut(ok=True, marked_count=marked)
