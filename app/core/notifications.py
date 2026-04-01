from __future__ import annotations

import json
import logging
import random
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"

_firebase_app = None

_NOTIF_TYPE_TITLES: dict[str, str] = {
    "post_reaction": "New reaction",
    "post_comment": "New comment",
    "comment_reply": "New reply",
    "follow": "New follower",
    "voice_vote": "Vote on your voice",
    "voice_reply": "Reply on your voice",
    "message": "New message",
    "series_update": "Series update",
    "system": "Gist",
    "post_bookmarked": "Post saved",
    "mention": "You were mentioned",
    "follower_milestone": "Milestone reached",
    "voice_milestone": "Your voice is trending",
}


def _build_push_body(
    notification_type: str,
    actor_display_name: str | None,
    payload: dict[str, Any],
) -> tuple[str, str]:
    """Return (title, body) for an Expo push message."""
    title = _NOTIF_TYPE_TITLES.get(notification_type, "Gist")
    actor = actor_display_name or "Someone"

    bodies: dict[str, str] = {
        "post_reaction": f"{actor} reacted to your post",
        "post_comment": f"{actor} commented on your post",
        "comment_reply": f"{actor} replied to your comment",
        "follow": f"{actor} started following you",
        "voice_vote": f"{actor} voted on your voice",
        "voice_reply": f"{actor} replied to your voice",
        "message": f"{actor} sent you a message",
        "series_update": payload.get("title", "A series you follow was updated"),  # type: ignore[arg-type]
        "system": payload.get("message", "You have a new notification"),  # type: ignore[arg-type]
        "post_bookmarked": f"{actor} bookmarked your post",
        "mention": f"{actor} mentioned you in a comment",
        "follower_milestone": f"You reached {payload.get('count', '')} followers!",
        "voice_milestone": f"Your voice reached {payload.get('total_votes', '')} votes!",
    }
    return title, bodies.get(notification_type, "You have a new notification")


