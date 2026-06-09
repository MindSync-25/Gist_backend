from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.notifications import create_notification


VALID_INVITE_TYPES = {"generic", "profile", "post", "voice"}
VALID_CHANNELS = {"native_share", "copy_link", "external_social", "dm"}


def _now() -> datetime:
    return datetime.now(UTC)


def build_invite_share_url(token: str) -> str:
    base = get_settings().share_public_base_url.rstrip("/")
    return f"{base}/share/invite/{token}"


def create_invite_link(
    db: Session,
    *,
    inviter_user_id: int,
    invite_type: str,
    channel: str,
    target_entity_type: str | None = None,
    target_entity_id: int | None = None,
) -> dict[str, Any]:
    normalized_type = invite_type.strip().lower()
    normalized_channel = channel.strip().lower()

    if normalized_type not in VALID_INVITE_TYPES:
        raise ValueError("Unsupported invite_type")
    if normalized_channel not in VALID_CHANNELS:
        raise ValueError("Unsupported channel")

    token = secrets.token_urlsafe(18)
    created_at = _now()
    row = db.execute(
        text(
            """
            INSERT INTO invite_links (
                inviter_user_id,
                token,
                invite_type,
                target_entity_type,
                target_entity_id,
                channel,
                created_at,
                updated_at
            ) VALUES (
                :inviter_user_id,
                :token,
                :invite_type,
                :target_entity_type,
                :target_entity_id,
                :channel,
                :created_at,
                :updated_at
            )
            RETURNING id, inviter_user_id, token, invite_type, target_entity_type, target_entity_id, channel, opens_count, last_opened_at, created_at
            """
        ),
        {
            "inviter_user_id": int(inviter_user_id),
            "token": token,
            "invite_type": normalized_type,
            "target_entity_type": target_entity_type,
            "target_entity_id": int(target_entity_id) if target_entity_id is not None else None,
            "channel": normalized_channel,
            "created_at": created_at,
            "updated_at": created_at,
        },
    ).mappings().one()
    return dict(row)


