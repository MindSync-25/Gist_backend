from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.core.notifications import create_notification
from app.models.user import User
from app.schemas.message import (
    ConversationCreateDirectIn,
    ConversationOut,
    MessageDeleteOut,
    ConversationParticipantOut,
    MessageCreateIn,
    MessageOut,
)

router = APIRouter(prefix="/messages", tags=["messages"])

_TABLE_READY = False


def _settings():
    return get_settings()


def _dynamo_resource():
    s = _settings()
    kwargs: dict = {"region_name": s.aws_region}
    if s.aws_access_key_id and s.aws_secret_access_key:
        kwargs["aws_access_key_id"] = s.aws_access_key_id
        kwargs["aws_secret_access_key"] = s.aws_secret_access_key
    return boto3.resource("dynamodb", **kwargs)


def _dynamo_client():
    s = _settings()
    kwargs: dict = {"region_name": s.aws_region}
    if s.aws_access_key_id and s.aws_secret_access_key:
        kwargs["aws_access_key_id"] = s.aws_access_key_id
        kwargs["aws_secret_access_key"] = s.aws_secret_access_key
    return boto3.client("dynamodb", **kwargs)


def _table_name() -> str:
    return _settings().dynamodb_messages_table


def _table():
    return _dynamo_resource().Table(_table_name())


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_table_exists() -> None:
    global _TABLE_READY
    if _TABLE_READY:
        return

    client = _dynamo_client()
    table_name = _table_name()

    try:
        client.describe_table(TableName=table_name)
        _TABLE_READY = True
        return
    except client.exceptions.ResourceNotFoundException:
        pass

    client.create_table(
        TableName=table_name,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI1PK", "AttributeType": "S"},
            {"AttributeName": "GSI1SK", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "GSI1",
                "KeySchema": [
                    {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    )
    waiter = client.get_waiter("table_exists")
    waiter.wait(TableName=table_name)
    _TABLE_READY = True


def _direct_conversation_id(user_a: int, user_b: int) -> str:
    lo = min(user_a, user_b)
    hi = max(user_a, user_b)
    return f"dm-{lo}-{hi}"


def _put_conversation_shell(conversation_id: str, participants: list[int], created_by_user_id: int) -> None:
    now = _iso_now()
    t = _table()

    t.put_item(
        Item={
            "PK": f"CONV#{conversation_id}",
            "SK": "META",
            "entity_type": "conversation",
            "conversation_id": conversation_id,
            "conversation_type": "direct",
            "participant_user_ids": participants,
            "created_by_user_id": created_by_user_id,
            "last_message_at": now,
            "last_message_preview": "",
            "created_at": now,
            "updated_at": now,
        }
    )

    for uid in participants:
        t.put_item(
            Item={
                "PK": f"USER#{uid}",
                "SK": f"CONV#{conversation_id}",
                "entity_type": "member",
                "conversation_id": conversation_id,
                "conversation_type": "direct",
                "participant_user_ids": participants,
                "user_id": uid,
                "last_message_at": now,
                "last_message_preview": "",
                "unread_count": 0,
                "GSI1PK": f"USER#{uid}",
                "GSI1SK": now,
                "updated_at": now,
            }
        )


def _get_users_map(db: Session, user_ids: list[int]) -> dict[int, User]:
    if not user_ids:
        return {}
    users = db.execute(select(User).where(User.id.in_(user_ids))).scalars().all()
    return {u.id: u for u in users}


def _build_participants(participant_ids: list[int], users_by_id: dict[int, User]) -> list[ConversationParticipantOut]:
    out: list[ConversationParticipantOut] = []
    for uid in participant_ids:
        user = users_by_id.get(uid)
        out.append(
            ConversationParticipantOut(
                user_id=uid,
                username=user.username if user else None,
                display_name=user.display_name if user else None,
                avatar_url=user.avatar_url if user else None,
            )
        )
    return out


@router.post("/conversations/direct", response_model=ConversationOut)
def create_or_get_direct_conversation(
    payload: ConversationCreateDirectIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConversationOut:
    if payload.other_user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot create a conversation with yourself")

    other_user = db.get(User, payload.other_user_id)
    if other_user is None or not other_user.is_active:
        raise HTTPException(status_code=404, detail="Recipient user not found")

    _ensure_table_exists()
    conversation_id = _direct_conversation_id(current_user.id, payload.other_user_id)
    t = _table()
    now = _iso_now()

    meta = t.get_item(Key={"PK": f"CONV#{conversation_id}", "SK": "META"}).get("Item")
    if meta is None:
        _put_conversation_shell(conversation_id, [current_user.id, payload.other_user_id], current_user.id)
        meta = t.get_item(Key={"PK": f"CONV#{conversation_id}", "SK": "META"}).get("Item")

    participant_ids = [int(v) for v in meta.get("participant_user_ids", [])]
    users_by_id = _get_users_map(db, participant_ids)

    member_item = t.get_item(
        Key={
            "PK": f"USER#{current_user.id}",
            "SK": f"CONV#{conversation_id}",
        }
    ).get("Item")

    return ConversationOut(
        id=conversation_id,
        conversation_type=str(meta.get("conversation_type", "direct")),
        participants=_build_participants(participant_ids, users_by_id),
        last_message_preview=str(meta.get("last_message_preview", "")),
        last_message_at=str(meta.get("last_message_at", now)),
        unread_count=int((member_item or {}).get("unread_count", 0)),
        updated_at=str(meta.get("updated_at", now)),
    )


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ConversationOut]:
    _ensure_table_exists()
    t = _table()

    result = t.query(
        IndexName="GSI1",
        KeyConditionExpression="GSI1PK = :pk",
        ExpressionAttributeValues={":pk": f"USER#{current_user.id}"},
        ScanIndexForward=False,
        Limit=limit,
    )
    member_items = result.get("Items", [])
    if not member_items:
        return []

    conversation_ids = [str(item.get("conversation_id", "")) for item in member_items if item.get("conversation_id")]
    meta_items: dict[str, dict] = {}
    participant_ids: set[int] = set()

    for cid in conversation_ids:
        meta = t.get_item(Key={"PK": f"CONV#{cid}", "SK": "META"}).get("Item")
        if not meta:
            continue
        meta_items[cid] = meta
        for uid in meta.get("participant_user_ids", []):
            participant_ids.add(int(uid))

    users_by_id = _get_users_map(db, list(participant_ids))
    now = _iso_now()
    out: list[ConversationOut] = []

    for member in member_items:
        cid = str(member.get("conversation_id", ""))
        if not cid or cid not in meta_items:
            continue
        meta = meta_items[cid]
        pids = [int(v) for v in meta.get("participant_user_ids", [])]
        out.append(
            ConversationOut(
                id=cid,
                conversation_type=str(meta.get("conversation_type", "direct")),
                participants=_build_participants(pids, users_by_id),
                last_message_preview=str(member.get("last_message_preview", meta.get("last_message_preview", ""))),
                last_message_at=str(member.get("last_message_at", meta.get("last_message_at", now))),
                unread_count=int(member.get("unread_count", 0)),
                updated_at=str(meta.get("updated_at", now)),
            )
        )

    return out


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def list_messages(
    conversation_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[MessageOut]:
    _ensure_table_exists()
    t = _table()

    member_item = t.get_item(
        Key={"PK": f"USER#{current_user.id}", "SK": f"CONV#{conversation_id}"}
    ).get("Item")
    if member_item is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    result = t.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
        ExpressionAttributeValues={
            ":pk": f"CONV#{conversation_id}",
            ":prefix": "MSG#",
        },
        ScanIndexForward=False,
        Limit=limit,
    )
    items = list(reversed(result.get("Items", [])))

    sender_ids = list({int(item["sender_user_id"]) for item in items if item.get("sender_user_id") is not None})
    users_by_id = _get_users_map(db, sender_ids)

    return [
        MessageOut(
            id=str(item.get("message_id", "")),
            conversation_id=conversation_id,
            sender_user_id=int(item.get("sender_user_id")) if item.get("sender_user_id") is not None else None,
            sender_username=users_by_id.get(int(item["sender_user_id"])).username
            if item.get("sender_user_id") is not None and int(item["sender_user_id"]) in users_by_id
            else None,
            sender_display_name=users_by_id.get(int(item["sender_user_id"])).display_name
            if item.get("sender_user_id") is not None and int(item["sender_user_id"]) in users_by_id
            else None,
            body=item.get("body"),
            message_type=str(item.get("message_type", "text")),
            shared_post_id=int(item["shared_post_id"]) if item.get("shared_post_id") is not None else None,
            created_at=str(item.get("created_at", _iso_now())),
        )
        for item in items
    ]


@router.post("/conversations/{conversation_id}/messages", response_model=MessageOut)
def send_message(
    conversation_id: str,
    payload: MessageCreateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageOut:
    _ensure_table_exists()
    t = _table()

    member_item = t.get_item(
        Key={"PK": f"USER#{current_user.id}", "SK": f"CONV#{conversation_id}"}
    ).get("Item")
    if member_item is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if payload.message_type == "text" and not (payload.body and payload.body.strip()):
        raise HTTPException(status_code=400, detail="Message body is required for text messages")

    if payload.message_type == "post_share" and payload.shared_post_id is None:
        raise HTTPException(status_code=400, detail="shared_post_id is required for shared post messages")

    now = _iso_now()
    message_id = str(uuid4())
    body = payload.body.strip() if payload.body else None
    preview = body or (f"Shared post #{payload.shared_post_id}" if payload.shared_post_id is not None else "")

    t.put_item(
        Item={
            "PK": f"CONV#{conversation_id}",
            "SK": f"MSG#{now}#{message_id}",
            "entity_type": "message",
            "conversation_id": conversation_id,
            "message_id": message_id,
            "sender_user_id": current_user.id,
            "body": body,
            "message_type": payload.message_type,
            "shared_post_id": payload.shared_post_id,
            "created_at": now,
        }
    )

    meta = t.get_item(Key={"PK": f"CONV#{conversation_id}", "SK": "META"}).get("Item")
    if meta is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    participant_ids = [int(v) for v in meta.get("participant_user_ids", [])]
    t.update_item(
        Key={"PK": f"CONV#{conversation_id}", "SK": "META"},
        UpdateExpression="SET last_message_at=:lma, last_message_preview=:lmp, updated_at=:upd",
        ExpressionAttributeValues={":lma": now, ":lmp": preview, ":upd": now},
    )

    for uid in participant_ids:
        incr = 0 if uid == current_user.id else 1
        try:
            t.update_item(
                Key={"PK": f"USER#{uid}", "SK": f"CONV#{conversation_id}"},
                UpdateExpression=(
                    "SET last_message_at=:lma, last_message_preview=:lmp, GSI1PK=:gpk, GSI1SK=:gsk, "
                    "updated_at=:upd ADD unread_count :inc"
                ),
                ExpressionAttributeValues={
                    ":lma": now,
                    ":lmp": preview,
                    ":gpk": f"USER#{uid}",
                    ":gsk": now,
                    ":upd": now,
                    ":inc": incr,
                },
            )
        except ClientError:
            # If a membership item is missing (rare race), recreate minimal membership row.
            t.put_item(
                Item={
                    "PK": f"USER#{uid}",
                    "SK": f"CONV#{conversation_id}",
                    "entity_type": "member",
                    "conversation_id": conversation_id,
                    "conversation_type": str(meta.get("conversation_type", "direct")),
                    "participant_user_ids": participant_ids,
                    "user_id": uid,
                    "last_message_at": now,
                    "last_message_preview": preview,
                    "unread_count": incr,
                    "GSI1PK": f"USER#{uid}",
                    "GSI1SK": now,
                    "updated_at": now,
                }
            )

    wrote_notifications = False
    try:
        for uid in participant_ids:
            if int(uid) == int(current_user.id):
                continue
            create_notification(
                db,
                recipient_user_id=int(uid),
                actor_user_id=int(current_user.id),
                notification_type="message",
                entity_type="conversation",
                entity_id=None,
                payload={
                    "kind": "new_message",
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                    "preview": preview,
                },
            )
            wrote_notifications = True
        if wrote_notifications:
            db.commit()
    except Exception:
        if wrote_notifications:
            db.rollback()

    return MessageOut(
        id=message_id,
        conversation_id=conversation_id,
        sender_user_id=current_user.id,
        sender_username=current_user.username,
        sender_display_name=current_user.display_name,
        body=body,
        message_type=payload.message_type,
        shared_post_id=payload.shared_post_id,
        created_at=now,
    )


@router.delete("/conversations/{conversation_id}/messages/{message_id}", response_model=MessageDeleteOut)
def delete_message(
    conversation_id: str,
    message_id: str,
    current_user: User = Depends(get_current_user),
) -> MessageDeleteOut:
    _ensure_table_exists()
    t = _table()

    member_item = t.get_item(
        Key={"PK": f"USER#{current_user.id}", "SK": f"CONV#{conversation_id}"}
    ).get("Item")
    if member_item is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conv_pk = f"CONV#{conversation_id}"
    last_evaluated_key: dict | None = None
    message_item: dict | None = None

    while True:
        query_kwargs = {
            "KeyConditionExpression": "PK = :pk AND begins_with(SK, :prefix)",
            "ExpressionAttributeValues": {
                ":pk": conv_pk,
                ":prefix": "MSG#",
            },
            "ProjectionExpression": "PK, SK, message_id, sender_user_id",
        }
        if last_evaluated_key is not None:
            query_kwargs["ExclusiveStartKey"] = last_evaluated_key

        result = t.query(**query_kwargs)
        for item in result.get("Items", []):
            if str(item.get("message_id", "")) == message_id:
                message_item = item
                break

        if message_item is not None:
            break

        last_evaluated_key = result.get("LastEvaluatedKey")
        if not last_evaluated_key:
            break

    if message_item is None:
        raise HTTPException(status_code=404, detail="Message not found")

    sender_user_id = message_item.get("sender_user_id")
    if sender_user_id is None or int(sender_user_id) != current_user.id:
        raise HTTPException(status_code=403, detail="You can only delete your own message")

    t.delete_item(
        Key={
            "PK": conv_pk,
            "SK": str(message_item["SK"]),
        }
    )

    meta = t.get_item(Key={"PK": conv_pk, "SK": "META"}).get("Item")
    if meta is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    latest_result = t.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
        ExpressionAttributeValues={
            ":pk": conv_pk,
            ":prefix": "MSG#",
        },
        ScanIndexForward=False,
        Limit=1,
    )
    latest_items = latest_result.get("Items", [])

    if latest_items:
        latest = latest_items[0]
        latest_at = str(latest.get("created_at", _iso_now()))
        latest_preview = str(
            latest.get("body")
            or (
                f"Shared post #{latest.get('shared_post_id')}"
                if latest.get("shared_post_id") is not None
                else ""
            )
        )
    else:
        latest_at = str(meta.get("created_at", _iso_now()))
        latest_preview = ""

    t.update_item(
        Key={"PK": conv_pk, "SK": "META"},
        UpdateExpression="SET last_message_at=:lma, last_message_preview=:lmp, updated_at=:upd",
        ExpressionAttributeValues={":lma": latest_at, ":lmp": latest_preview, ":upd": _iso_now()},
    )

    participant_ids = [int(v) for v in meta.get("participant_user_ids", [])]
    for uid in participant_ids:
        member_key = {"PK": f"USER#{uid}", "SK": f"CONV#{conversation_id}"}
        member = t.get_item(Key=member_key).get("Item")
        unread_count = int((member or {}).get("unread_count", 0))
        if uid != current_user.id and unread_count > 0:
            unread_count -= 1

        t.update_item(
            Key=member_key,
            UpdateExpression=(
                "SET last_message_at=:lma, last_message_preview=:lmp, "
                "GSI1PK=:gpk, GSI1SK=:gsk, unread_count=:uc, updated_at=:upd"
            ),
            ExpressionAttributeValues={
                ":lma": latest_at,
                ":lmp": latest_preview,
                ":gpk": f"USER#{uid}",
                ":gsk": latest_at,
                ":uc": unread_count,
                ":upd": _iso_now(),
            },
        )

    return MessageDeleteOut(ok=True, conversation_id=conversation_id, message_id=message_id)