def send_expo_push(
    push_token: str,
    notification_type: str,
    actor_display_name: str | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Send an Expo push and return parsed delivery metadata."""
    if not push_token or not (
        push_token.startswith("ExponentPushToken[") or push_token.startswith("ExpoPushToken[")
    ):
        return {"ok": False, "reason": "invalid_push_token_format"}

    title, body = _build_push_body(notification_type, actor_display_name, payload)
    try:
        resp = httpx.post(
            EXPO_PUSH_URL,
            json={
                "to": push_token,
                "title": title,
                "body": body,
                "data": {"type": notification_type, **payload},
                "sound": "default",
                "channelId": "default",
            },
            timeout=8,
        )
        resp.raise_for_status()
        parsed: dict[str, Any] = {}
        try:
            parsed = resp.json()
        except Exception:
            parsed = {}

        # Expo returns HTTP 200 even for many delivery errors; inspect ticket status.
        ticket = None
        status = None
        details = None
        data = parsed.get("data") if isinstance(parsed, dict) else None
        if isinstance(data, list) and data:
            ticket = data[0]
        elif isinstance(data, dict):
            ticket = data

        if isinstance(ticket, dict):
            status = ticket.get("status")
            details = ticket.get("details")

        ok = status == "ok"
        if not ok:
            logger.warning(
                "Expo push ticket not ok for token %s: status=%s details=%s body=%s",
                push_token,
                status,
                details,
                parsed,
            )
        return {
            "ok": ok,
            "status": status,
            "details": details,
            "response": parsed,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Expo push failed for token %s: %s", push_token, exc)
        return {"ok": False, "reason": "request_failed", "error": str(exc)}


def _init_firebase_app() -> tuple[object | None, str | None]:
    global _firebase_app
    if _firebase_app is not None:
        return _firebase_app, None

    settings = get_settings()
    try:
        import firebase_admin
        from firebase_admin import credentials
    except Exception as exc:  # noqa: BLE001
        return None, f"firebase_admin_import_failed: {exc}"

    try:
        cred_obj = None
        if settings.fcm_service_account_json.strip():
            data = json.loads(settings.fcm_service_account_json)
            cred_obj = credentials.Certificate(data)
        elif settings.fcm_service_account_json_path.strip():
            cred_obj = credentials.Certificate(settings.fcm_service_account_json_path)

        if cred_obj is None:
            return None, "missing_fcm_service_account"

        options = {"projectId": settings.fcm_project_id} if settings.fcm_project_id.strip() else None
        _firebase_app = firebase_admin.initialize_app(cred_obj, options=options)
        return _firebase_app, None
    except ValueError as exc:
        # Only treat this branch as "already initialized" when the SDK says so.
        # Other ValueError cases indicate malformed credential/options and should surface.
        if "already exists" in str(exc).lower():
            try:
                import firebase_admin

                _firebase_app = firebase_admin.get_app()
                return _firebase_app, None
            except Exception as get_app_exc:  # noqa: BLE001
                return None, f"firebase_get_app_failed: {get_app_exc}"
        return None, f"firebase_init_failed: {exc}"
    except Exception as exc:  # noqa: BLE001
        return None, f"firebase_init_failed: {exc}"


def send_fcm_push(
    push_token: str,
    notification_type: str,
    actor_display_name: str | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if not push_token or len(push_token.strip()) < 20:
        return {"ok": False, "reason": "invalid_fcm_token_format"}

    app, init_error = _init_firebase_app()
    if app is None:
        return {"ok": False, "reason": init_error or "firebase_not_initialized"}

    title, body = _build_push_body(notification_type, actor_display_name, payload)
    try:
        from firebase_admin import messaging

        # Send a visible notification and include custom payload for deep-linking.
        message = messaging.Message(
            token=push_token,
            notification=messaging.Notification(title=title, body=body),
            data={"type": notification_type, **{k: str(v) for k, v in payload.items()}},
            android=messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(channel_id="default", sound="default"),
            ),
        )
        message_id = messaging.send(message, app=app)
        return {"ok": True, "message_id": message_id}
    except Exception as exc:  # noqa: BLE001
        logger.warning("FCM push failed for token %s: %s", push_token[:16], exc)
        return {"ok": False, "reason": "request_failed", "error": str(exc)}


def _send_expo_push(
    push_token: str,
    notification_type: str,
    actor_display_name: str | None,
    payload: dict[str, Any],
) -> None:
    """Fire-and-forget wrapper around send_expo_push."""
    send_expo_push(push_token, notification_type, actor_display_name, payload)


def _send_fcm_push(
    push_token: str,
    notification_type: str,
    actor_display_name: str | None,
    payload: dict[str, Any],
) -> None:
    """Fire-and-forget wrapper around send_fcm_push."""
    send_fcm_push(push_token, notification_type, actor_display_name, payload)


FOLLOWING_POST_DAILY_CAP = 5
TOPIC_INTEREST_DAILY_CAP = 5
SERIES_UPDATE_DAILY_CAP = 4

FOLLOWING_GROUP_WINDOW_HOURS = 2
TOPIC_GROUP_WINDOW_HOURS = 6
SERIES_GROUP_WINDOW_HOURS = 6


def create_notification(
    db: Session,
    *,
    recipient_user_id: int,
    actor_user_id: int | None,
    notification_type: str,
    entity_type: str | None = None,
    entity_id: int | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    if recipient_user_id <= 0:
        return

    if actor_user_id is not None and recipient_user_id == actor_user_id:
        return

    body = payload or {}

    db.execute(
        text(
            """
            INSERT INTO notifications (
                recipient_user_id,
                actor_user_id,
                notification_type,
                entity_type,
                entity_id,
                payload,
                is_read
            ) VALUES (
                :recipient_user_id,
                :actor_user_id,
                :notification_type,
                :entity_type,
                :entity_id,
                CAST(:payload AS jsonb),
                FALSE
            )
            """
        ),
        {
            "recipient_user_id": int(recipient_user_id),
            "actor_user_id": int(actor_user_id) if actor_user_id is not None else None,
            "notification_type": notification_type,
            "entity_type": entity_type,
            "entity_id": int(entity_id) if entity_id is not None else None,
            "payload": json.dumps(body),
        },
    )

    # --- Mobile push delivery ---
    # Look up the recipient's Expo push token and fire a push if present.
    try:
        row = db.execute(
            text("SELECT expo_push_token, fcm_push_token, display_name FROM users WHERE id = :uid"),
            {"uid": int(recipient_user_id)},
        ).one_or_none()
        if row and (row.fcm_push_token or row.expo_push_token):
            # Resolve actor name for the push body.
            actor_name: str | None = None
            if actor_user_id:
                actor_row = db.execute(
                    text("SELECT display_name FROM users WHERE id = :uid"),
                    {"uid": int(actor_user_id)},
                ).one_or_none()
                if actor_row:
                    actor_name = actor_row.display_name
            if row.fcm_push_token:
                _send_fcm_push(row.fcm_push_token, notification_type, actor_name, body)
            elif row.expo_push_token:
                _send_expo_push(row.expo_push_token, notification_type, actor_name, body)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Push lookup failed for user %s: %s", recipient_user_id, exc)


def _count_recent_kind_notifications(db: Session, *, recipient_user_id: int, kind: str) -> int:
    return int(
        db.execute(
            text(
                """
                SELECT COUNT(*)::bigint
                FROM notifications
                WHERE recipient_user_id = :recipient_user_id
                  AND notification_type = 'system'
                  AND payload->>'kind' = :kind
                  AND created_at >= NOW() - INTERVAL '1 day'
                """
            ),
            {
                "recipient_user_id": int(recipient_user_id),
                "kind": kind,
            },
        ).scalar_one()
    )


def _count_recent_series_notifications(db: Session, *, recipient_user_id: int) -> int:
    return int(
        db.execute(
            text(
                """
                SELECT COUNT(*)::bigint
                FROM notifications
                WHERE recipient_user_id = :recipient_user_id
                  AND notification_type = 'series_update'
                  AND created_at >= NOW() - INTERVAL '1 day'
                """
            ),
            {"recipient_user_id": int(recipient_user_id)},
        ).scalar_one()
    )


def _upsert_grouped_system_notification(
    db: Session,
    *,
    recipient_user_id: int,
    actor_user_id: int,
    kind: str,
    window_hours: int,
    post_id: int,
    title: str,
    extra_payload: dict[str, Any],
) -> None:
    row = db.execute(
        text(
            """
            SELECT id, payload
            FROM notifications
            WHERE recipient_user_id = :recipient_user_id
              AND notification_type = 'system'
              AND is_read = FALSE
              AND actor_user_id = :actor_user_id
              AND payload->>'kind' = :kind
              AND created_at >= NOW() - (:window_hours || ' hours')::interval
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """
        ),
        {
            "recipient_user_id": int(recipient_user_id),
            "actor_user_id": int(actor_user_id),
            "kind": kind,
            "window_hours": int(window_hours),
        },
    ).mappings().first()

    if row:
        payload = row.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}
        count = int(payload.get("count", 1)) + 1
        payload.update(extra_payload)
        payload["kind"] = kind
        payload["count"] = count
        payload["latest_post_id"] = int(post_id)
        payload["title"] = title

        db.execute(
            text(
                """
                UPDATE notifications
                SET payload = CAST(:payload AS jsonb),
                    created_at = NOW(),
                    is_read = FALSE,
                    read_at = NULL
                WHERE id = :notification_id
                """
            ),
            {
                "notification_id": int(row["id"]),
                "payload": json.dumps(payload),
            },
        )
        return

    payload = {
        "kind": kind,
        "count": 1,
        "latest_post_id": int(post_id),
        "title": title,
        **extra_payload,
    }
    create_notification(
        db,
        recipient_user_id=int(recipient_user_id),
        actor_user_id=int(actor_user_id),
        notification_type="system",
        entity_type="post",
        entity_id=int(post_id),
        payload=payload,
    )


def _upsert_grouped_topic_interest_notification(
    db: Session,
    *,
    recipient_user_id: int,
    actor_user_id: int,
    topic_id: int,
    post_id: int,
    title: str,
) -> None:
    row = db.execute(
        text(
            """
            SELECT id, payload
            FROM notifications
            WHERE recipient_user_id = :recipient_user_id
              AND notification_type = 'system'
              AND is_read = FALSE
              AND payload->>'kind' = 'topic_interest_post'
              AND payload->>'topic_id' = :topic_id
              AND created_at >= NOW() - (:window_hours || ' hours')::interval
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """
        ),
        {
            "recipient_user_id": int(recipient_user_id),
            "topic_id": str(int(topic_id)),
            "window_hours": int(TOPIC_GROUP_WINDOW_HOURS),
        },
    ).mappings().first()

    if row:
        payload = row.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}
        count = int(payload.get("count", 1)) + 1
        payload.update(
            {
                "kind": "topic_interest_post",
                "topic_id": int(topic_id),
                "latest_post_id": int(post_id),
                "title": title,
                "author_user_id": int(actor_user_id),
                "count": count,
            }
        )

        db.execute(
            text(
                """
                UPDATE notifications
                SET payload = CAST(:payload AS jsonb),
                    created_at = NOW(),
                    is_read = FALSE,
                    read_at = NULL
                WHERE id = :notification_id
                """
            ),
            {
                "notification_id": int(row["id"]),
                "payload": json.dumps(payload),
            },
        )
        return

    create_notification(
        db,
        recipient_user_id=int(recipient_user_id),
        actor_user_id=int(actor_user_id),
        notification_type="system",
        entity_type="post",
        entity_id=int(post_id),
        payload={
            "kind": "topic_interest_post",
            "topic_id": int(topic_id),
            "post_id": int(post_id),
            "author_user_id": int(actor_user_id),
            "title": title,
            "count": 1,
        },
    )


def _upsert_grouped_series_update(
    db: Session,
    *,
    recipient_user_id: int,
    actor_user_id: int,
    series_id: int,
    post_id: int,
    title: str,
) -> None:
    row = db.execute(
        text(
            """
            SELECT id, payload
            FROM notifications
            WHERE recipient_user_id = :recipient_user_id
              AND notification_type = 'series_update'
              AND is_read = FALSE
              AND entity_id = :series_id
              AND created_at >= NOW() - (:window_hours || ' hours')::interval
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """
        ),
        {
            "recipient_user_id": int(recipient_user_id),
            "series_id": int(series_id),
            "window_hours": int(SERIES_GROUP_WINDOW_HOURS),
        },
    ).mappings().first()

    if row:
        payload = row.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}
        count = int(payload.get("count", 1)) + 1
        payload.update(
            {
                "kind": "series_new_post",
                "series_id": int(series_id),
                "latest_post_id": int(post_id),
                "title": title,
                "count": count,
            }
        )
        db.execute(
            text(
                """
                UPDATE notifications
                SET payload = CAST(:payload AS jsonb),
                    created_at = NOW(),
                    is_read = FALSE,
                    read_at = NULL
                WHERE id = :notification_id
                """
            ),
            {
                "notification_id": int(row["id"]),
                "payload": json.dumps(payload),
            },
        )
        return

    create_notification(
        db,
        recipient_user_id=int(recipient_user_id),
        actor_user_id=int(actor_user_id),
        notification_type="series_update",
        entity_type="series",
        entity_id=int(series_id),
        payload={
            "kind": "series_new_post",
            "series_id": int(series_id),
            "post_id": int(post_id),
            "title": title,
            "count": 1,
        },
    )


def fanout_new_post_notifications(
    db: Session,
    *,
    post_id: int,
    author_user_id: int,
    topic_id: int | None,
    series_id: int | None,
    title: str,
) -> None:
    # Follow-based notifications for creator updates.
    follower_ids = db.execute(
        text(
            """
            SELECT follower_user_id
            FROM follows
            WHERE followed_user_id = :author_user_id
            """
        ),
        {"author_user_id": int(author_user_id)},
    ).scalars().all()

    for follower_id in follower_ids:
        rid = int(follower_id)
        if _count_recent_kind_notifications(db, recipient_user_id=rid, kind="following_post") >= FOLLOWING_POST_DAILY_CAP:
            continue

        _upsert_grouped_system_notification(
            db,
            recipient_user_id=rid,
            actor_user_id=int(author_user_id),
            kind="following_post",
            window_hours=FOLLOWING_GROUP_WINDOW_HOURS,
            post_id=int(post_id),
            title=title,
            extra_payload={
                "author_user_id": int(author_user_id),
            },
        )

    # Interest-based notifications inferred from prior engagement in same topic.
    if topic_id is not None:
        interested_ids = db.execute(
            text(
                """
                WITH interested_users AS (
                    SELECT DISTINCT pr.user_id AS uid
                    FROM post_reactions pr
                    JOIN posts p ON p.id = pr.post_id
                    WHERE p.topic_id = :topic_id

                    UNION

                    SELECT DISTINCT c.user_id AS uid
                    FROM comments c
                    JOIN posts p ON p.id = c.post_id
                    WHERE p.topic_id = :topic_id
                      AND c.status = 'published'
                      AND c.user_id IS NOT NULL
                )
                SELECT uid
                FROM interested_users
                WHERE uid IS NOT NULL
                LIMIT 500
                """
            ),
            {"topic_id": int(topic_id)},
        ).scalars().all()

        follower_set = {int(v) for v in follower_ids}
        for interested_user_id in interested_ids:
            uid = int(interested_user_id)
            if uid == int(author_user_id):
                continue
            # Do not duplicate if follow-based notification already exists.
            if uid in follower_set:
                continue
            if _count_recent_kind_notifications(db, recipient_user_id=uid, kind="topic_interest_post") >= TOPIC_INTEREST_DAILY_CAP:
                continue

            _upsert_grouped_topic_interest_notification(
                db,
                recipient_user_id=uid,
                actor_user_id=int(author_user_id),
                topic_id=int(topic_id),
                post_id=int(post_id),
                title=title,
            )

    # Series subscribers receive series update notifications.
    if series_id is not None:
        subscriber_ids = db.execute(
            text(
                """
                SELECT user_id
                FROM series_subscriptions
                WHERE series_id = :series_id
                """
            ),
            {"series_id": int(series_id)},
        ).scalars().all()

        for subscriber_id in subscriber_ids:
            rid = int(subscriber_id)
            if _count_recent_series_notifications(db, recipient_user_id=rid) >= SERIES_UPDATE_DAILY_CAP:
                continue

            _upsert_grouped_series_update(
                db,
                recipient_user_id=rid,
                actor_user_id=int(author_user_id),
                series_id=int(series_id),
                post_id=int(post_id),
                title=title,
            )


_HOURLY_DIGEST_TEMPLATES: list[str] = [
    "{topic}: {title}",
    "Trending in {topic} — {title}",
    "Latest from {topic}: {title}",
    "Don't miss: {title}",
    "New {topic} story you might like",
    "Hot in {topic} right now — {title}",
    "Just in: {title}",
    "People are talking about this in {topic}",
    "Top {topic} update: {title}",
    "Breaking in {topic} — {title}",
    "Fresh from {topic}: {title}",
    "Your {topic} roundup: {title}",
]


def send_hourly_interest_digest(db: Session) -> None:
    """Send one personalised interest-post push to each eligible user once per hour."""
    try:
        user_rows = db.execute(
            text(
                """
                SELECT id, preferred_topic_slugs
                FROM users
                WHERE onboarding_completed = true
                  AND preferred_topic_slugs != '{}'::text[]
                  AND is_active = true
                  AND (fcm_push_token IS NOT NULL OR expo_push_token IS NOT NULL)
                """
            )
        ).mappings().all()

        for user_row in user_rows:
            try:
                user_id = int(user_row["id"])
                slugs = list(user_row["preferred_topic_slugs"] or [])
                if not slugs:
                    continue

                # Skip if an hourly digest was already sent within the last 55 minutes
                recent = db.execute(
                    text(
                        """
                        SELECT id FROM notifications
                        WHERE recipient_user_id = :uid
                          AND notification_type = 'system'
                          AND payload->>'kind' = 'interest_hourly'
                          AND created_at >= NOW() - INTERVAL '55 minutes'
                        LIMIT 1
                        """
                    ),
                    {"uid": user_id},
                ).first()
                if recent:
                    continue

                # Posts already notified about via hourly digest
                notified_post_ids: set[int] = set(
                    int(r)
                    for r in db.execute(
                        text(
                            """
                            SELECT (payload->>'post_id')::int
                            FROM notifications
                            WHERE recipient_user_id = :uid
                              AND notification_type = 'system'
                              AND payload->>'kind' = 'interest_hourly'
                              AND payload->>'post_id' IS NOT NULL
                            """
                        ),
                        {"uid": user_id},
                    ).scalars().all()
                    if r is not None
                )

                # Fresh published posts from user's preferred topics (last 48 h)
                candidates = db.execute(
                    text(
                        """
                                                SELECT p.id, p.title, t.label AS topic_name, p.author_user_id
                        FROM posts p
                        JOIN topics t ON t.id = p.topic_id
                        WHERE t.slug = ANY(:slugs)
                          AND p.status = 'published'
                          AND p.published_at >= NOW() - INTERVAL '48 hours'
                          AND p.author_user_id != :uid
                        ORDER BY p.published_at DESC
                        LIMIT 50
                        """
                    ),
                    {"slugs": slugs, "uid": user_id},
                ).mappings().all()

                fresh = [r for r in candidates if int(r["id"]) not in notified_post_ids]
                if not fresh:
                    continue

                pick = random.choice(fresh)
                post_id = int(pick["id"])
                topic_name: str = pick["topic_name"] or "your topics"
                title: str = pick["title"] or "New post"
                author_uid = pick["author_user_id"]

                tmpl = random.choice(_HOURLY_DIGEST_TEMPLATES)
                message = tmpl.format(topic=topic_name, title=title[:60])

                create_notification(
                    db,
                    recipient_user_id=user_id,
                    actor_user_id=int(author_uid) if author_uid else None,
                    notification_type="system",
                    entity_type="post",
                    entity_id=post_id,
                    payload={
                        "kind": "interest_hourly",
                        "post_id": post_id,
                        "topic_name": topic_name,
                        "title": title,
                        "message": message,
                    },
                )

            except Exception as exc:  # noqa: BLE001
                db.rollback()
                logger.warning("Hourly digest skipped for user %s: %s", user_row.get("id"), exc)

        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("Hourly interest digest run failed: %s", exc)