def resolve_invite_link(
    db: Session,
    *,
    token: str,
    actor_user_id: int | None = None,
    record_open: bool = True,
) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            SELECT il.id,
                   il.inviter_user_id,
                   il.token,
                   il.invite_type,
                   il.target_entity_type,
                   il.target_entity_id,
                   il.channel,
                   il.opens_count,
                   il.last_opened_at,
                   il.created_at,
                   inviter.display_name AS inviter_display_name,
                   inviter.username AS inviter_username,
                   inviter.avatar_url AS inviter_avatar_url
            FROM invite_links il
            JOIN users inviter ON inviter.id = il.inviter_user_id
            WHERE il.token = :token
              AND il.is_active = TRUE
            LIMIT 1
            """
        ),
        {"token": token.strip()},
    ).mappings().first()

    if row is None:
        return None

    result = dict(row)
    if record_open:
        opened_at = _now()
        db.execute(
            text(
                """
                UPDATE invite_links
                SET opens_count = opens_count + 1,
                    last_opened_at = :opened_at,
                    updated_at = :opened_at
                WHERE id = :invite_link_id
                """
            ),
            {"opened_at": opened_at, "invite_link_id": int(result["id"])},
        )
        db.execute(
            text(
                """
                INSERT INTO invite_events (invite_link_id, event_type, actor_user_id, metadata)
                VALUES (:invite_link_id, 'open', :actor_user_id, CAST(:metadata AS jsonb))
                """
            ),
            {
                "invite_link_id": int(result["id"]),
                "actor_user_id": int(actor_user_id) if actor_user_id is not None else None,
                "metadata": json.dumps({"token": result["token"]}),
            },
        )
        result["opens_count"] = int(result.get("opens_count") or 0) + 1
        result["last_opened_at"] = opened_at

    return result


def claim_invite_for_user(db: Session, *, invite_token: str | None, user_id: int) -> dict[str, Any] | None:
    if not invite_token:
        return None

    user_row = db.execute(
        text(
            """
            SELECT id, referred_by_invite_link_id
            FROM users
            WHERE id = :user_id
            LIMIT 1
            """
        ),
        {"user_id": int(user_id)},
    ).mappings().first()
    if user_row is None or user_row.get("referred_by_invite_link_id") is not None:
        return None

    invite = resolve_invite_link(db, token=invite_token, actor_user_id=user_id, record_open=False)
    if invite is None or int(invite["inviter_user_id"]) == int(user_id):
        return None

    referred_at = _now()
    db.execute(
        text(
            """
            UPDATE users
            SET referred_by_user_id = :referred_by_user_id,
                referred_by_invite_link_id = :referred_by_invite_link_id,
                updated_at = :updated_at
            WHERE id = :user_id
              AND referred_by_invite_link_id IS NULL
            """
        ),
        {
            "referred_by_user_id": int(invite["inviter_user_id"]),
            "referred_by_invite_link_id": int(invite["id"]),
            "updated_at": referred_at,
            "user_id": int(user_id),
        },
    )

    db.execute(
        text(
            """
            INSERT INTO invite_events (invite_link_id, event_type, actor_user_id, subject_user_id, metadata)
            VALUES (:invite_link_id, 'signup', :actor_user_id, :subject_user_id, CAST(:metadata AS jsonb))
            """
        ),
        {
            "invite_link_id": int(invite["id"]),
            "actor_user_id": int(invite["inviter_user_id"]),
            "subject_user_id": int(user_id),
            "metadata": json.dumps({"token": invite["token"], "claimed_at": referred_at.isoformat()}),
        },
    )
    return invite


def activate_invite_for_user(db: Session, *, user_id: int) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            SELECT id, referred_by_user_id, referred_by_invite_link_id, invite_activated_at, onboarding_completed
            FROM users
            WHERE id = :user_id
            LIMIT 1
            """
        ),
        {"user_id": int(user_id)},
    ).mappings().first()

    if row is None:
        return None
    if row.get("referred_by_invite_link_id") is None or row.get("referred_by_user_id") is None:
        return None
    if row.get("invite_activated_at") is not None or row.get("onboarding_completed") is not True:
        return None

    activated_at = _now()
    db.execute(
        text(
            """
            UPDATE users
            SET invite_activated_at = :activated_at,
                updated_at = :activated_at
            WHERE id = :user_id
              AND invite_activated_at IS NULL
            """
        ),
        {"activated_at": activated_at, "user_id": int(user_id)},
    )
    db.execute(
        text(
            """
            INSERT INTO invite_events (invite_link_id, event_type, actor_user_id, subject_user_id, metadata)
            VALUES (:invite_link_id, 'activate', :actor_user_id, :subject_user_id, CAST(:metadata AS jsonb))
            """
        ),
        {
            "invite_link_id": int(row["referred_by_invite_link_id"]),
            "actor_user_id": int(row["referred_by_user_id"]),
            "subject_user_id": int(user_id),
            "metadata": json.dumps({"activated_at": activated_at.isoformat()}),
        },
    )
    create_notification(
        db,
        recipient_user_id=int(row["referred_by_user_id"]),
        actor_user_id=int(user_id),
        notification_type="system",
        entity_type="invite",
        entity_id=int(row["referred_by_invite_link_id"]),
        payload={
            "kind": "invite_activated",
            "invite_link_id": int(row["referred_by_invite_link_id"]),
            "activated_user_id": int(user_id),
        },
    )
    return {
        "invite_link_id": int(row["referred_by_invite_link_id"]),
        "referred_by_user_id": int(row["referred_by_user_id"]),
        "activated_at": activated_at,
    }


def get_invite_dashboard(db: Session, *, inviter_user_id: int) -> dict[str, Any]:
    links = db.execute(
        text(
            """
            SELECT il.id,
                   il.inviter_user_id,
                   il.token,
                   il.invite_type,
                   il.target_entity_type,
                   il.target_entity_id,
                   il.channel,
                   il.opens_count,
                   il.last_opened_at,
                   il.created_at,
                   COALESCE(signups.signups_count, 0) AS signups_count,
                   COALESCE(activations.activations_count, 0) AS activations_count
            FROM invite_links il
            LEFT JOIN (
                SELECT invite_link_id, COUNT(DISTINCT subject_user_id)::int AS signups_count
                FROM invite_events
                WHERE event_type = 'signup'
                GROUP BY invite_link_id
            ) signups ON signups.invite_link_id = il.id
            LEFT JOIN (
                SELECT invite_link_id, COUNT(DISTINCT subject_user_id)::int AS activations_count
                FROM invite_events
                WHERE event_type = 'activate'
                GROUP BY invite_link_id
            ) activations ON activations.invite_link_id = il.id
            WHERE il.inviter_user_id = :inviter_user_id
            ORDER BY il.created_at DESC
            LIMIT 50
            """
        ),
        {"inviter_user_id": int(inviter_user_id)},
    ).mappings().all()

    totals = {
        "links_count": 0,
        "opens_count": 0,
        "signups_count": 0,
        "activations_count": 0,
    }
    items: list[dict[str, Any]] = []
    for row in links:
        item = dict(row)
        totals["links_count"] += 1
        totals["opens_count"] += int(item.get("opens_count") or 0)
        totals["signups_count"] += int(item.get("signups_count") or 0)
        totals["activations_count"] += int(item.get("activations_count") or 0)
        item["share_url"] = build_invite_share_url(str(item["token"]))
        items.append(item)

    totals["reward_points"] = totals["activations_count"] * 100
    return {**totals, "links": items}