import json
import re
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from jose import jwt
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.notifications import create_notification
from app.core.config import get_settings
from app.core.r2 import extract_r2_bucket_and_key
from app.models.user import User
from app.models.prediction import Prediction, PredictionEstimate
from app.models.voice_issue import VoiceIssue
from app.models.voice_live import VoiceLiveParticipant, VoiceLiveSession
from app.models.voice_poll import VoicePoll, VoicePollOption, VoicePollVote
from app.models.voice_stance import VoiceStance
from app.models.voice_take import VoiceTake
from app.schemas.voice import (
    ParticipationStreamItem,
    TopTakeOut,
    TopVoiceOut,
    VoiceUserActivityItemOut,
    VoiceTakeDeleteOut,
    VoiceIssueCreateIn,
    VoiceIssueUpdateIn,
    VoiceIssueOut,
    VoicePollCreateIn,
    VoicePollOut,
    VoicePollOptionOut,
    VoicePollVoteIn,
    VoicePollVoteOut,
    PredictionCreateIn,
    PredictionEstimateIn,
    PredictionEstimateOut,
    PredictionOut,
    VoiceStanceIn,
    VoiceStanceOut,
    VoiceTakeCreateIn,
    VoiceTakeOut,
    VoiceTakeReplyOut,
    VoiceLiveEndIn,
    VoiceLiveConnectionIn,
    VoiceLiveConnectionOut,
    VoiceLiveInviteIn,
    VoiceLiveJoinIn,
    VoiceLiveParticipantOut,
    VoiceLiveSessionCreateIn,
    VoiceLiveSessionOut,
)

router = APIRouter(prefix="/voice", tags=["voice"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_slug(title: str) -> str:
    """Generate a URL-safe slug from a title with a short unique suffix."""
    base = re.sub(r'[^\w\s-]', '', title.lower()).strip()
    base = re.sub(r'[\s_]+', '-', base)
    base = re.sub(r'-+', '-', base)[:80].rstrip('-')
    suffix = uuid.uuid4().hex[:8]
    return f"{base}-{suffix}"


def _parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


def _validate_take_audio_url(audio_url: str | None) -> str | None:
    if not audio_url:
        return None

    parsed = extract_r2_bucket_and_key(audio_url)
    if not parsed:
        raise HTTPException(status_code=422, detail="audio_url must be an R2 object URL")

    _, key = parsed
    settings = get_settings()
    if not key.startswith(settings.r2_user_uploads_prefix):
        raise HTTPException(status_code=422, detail="audio_url must point to user-uploads")

    return audio_url


def _issue_to_out(
    issue: VoiceIssue,
    viewer_stance: str | None = None,
    live_session: VoiceLiveSession | None = None,
) -> VoiceIssueOut:
    return VoiceIssueOut(
        id=issue.id,
        title=issue.title,
        context=issue.context,
        tags=_parse_tags(issue.tags),
        created_by_type=issue.created_by_type,
        created_by_user_id=issue.created_by_user_id,
        is_featured=issue.is_featured,
        support_count=issue.support_count,
        oppose_count=issue.oppose_count,
        question_count=issue.question_count,
        takes_count=issue.takes_count,
        reacting_now=issue.support_count + issue.oppose_count + issue.question_count,
        cover_image_url=issue.cover_image_url,
        expires_at=issue.expires_at,
        created_at=issue.created_at,
        viewer_stance=viewer_stance,
        is_live_debate=live_session is not None and live_session.status == "active",
        live_session_id=live_session.id if live_session else None,
        live_session_status=live_session.status if live_session else None,
        live_provider=live_session.provider if live_session else None,
        live_join_url=live_session.join_url if live_session else None,
    )


def _active_live_session_for_issue(db: Session, issue_id: int) -> VoiceLiveSession | None:
    return db.execute(
        select(VoiceLiveSession)
        .where(VoiceLiveSession.issue_id == issue_id, VoiceLiveSession.status == "active")
        .order_by(VoiceLiveSession.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _build_live_join_url(room_slug: str) -> str:
    return f"gist://voice/live?room={room_slug}"


def _normalize_invitee_ids(invitee_user_ids: list[int], host_user_id: int) -> list[int]:
    seen: set[int] = set()
    normalized: list[int] = []
    for raw_id in invitee_user_ids:
        user_id = int(raw_id)
        if user_id <= 0 or user_id == host_user_id or user_id in seen:
            continue
        seen.add(user_id)
        normalized.append(user_id)
    if len(normalized) > 7:
        raise HTTPException(status_code=422, detail="You can invite up to 7 friends")
    return normalized


def _live_session_to_out(db: Session, session: VoiceLiveSession) -> VoiceLiveSessionOut:
    rows = db.execute(
        select(VoiceLiveParticipant, User)
        .join(User, User.id == VoiceLiveParticipant.user_id)
        .where(VoiceLiveParticipant.session_id == session.id)
        .order_by(VoiceLiveParticipant.role.asc(), VoiceLiveParticipant.created_at.asc())
    ).all()

    participants = [
        VoiceLiveParticipantOut(
            user_id=participant.user_id,
            display_name=user.display_name,
            username=user.username,
            avatar_url=user.avatar_url,
            role=participant.role,
            status=participant.status,
            joined_at=participant.joined_at,
        )
        for participant, user in rows
    ]
    active_count = sum(1 for item in participants if item.status == "joined")
    invited_count = sum(1 for item in participants if item.role == "member")
    return VoiceLiveSessionOut(
        id=session.id,
        issue_id=session.issue_id,
        room_slug=session.room_slug,
        provider=session.provider,
        status=session.status,
        join_url=session.join_url,
        host_user_id=session.host_user_id,
        started_at=session.started_at,
        ended_at=session.ended_at,
        max_participants=session.max_participants,
        active_participants_count=active_count,
        invited_count=invited_count,
        available_invites=max(0, session.max_participants - 1 - invited_count),
        participants=participants,
    )


def _ensure_live_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def _livekit_connection_out(
    *,
    db: Session,
    session: VoiceLiveSession,
    user_id: int,
    requested_role: str,
) -> VoiceLiveConnectionOut:
    settings = get_settings()
    if not settings.livekit_url or not settings.livekit_api_key or not settings.livekit_api_secret:
        raise HTTPException(
            status_code=503,
            detail="Live streaming is not configured. Set LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET.",
        )

    user = _ensure_live_user(db, user_id)
    participant = db.execute(
        select(VoiceLiveParticipant)
        .where(VoiceLiveParticipant.session_id == session.id, VoiceLiveParticipant.user_id == user_id)
    ).scalar_one_or_none()

    is_host = session.host_user_id == user_id
    wants_publish = requested_role in {"host", "speaker"}
    if requested_role == "host" and not is_host:
        raise HTTPException(status_code=403, detail="Only the host can publish as host")
    if wants_publish and not is_host and (not participant or participant.invited_by_user_id is None):
        raise HTTPException(status_code=403, detail="Only invited speakers can publish in this live")

    if wants_publish and participant:
        participant.status = "joined"
        participant.joined_at = datetime.now(timezone.utc)
        participant.left_at = None
        db.commit()

    can_publish = bool(wants_publish)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=6)
    identity = f"user-{user.id}"
    room_name = session.room_slug
    payload = {
        "iss": settings.livekit_api_key,
        "sub": identity,
        "name": user.display_name or user.username or identity,
        "nbf": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "metadata": json.dumps(
            {
                "user_id": user.id,
                "issue_id": session.issue_id,
                "live_session_id": session.id,
                "role": "host" if is_host else ("speaker" if can_publish else "viewer"),
            }
        ),
        "video": {
            "roomJoin": True,
            "room": room_name,
            "canPublish": can_publish,
            "canSubscribe": True,
            "canPublishData": True,
            "roomAdmin": bool(is_host),
        },
    }
    token = jwt.encode(payload, settings.livekit_api_secret, algorithm="HS256")
    return VoiceLiveConnectionOut(
        provider="livekit",
        server_url=settings.livekit_url,
        token=token,
        room_name=room_name,
        identity=identity,
        can_publish=can_publish,
    )


def _add_live_invites(
    db: Session,
    session: VoiceLiveSession,
    *,
    inviter_user_id: int,
    invitee_user_ids: list[int],
) -> None:
    invitee_ids = _normalize_invitee_ids(invitee_user_ids, inviter_user_id)
    if not invitee_ids:
        return

    users = db.execute(select(User).where(User.id.in_(invitee_ids), User.is_active.is_(True))).scalars().all()
    found_ids = {int(user.id) for user in users}
    missing_ids = [user_id for user_id in invitee_ids if user_id not in found_ids]
    if missing_ids:
        raise HTTPException(status_code=404, detail=f"Invitee not found: {missing_ids[0]}")

    existing_participants = db.execute(
        select(VoiceLiveParticipant)
        .where(VoiceLiveParticipant.session_id == session.id)
    ).scalars().all()
    existing_user_ids = {int(participant.user_id) for participant in existing_participants}
    existing_member_count = sum(1 for participant in existing_participants if participant.role == "member")
    new_invitee_ids = [invitee_id for invitee_id in invitee_ids if invitee_id not in existing_user_ids]
    if existing_member_count + len(new_invitee_ids) > session.max_participants - 1:
        raise HTTPException(status_code=422, detail="Live rooms support the host plus 7 invited friends")

    for invitee_id in new_invitee_ids:
        db.add(
            VoiceLiveParticipant(
                session_id=session.id,
                user_id=invitee_id,
                role="member",
                status="invited",
                invited_by_user_id=inviter_user_id,
            )
        )


def _format_time_info(closes_at: datetime | None) -> str:
    if not closes_at:
        return "Ongoing"
    now = datetime.now(timezone.utc)
    diff = closes_at - now
    if diff.total_seconds() <= 0:
        return "Closed"
    total_minutes = int(diff.total_seconds() // 60)
    hours = total_minutes // 60
    minutes = total_minutes % 60
    if hours > 0:
        return f"Closes in {hours}h {minutes}m"
    return f"Closes in {minutes}m"


def _poll_options_with_pct(options: list[VoicePollOption], total_votes: int) -> list[VoicePollOptionOut]:
    return [
        VoicePollOptionOut(
            id=opt.id,
            label=opt.label,
            percentage=round((opt.votes_count / total_votes * 100) if total_votes > 0 else 0, 1),
            votes=opt.votes_count,
        )
        for opt in options
    ]


def _prediction_average(prediction: Prediction) -> float | None:
    if prediction.estimates_count <= 0:
        return None
    return round(prediction.estimates_sum / prediction.estimates_count, 1)


def _prediction_to_out(
    prediction: Prediction,
    creator: User | None = None,
    viewer_estimate: int | None = None,
) -> PredictionOut:
    return PredictionOut(
        id=prediction.id,
        creator_user_id=prediction.creator_user_id,
        creator_name=creator.display_name if creator else None,
        creator_avatar_url=creator.avatar_url if creator else None,
        statement=prediction.statement,
        context=prediction.context or "",
        topic=prediction.topic,
        estimates_count=prediction.estimates_count,
        crowd_average=_prediction_average(prediction),
        viewer_estimate=viewer_estimate,
        created_at=prediction.created_at,
    )


def _delete_expired_polls(db: Session) -> None:
    now = datetime.now(timezone.utc)
    db.execute(
        text(
            """
            DELETE FROM voice_polls
            WHERE closes_at IS NOT NULL
              AND closes_at <= :now
            """
        ),
        {"now": now},
    )
    db.commit()


# ---------------------------------------------------------------------------
# Issues
# ---------------------------------------------------------------------------

@router.get("/issues/featured", response_model=VoiceIssueOut)
def get_featured_issue(
    viewer_user_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> VoiceIssueOut:
    now = datetime.now(timezone.utc)
    issue = db.execute(
        select(VoiceIssue)
        .where(
            VoiceIssue.is_featured.is_(True),
            VoiceIssue.status == "open",
            (VoiceIssue.expires_at.is_(None)) | (VoiceIssue.expires_at > now),
        )
        .order_by(VoiceIssue.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    if not issue:
        raise HTTPException(status_code=404, detail="No featured issue found")

    viewer_stance: str | None = None
    if viewer_user_id:
        row = db.execute(
            select(VoiceStance.stance)
            .where(VoiceStance.issue_id == issue.id, VoiceStance.user_id == viewer_user_id)
        ).scalar_one_or_none()
        viewer_stance = row

    return _issue_to_out(issue, viewer_stance, _active_live_session_for_issue(db, issue.id))


@router.get("/issues", response_model=list[VoiceIssueOut])
def list_issues(
    filter: str = Query(default="Trending"),
    q: str = Query(default=""),
    viewer_user_id: int | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[VoiceIssueOut]:
    now = datetime.now(timezone.utc)
    stmt = (
        select(VoiceIssue)
        .where(
            VoiceIssue.status == "open",
            VoiceIssue.is_featured.is_(False),
            (VoiceIssue.expires_at.is_(None)) | (VoiceIssue.expires_at > now),
        )
        .order_by(VoiceIssue.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    if filter and filter != "Trending":
        stmt = stmt.where(VoiceIssue.tags.contains(filter))

    if q.strip():
        needle = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            func.lower(VoiceIssue.title).like(needle)
            | func.lower(VoiceIssue.context).like(needle)
        )

    issues = db.execute(stmt).scalars().all()

    if not issues:
        return []

    # Fetch viewer stances in one query
    stance_map: dict[int, str] = {}
    if viewer_user_id:
        issue_ids = [i.id for i in issues]
        rows = db.execute(
            select(VoiceStance.issue_id, VoiceStance.stance)
            .where(VoiceStance.user_id == viewer_user_id, VoiceStance.issue_id.in_(issue_ids))
        ).all()
        stance_map = {row.issue_id: row.stance for row in rows}

    active_live_rows = db.execute(
        select(VoiceLiveSession)
        .where(
            VoiceLiveSession.issue_id.in_([issue.id for issue in issues]),
            VoiceLiveSession.status == "active",
        )
        .order_by(VoiceLiveSession.created_at.desc())
    ).scalars().all()
    live_by_issue: dict[int, VoiceLiveSession] = {}
    for live_session in active_live_rows:
        live_by_issue.setdefault(live_session.issue_id, live_session)

    return [_issue_to_out(issue, stance_map.get(issue.id), live_by_issue.get(issue.id)) for issue in issues]


@router.get("/issues/{issue_id}", response_model=VoiceIssueOut)
def get_issue(
    issue_id: int,
    viewer_user_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> VoiceIssueOut:
    issue = db.get(VoiceIssue, issue_id)
    if not issue or issue.status == "archived":
        raise HTTPException(status_code=404, detail="Issue not found")

    viewer_stance: str | None = None
    if viewer_user_id:
        row = db.execute(
            select(VoiceStance.stance)
            .where(VoiceStance.issue_id == issue_id, VoiceStance.user_id == viewer_user_id)
        ).scalar_one_or_none()
        viewer_stance = row

    return _issue_to_out(issue, viewer_stance, _active_live_session_for_issue(db, issue.id))


MAX_ISSUE_LIFETIME_DAYS = 10


@router.post("/issues", response_model=VoiceIssueOut, status_code=201)
def create_issue(
    body: VoiceIssueCreateIn,
    db: Session = Depends(get_db),
) -> VoiceIssueOut:
    now = datetime.now(timezone.utc)
    hard_cap = now + timedelta(days=MAX_ISSUE_LIFETIME_DAYS)
    # Always expire: use caller's value if sooner than cap, otherwise cap
    if body.expires_at and body.expires_at < hard_cap:
        expires_at = body.expires_at
    else:
        expires_at = hard_cap

    issue = VoiceIssue(
        slug=_make_slug(body.title),
        title=body.title,
        context=body.context,
        tags=",".join(body.tags) if body.tags else None,
        created_by_type="user",
        created_by_user_id=body.user_id,
        is_featured=False,
        cover_image_url=body.cover_image_url,
        expires_at=expires_at,
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)

    return _issue_to_out(issue)


@router.patch("/issues/{issue_id}", response_model=VoiceIssueOut)
def update_issue(
    issue_id: int,
    body: VoiceIssueUpdateIn,
    db: Session = Depends(get_db),
) -> VoiceIssueOut:
    issue = db.get(VoiceIssue, issue_id)
    if not issue or issue.status == "archived":
        raise HTTPException(status_code=404, detail="Issue not found")
    if issue.created_by_user_id != body.user_id:
        raise HTTPException(status_code=403, detail="You can only edit your own issues")

    if body.title is not None:
        issue.title = body.title
    if body.context is not None:
        issue.context = body.context
    if body.tags is not None:
        issue.tags = ",".join(body.tags) if body.tags else None
    if body.is_featured is not None:
        issue.is_featured = body.is_featured
    if body.cover_image_url is not None:
        issue.cover_image_url = body.cover_image_url
    if body.expires_at is not None:
        hard_cap = issue.created_at + timedelta(days=MAX_ISSUE_LIFETIME_DAYS)
        issue.expires_at = min(body.expires_at, hard_cap)
    if body.status is not None:
        issue.status = body.status

    db.commit()
    db.refresh(issue)
    return _issue_to_out(issue)


@router.delete("/issues/{issue_id}", status_code=204)
def delete_issue(
    issue_id: int,
    user_id: int = Query(..., gt=0),
    db: Session = Depends(get_db),
) -> None:
    """Soft-delete: only the creator can delete their own issue."""
    issue = db.get(VoiceIssue, issue_id)
    if not issue or issue.status == "archived":
        raise HTTPException(status_code=404, detail="Issue not found")
    if issue.created_by_user_id != user_id:
        raise HTTPException(status_code=403, detail="You can only delete your own issues")

    issue.status = "archived"
    db.commit()


@router.post("/issues/expire", status_code=200)
def expire_issues(db: Session = Depends(get_db)) -> dict:
    """
    Sweep: archive all open issues whose expires_at has passed.
    Cascades automatically delete all stances, takes (comments) and replies
    via DB-level ON DELETE CASCADE.
    Call this from a cron job or Fly scheduled machine.
    """
    now = datetime.now(timezone.utc)
    result = db.execute(
        text(
            """
            UPDATE voice_issues
               SET status = 'archived'
             WHERE status = 'open'
               AND expires_at IS NOT NULL
               AND expires_at <= :now
            RETURNING id
            """
        ),
        {"now": now},
    )
    expired_ids = [row[0] for row in result.fetchall()]
    db.commit()
    return {"archived": len(expired_ids), "ids": expired_ids}


# ---------------------------------------------------------------------------
# Live sessions
# ---------------------------------------------------------------------------

@router.get("/issues/{issue_id}/live-session", response_model=VoiceLiveSessionOut)
def get_issue_live_session(
    issue_id: int,
    db: Session = Depends(get_db),
) -> VoiceLiveSessionOut:
    issue = db.get(VoiceIssue, issue_id)
    if not issue or issue.status == "archived":
        raise HTTPException(status_code=404, detail="Issue not found")

    session = _active_live_session_for_issue(db, issue_id)
    if not session:
        raise HTTPException(status_code=404, detail="No active live session")

    return _live_session_to_out(db, session)


@router.post("/issues/{issue_id}/live-session", response_model=VoiceLiveSessionOut, status_code=201)
def create_issue_live_session(
    issue_id: int,
    body: VoiceLiveSessionCreateIn,
    db: Session = Depends(get_db),
) -> VoiceLiveSessionOut:
    issue = db.get(VoiceIssue, issue_id)
    if not issue or issue.status == "archived":
        raise HTTPException(status_code=404, detail="Issue not found")

    host = _ensure_live_user(db, body.user_id)
    existing = _active_live_session_for_issue(db, issue_id)
    if existing:
        return _live_session_to_out(db, existing)

    room_slug = f"gist-live-{issue_id}-{uuid.uuid4().hex[:12]}"
    session = VoiceLiveSession(
        issue_id=issue_id,
        host_user_id=host.id,
        room_slug=room_slug,
        provider="livekit",
        join_url=_build_live_join_url(room_slug),
        status="active",
        max_participants=8,
    )
    db.add(session)
    db.flush()
    db.add(
        VoiceLiveParticipant(
            session_id=session.id,
            user_id=host.id,
            role="host",
            status="joined",
            joined_at=datetime.now(timezone.utc),
        )
    )
    _add_live_invites(db, session, inviter_user_id=host.id, invitee_user_ids=body.invitee_user_ids)
    db.commit()
    db.refresh(session)
    return _live_session_to_out(db, session)


@router.post("/live-sessions/{session_id}/connection", response_model=VoiceLiveConnectionOut)
def create_live_session_connection(
    session_id: int,
    body: VoiceLiveConnectionIn,
    db: Session = Depends(get_db),
) -> VoiceLiveConnectionOut:
    session = db.get(VoiceLiveSession, session_id)
    if not session or session.status != "active":
        raise HTTPException(status_code=404, detail="Active live session not found")

    return _livekit_connection_out(
        db=db,
        session=session,
        user_id=body.user_id,
        requested_role=body.role,
    )


@router.post("/live-sessions/{session_id}/invite", response_model=VoiceLiveSessionOut)
def invite_to_live_session(
    session_id: int,
    body: VoiceLiveInviteIn,
    db: Session = Depends(get_db),
) -> VoiceLiveSessionOut:
    session = db.get(VoiceLiveSession, session_id)
    if not session or session.status != "active":
        raise HTTPException(status_code=404, detail="Active live session not found")
    if session.host_user_id != body.user_id:
        raise HTTPException(status_code=403, detail="Only the host can invite friends")

    _add_live_invites(db, session, inviter_user_id=body.user_id, invitee_user_ids=body.invitee_user_ids)
    db.commit()
    db.refresh(session)
    return _live_session_to_out(db, session)


@router.post("/live-sessions/{session_id}/join", response_model=VoiceLiveSessionOut)
def join_live_session(
    session_id: int,
    body: VoiceLiveJoinIn,
    db: Session = Depends(get_db),
) -> VoiceLiveSessionOut:
    session = db.get(VoiceLiveSession, session_id)
    if not session or session.status != "active":
        raise HTTPException(status_code=404, detail="Active live session not found")

    _ensure_live_user(db, body.user_id)
    participant = db.execute(
        select(VoiceLiveParticipant)
        .where(VoiceLiveParticipant.session_id == session_id, VoiceLiveParticipant.user_id == body.user_id)
    ).scalar_one_or_none()

    if not participant:
        active_or_invited_count = int(
            db.scalar(
                select(func.count())
                .select_from(VoiceLiveParticipant)
                .where(VoiceLiveParticipant.session_id == session_id)
            )
            or 0
        )
        if active_or_invited_count >= session.max_participants:
            raise HTTPException(status_code=422, detail="This live room is full")
        participant = VoiceLiveParticipant(
            session_id=session_id,
            user_id=body.user_id,
            role="member",
            status="joined",
            joined_at=datetime.now(timezone.utc),
        )
        db.add(participant)
    else:
        participant.status = "joined"
        participant.joined_at = datetime.now(timezone.utc)
        participant.left_at = None

    db.commit()
    db.refresh(session)
    return _live_session_to_out(db, session)


@router.post("/live-sessions/{session_id}/leave", response_model=VoiceLiveSessionOut)
def leave_live_session(
    session_id: int,
    body: VoiceLiveJoinIn,
    db: Session = Depends(get_db),
) -> VoiceLiveSessionOut:
    session = db.get(VoiceLiveSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Live session not found")

    participant = db.execute(
        select(VoiceLiveParticipant)
        .where(VoiceLiveParticipant.session_id == session_id, VoiceLiveParticipant.user_id == body.user_id)
    ).scalar_one_or_none()
    if participant:
        participant.status = "left"
        participant.left_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(session)
    return _live_session_to_out(db, session)


@router.post("/live-sessions/{session_id}/end")
def end_live_session(
    session_id: int,
    body: VoiceLiveEndIn,
    db: Session = Depends(get_db),
) -> dict:
    session = db.get(VoiceLiveSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Live session not found")
    if session.host_user_id != body.user_id:
        raise HTTPException(status_code=403, detail="Only the host can end this live session")

    session.status = "ended"
    session.ended_at = datetime.now(timezone.utc)
    db.execute(
        text(
            """
            UPDATE voice_live_participants
               SET status = 'left',
                   left_at = COALESCE(left_at, :now),
                   updated_at = :now
             WHERE session_id = :session_id
               AND status <> 'left'
            """
        ),
        {"session_id": session_id, "now": session.ended_at},
    )
    db.commit()
    return {"ok": True, "session_id": session.id, "issue_id": session.issue_id, "status": session.status}


# ---------------------------------------------------------------------------
# Stances
# ---------------------------------------------------------------------------

@router.post("/issues/{issue_id}/stance", response_model=VoiceStanceOut)
def set_stance(
    issue_id: int,
    body: VoiceStanceIn,
    db: Session = Depends(get_db),
) -> VoiceStanceOut:
    issue = db.get(VoiceIssue, issue_id)
    if not issue or issue.status == "archived":
        raise HTTPException(status_code=404, detail="Issue not found")

    existing = db.execute(
        select(VoiceStance)
        .where(VoiceStance.issue_id == issue_id, VoiceStance.user_id == body.user_id)
    ).scalar_one_or_none()

    if existing:
        old_stance = existing.stance
        if old_stance != body.stance:
            # Decrement old, increment new
            setattr(issue, f"{old_stance}_count", getattr(issue, f"{old_stance}_count") - 1)
            setattr(issue, f"{body.stance}_count", getattr(issue, f"{body.stance}_count") + 1)
            existing.stance = body.stance
    else:
        db.add(VoiceStance(issue_id=issue_id, user_id=body.user_id, stance=body.stance))
        setattr(issue, f"{body.stance}_count", getattr(issue, f"{body.stance}_count") + 1)

    try:
        if issue.created_by_user_id is not None and int(issue.created_by_user_id) != int(body.user_id):
            create_notification(
                db,
                recipient_user_id=int(issue.created_by_user_id),
                actor_user_id=int(body.user_id),
                notification_type="voice_vote",
                entity_type="voice_issue",
                entity_id=int(issue_id),
                payload={
                    "kind": "voice_vote",
                    "issue_id": int(issue_id),
                    "stance": body.stance,
                },
            )
    except Exception:
        pass

    # Voice trending milestone — only triggered on brand new votes, not stance changes
    if not existing:
        try:
            total_votes = issue.support_count + issue.oppose_count + issue.question_count
            if total_votes in {10, 50, 100, 500} and issue.created_by_user_id is not None:
                create_notification(
                    db,
                    recipient_user_id=int(issue.created_by_user_id),
                    actor_user_id=None,
                    notification_type="voice_milestone",
                    entity_type="voice_issue",
                    entity_id=int(issue_id),
                    payload={
                        "kind": "voice_milestone",
                        "issue_id": int(issue_id),
                        "total_votes": total_votes,
                    },
                )
        except Exception:
            pass

    db.commit()
    db.refresh(issue)

    return VoiceStanceOut(
        ok=True,
        issue_id=issue_id,
        stance=body.stance,
        support_count=issue.support_count,
        oppose_count=issue.oppose_count,
        question_count=issue.question_count,
    )


# ---------------------------------------------------------------------------
# Takes (comments on an issue)
# ---------------------------------------------------------------------------

@router.get("/issues/{issue_id}/takes", response_model=list[VoiceTakeOut])
def list_takes(
    issue_id: int,
    filter: str = Query(default="all"),
    limit: int = Query(default=15, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[VoiceTakeOut]:
    issue = db.get(VoiceIssue, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    stmt = (
        select(VoiceTake)
        .where(VoiceTake.issue_id == issue_id, VoiceTake.parent_take_id.is_(None), VoiceTake.status == "published")
        .order_by(VoiceTake.created_at.desc(), VoiceTake.reactions_count.desc())
        .limit(limit)
        .offset(offset)
    )
    if filter != "all":
        stmt = stmt.where(VoiceTake.stance == filter)

    takes = db.execute(stmt).scalars().all()

    def _author_info(user_id: int | None) -> tuple[str, str | None]:
        if not user_id:
            return "Anonymous", None
        user = db.get(User, user_id)
        if not user:
            return "Anonymous", None
        return user.display_name, user.avatar_url

    def _collect_descendant_rows(root_take_id: int) -> list[VoiceTake]:
        collected: list[VoiceTake] = []
        seen_ids: set[int] = set()
        frontier: list[int] = [root_take_id]

        while frontier:
            reply_rows = db.execute(
                select(VoiceTake)
                .where(
                    VoiceTake.issue_id == issue_id,
                    VoiceTake.status == "published",
                    VoiceTake.parent_take_id.in_(frontier),
                )
                .order_by(VoiceTake.created_at.asc())
            ).scalars().all()

            next_frontier: list[int] = []
            for row in reply_rows:
                row_id = int(row.id)
                if row_id in seen_ids:
                    continue
                seen_ids.add(row_id)
                collected.append(row)
                next_frontier.append(row_id)

            frontier = next_frontier

        collected.sort(key=lambda row: row.created_at)
        return collected

    result: list[VoiceTakeOut] = []
    for take in takes:
        reply_rows = _collect_descendant_rows(int(take.id))
        replies = []
        for row in reply_rows:
            reply_author, reply_avatar = _author_info(row.user_id)
            replies.append(
                VoiceTakeReplyOut(
                    id=row.id,
                    parent_take_id=row.parent_take_id,
                    author=reply_author,
                    author_id=row.user_id,
                    author_avatar_url=reply_avatar,
                    stance=row.stance,
                    content=row.body,
                    audio_url=row.audio_url,
                    audio_duration_sec=row.audio_duration_sec,
                    created_at=row.created_at,
                    replies=[],
                )
            )

        take_author, take_avatar = _author_info(take.user_id)
        result.append(
            VoiceTakeOut(
                id=take.id,
                author=take_author,
                author_id=take.user_id,
                author_avatar_url=take_avatar,
                stance=take.stance,
                content=take.body,
                audio_url=take.audio_url,
                audio_duration_sec=take.audio_duration_sec,
                reactions_count=take.reactions_count,
                replies_count=take.replies_count,
                created_at=take.created_at,
                replies=replies,
            )
        )
    return result


@router.get("/top-takes", response_model=list[TopTakeOut])
def get_top_takes(
    limit: int = Query(default=10, ge=1, le=30),
    db: Session = Depends(get_db),
) -> list[TopTakeOut]:
    rows = db.execute(
        select(
            VoiceTake,
            VoiceIssue.title.label("issue_title"),
            User.display_name.label("author_name"),
            User.avatar_url.label("author_avatar_url"),
            (VoiceTake.reactions_count + VoiceTake.replies_count).label("engagement_score"),
        )
        .join(VoiceIssue, VoiceIssue.id == VoiceTake.issue_id)
        .outerjoin(User, User.id == VoiceTake.user_id)
        .where(
            VoiceTake.status == "published",
            VoiceTake.parent_take_id.is_(None),
            VoiceIssue.status != "archived",
        )
        .order_by(
            (VoiceTake.reactions_count + VoiceTake.replies_count).desc(),
            VoiceTake.created_at.desc(),
        )
        .limit(limit)
    ).all()

    result: list[TopTakeOut] = []
    for take, issue_title, author_name, author_avatar_url, engagement_score in rows:
        result.append(
            TopTakeOut(
                take_id=int(take.id),
                issue_id=int(take.issue_id),
                issue_title=issue_title or "Voice",
                author_id=int(take.user_id) if take.user_id is not None else None,
                author_name=author_name or "Anonymous",
                author_avatar_url=author_avatar_url,
                stance=take.stance,
                content=take.body,
                reactions_count=int(take.reactions_count),
                replies_count=int(take.replies_count),
                engagement_score=int(engagement_score or 0),
                created_at=take.created_at,
            )
        )

    return result


@router.post("/issues/{issue_id}/takes", response_model=VoiceTakeOut, status_code=201)
def create_take(
    issue_id: int,
    body: VoiceTakeCreateIn,
    db: Session = Depends(get_db),
) -> VoiceTakeOut:
    issue = db.get(VoiceIssue, issue_id)
    if not issue or issue.status == "archived":
        raise HTTPException(status_code=404, detail="Issue not found")

    if body.reply_to_take_id and not body.parent_take_id:
        raise HTTPException(status_code=400, detail="reply_to_take_id requires parent_take_id")

    root_parent_id: int | None = None
    reply_target_take: VoiceTake | None = None
    if body.parent_take_id:
        parent = db.get(VoiceTake, body.parent_take_id)
        if not parent or parent.issue_id != issue_id:
            raise HTTPException(status_code=400, detail="Invalid parent_take_id")

        # Force single-thread model: every reply is attached to the root comment.
        root_parent_id = int(parent.id if parent.parent_take_id is None else parent.parent_take_id)

        if body.reply_to_take_id:
            reply_target_take = db.get(VoiceTake, body.reply_to_take_id)
            if not reply_target_take or reply_target_take.issue_id != issue_id:
                raise HTTPException(status_code=400, detail="Invalid reply_to_take_id")
        else:
            reply_target_take = parent

    user = db.get(User, body.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    validated_audio_url = _validate_take_audio_url(body.audio_url)
    cleaned_body = (body.body or "").strip()
    if not cleaned_body and not validated_audio_url:
        raise HTTPException(status_code=422, detail="Either body or audio_url is required")

    take = VoiceTake(
        issue_id=issue_id,
        user_id=body.user_id,
        body=cleaned_body,
        stance=body.stance,
        audio_url=validated_audio_url,
        audio_duration_sec=body.audio_duration_sec,
        parent_take_id=root_parent_id,
    )
    db.add(take)

    # Update counters
    issue.takes_count = issue.takes_count + 1
    if root_parent_id:
        root_parent = db.get(VoiceTake, root_parent_id)
        if root_parent:
            root_parent.replies_count = root_parent.replies_count + 1

    db.flush()

    # Best-effort notification for direct reply target.
    if reply_target_take and reply_target_take.user_id and reply_target_take.user_id != body.user_id:
        try:
            payload = json.dumps(
                {
                    "issue_id": issue_id,
                    "root_take_id": root_parent_id,
                    "reply_to_take_id": int(reply_target_take.id),
                    "new_take_id": int(take.id),
                }
            )
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
                        'voice_reply',
                        'voice_take',
                        :entity_id,
                        CAST(:payload AS jsonb),
                        FALSE
                    )
                    """
                ),
                {
                    "recipient_user_id": int(reply_target_take.user_id),
                    "actor_user_id": int(body.user_id),
                    "entity_id": int(take.id),
                    "payload": payload,
                },
            )
        except Exception:
            # Do not fail comment creation if notifications schema is unavailable.
            pass

    db.commit()
    db.refresh(take)

    return VoiceTakeOut(
        id=take.id,
        author=user.display_name,
        author_id=user.id,
        author_avatar_url=user.avatar_url,
        stance=take.stance,
        content=take.body,
        audio_url=take.audio_url,
        audio_duration_sec=take.audio_duration_sec,
        reactions_count=0,
        replies_count=0,
        created_at=take.created_at,
        replies=[],
    )


@router.delete("/issues/{issue_id}/takes/{take_id}", response_model=VoiceTakeDeleteOut)
def delete_take(
    issue_id: int,
    take_id: int,
    user_id: int = Query(gt=0),
    db: Session = Depends(get_db),
) -> VoiceTakeDeleteOut:
    issue = db.get(VoiceIssue, issue_id)
    if not issue or issue.status == "archived":
        raise HTTPException(status_code=404, detail="Issue not found")

    target_take = db.get(VoiceTake, take_id)
    if not target_take or target_take.issue_id != issue_id:
        raise HTTPException(status_code=404, detail="Take not found")

    if target_take.user_id != user_id:
        raise HTTPException(status_code=403, detail="You can only delete your own comment")

    to_delete_ids: list[int] = [take_id]
    frontier: list[int] = [take_id]

    # Soft-delete the full descendant chain so nested responses do not become orphaned.
    while frontier:
        children = db.execute(
            select(VoiceTake.id)
            .where(
                VoiceTake.issue_id == issue_id,
                VoiceTake.status == "published",
                VoiceTake.parent_take_id.in_(frontier),
            )
        ).scalars().all()

        next_frontier: list[int] = []
        for child_id in children:
            child_id_int = int(child_id)
            if child_id_int not in to_delete_ids:
                to_delete_ids.append(child_id_int)
                next_frontier.append(child_id_int)
        frontier = next_frontier

    rows_to_mark = db.execute(
        select(VoiceTake).where(VoiceTake.id.in_(to_delete_ids))
    ).scalars().all()

    deleted_count = 0
    for row in rows_to_mark:
        if row.status == "published":
            row.status = "deleted"
            deleted_count += 1

    # Keep counters accurate after delete.
    issue.takes_count = int(
        db.execute(
            select(func.count(VoiceTake.id)).where(
                VoiceTake.issue_id == issue_id,
                VoiceTake.status == "published",
            )
        ).scalar_one()
    )

    per_parent_counts = {
        int(parent_id): int(count)
        for parent_id, count in db.execute(
            select(VoiceTake.parent_take_id, func.count(VoiceTake.id))
            .where(
                VoiceTake.issue_id == issue_id,
                VoiceTake.status == "published",
                VoiceTake.parent_take_id.is_not(None),
            )
            .group_by(VoiceTake.parent_take_id)
        ).all()
    }

    issue_takes = db.execute(
        select(VoiceTake).where(VoiceTake.issue_id == issue_id)
    ).scalars().all()

    for row in issue_takes:
        row.replies_count = per_parent_counts.get(int(row.id), 0)

    db.commit()

    return VoiceTakeDeleteOut(
        ok=True,
        issue_id=issue_id,
        take_id=take_id,
        deleted_count=deleted_count,
    )


# ---------------------------------------------------------------------------
# Polls
# ---------------------------------------------------------------------------

@router.get("/polls/active", response_model=list[VoicePollOut])
def get_active_polls(
    viewer_user_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[VoicePollOut]:
    _delete_expired_polls(db)

    polls = db.execute(
        select(VoicePoll)
        .where(VoicePoll.is_active.is_(True))
        .where((VoicePoll.closes_at.is_(None)) | (VoicePoll.closes_at > datetime.now(timezone.utc)))
        .order_by(VoicePoll.created_at.desc())
        .limit(20)
    ).scalars().all()

    result: list[VoicePollOut] = []
    for poll in polls:
        options = db.execute(
            select(VoicePollOption)
            .where(VoicePollOption.poll_id == poll.id)
            .order_by(VoicePollOption.sort_order.asc())
        ).scalars().all()

        viewer_voted: int | None = None
        if viewer_user_id:
            row = db.execute(
                select(VoicePollVote.option_id)
                .where(VoicePollVote.poll_id == poll.id, VoicePollVote.user_id == viewer_user_id)
            ).scalar_one_or_none()
            viewer_voted = row

        result.append(VoicePollOut(
            id=poll.id,
            label=poll.label,
            question=poll.question,
            options=_poll_options_with_pct(list(options), poll.total_votes),
            total_votes=poll.total_votes,
            closes_at=poll.closes_at,
            time_info=_format_time_info(poll.closes_at),
            viewer_voted_option_id=viewer_voted,
            cover_image_url=poll.cover_image_url,
        ))

    return result


@router.post("/polls/{poll_id}/vote", response_model=VoicePollVoteOut)
def vote_poll(
    poll_id: int,
    body: VoicePollVoteIn,
    db: Session = Depends(get_db),
) -> VoicePollVoteOut:
    _delete_expired_polls(db)

    poll = db.get(VoicePoll, poll_id)
    if not poll or not poll.is_active:
        raise HTTPException(status_code=404, detail="Poll not found or not active")

    if poll.closes_at is not None and poll.closes_at <= datetime.now(timezone.utc):
        db.delete(poll)
        db.commit()
        raise HTTPException(status_code=404, detail="Poll not found or not active")

    option = db.get(VoicePollOption, body.option_id)
    if not option or option.poll_id != poll_id:
        raise HTTPException(status_code=400, detail="Invalid option")

    # Prevent double-voting
    existing = db.execute(
        select(VoicePollVote)
        .where(VoicePollVote.poll_id == poll_id, VoicePollVote.user_id == body.user_id)
    ).scalar_one_or_none()

    if existing:
        raise HTTPException(status_code=409, detail="Already voted")

    db.add(VoicePollVote(poll_id=poll_id, option_id=body.option_id, user_id=body.user_id))
    option.votes_count = option.votes_count + 1
    poll.total_votes = poll.total_votes + 1

    db.commit()
    db.refresh(poll)

    options = db.execute(
        select(VoicePollOption)
        .where(VoicePollOption.poll_id == poll_id)
        .order_by(VoicePollOption.sort_order.asc())
    ).scalars().all()

    return VoicePollVoteOut(
        ok=True,
        poll_id=poll_id,
        option_id=body.option_id,
        total_votes=poll.total_votes,
        options=_poll_options_with_pct(list(options), poll.total_votes),
    )


# ---------------------------------------------------------------------------# Create poll (user-facing)
# -------------------------------------------------------------------------


@router.post("/polls", response_model=VoicePollOut, status_code=201)
def create_poll(
    body: VoicePollCreateIn,
    db: Session = Depends(get_db),
) -> VoicePollOut:
    # Enforce 3-poll maximum
    _delete_expired_polls(db)
    active_count = db.execute(
        select(func.count()).select_from(VoicePoll)
        .where(VoicePoll.is_active.is_(True))
        .where((VoicePoll.closes_at.is_(None)) | (VoicePoll.closes_at > datetime.now(timezone.utc)))
    ).scalar_one()
    if active_count >= 3:
        raise HTTPException(
            status_code=409,
            detail="Poll limit reached. You already have 3 active polls. Wait for one to expire before creating a new one.",
        )

    closes_at = datetime.now(timezone.utc) + timedelta(hours=body.closes_in_hours)

    poll = VoicePoll(
        label="Community Poll",
        question=body.question,
        is_active=True,
        total_votes=0,
        closes_at=closes_at,
        issue_id=body.issue_id,
        cover_image_url=body.cover_image_url,
    )
    db.add(poll)
    db.flush()  # get poll.id

    for idx, opt_label in enumerate(body.options):
        db.add(VoicePollOption(
            poll_id=poll.id,
            label=opt_label,
            votes_count=0,
            sort_order=idx,
        ))

    db.commit()
    db.refresh(poll)

    options = db.execute(
        select(VoicePollOption)
        .where(VoicePollOption.poll_id == poll.id)
        .order_by(VoicePollOption.sort_order.asc())
    ).scalars().all()

    return VoicePollOut(
        id=poll.id,
        label=poll.label,
        question=poll.question,
        options=_poll_options_with_pct(list(options), 0),
        total_votes=0,
        closes_at=poll.closes_at,
        time_info=_format_time_info(poll.closes_at),
        viewer_voted_option_id=None,
        cover_image_url=poll.cover_image_url,
    )


# ---------------------------------------------------------------------------
# Predictions
# ---------------------------------------------------------------------------

@router.get("/predictions/active", response_model=list[PredictionOut])
def get_active_predictions(
    viewer_user_id: int | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
) -> list[PredictionOut]:
    predictions = db.execute(
        select(Prediction)
        .where(Prediction.is_active.is_(True))
        .order_by(Prediction.created_at.desc())
        .limit(limit)
    ).scalars().all()

    if not predictions:
        return []

    creator_ids = {p.creator_user_id for p in predictions}
    creators = db.execute(select(User).where(User.id.in_(creator_ids))).scalars().all()
    creator_map = {u.id: u for u in creators}

    viewer_estimates: dict[int, int] = {}
    if viewer_user_id:
        rows = db.execute(
            select(PredictionEstimate.prediction_id, PredictionEstimate.estimate_percent)
            .where(
                PredictionEstimate.user_id == viewer_user_id,
                PredictionEstimate.prediction_id.in_([p.id for p in predictions]),
            )
        ).all()
        viewer_estimates = {prediction_id: estimate for prediction_id, estimate in rows}

    return [
        _prediction_to_out(
            prediction,
            creator_map.get(prediction.creator_user_id),
            viewer_estimates.get(prediction.id),
        )
        for prediction in predictions
    ]


@router.post("/predictions", response_model=PredictionOut, status_code=201)
def create_prediction(
    body: PredictionCreateIn,
    db: Session = Depends(get_db),
) -> PredictionOut:
    user = db.get(User, body.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    prediction = Prediction(
        creator_user_id=body.user_id,
        statement=body.statement.strip(),
        context=body.context.strip(),
        topic=body.topic.strip() if body.topic and body.topic.strip() else None,
        estimates_count=0,
        estimates_sum=0,
        is_active=True,
    )
    db.add(prediction)
    db.commit()
    db.refresh(prediction)

    return _prediction_to_out(prediction, user)


@router.post("/predictions/{prediction_id}/estimate", response_model=PredictionEstimateOut)
def set_prediction_estimate(
    prediction_id: int,
    body: PredictionEstimateIn,
    db: Session = Depends(get_db),
) -> PredictionEstimateOut:
    prediction = db.get(Prediction, prediction_id)
    if not prediction or not prediction.is_active:
        raise HTTPException(status_code=404, detail="Prediction not found")

    existing = db.execute(
        select(PredictionEstimate)
        .where(
            PredictionEstimate.prediction_id == prediction_id,
            PredictionEstimate.user_id == body.user_id,
        )
    ).scalar_one_or_none()

    if existing:
        prediction.estimates_sum = prediction.estimates_sum - existing.estimate_percent + body.estimate_percent
        existing.estimate_percent = body.estimate_percent
    else:
        db.add(PredictionEstimate(
            prediction_id=prediction_id,
            user_id=body.user_id,
            estimate_percent=body.estimate_percent,
        ))
        prediction.estimates_count += 1
        prediction.estimates_sum += body.estimate_percent

    db.commit()
    db.refresh(prediction)

    return PredictionEstimateOut(
        ok=True,
        prediction_id=prediction_id,
        estimate_percent=body.estimate_percent,
        estimates_count=prediction.estimates_count,
        crowd_average=_prediction_average(prediction),
    )


# -------------------------------------------------------------------------# Top Voices
# ---------------------------------------------------------------------------

@router.get("/top-voices", response_model=list[TopVoiceOut])
def get_top_voices(
    limit: int = Query(default=4, ge=1, le=20),
    db: Session = Depends(get_db),
) -> list[TopVoiceOut]:
    # Top voices = users with the most total reactions on their takes
    rows = db.execute(
        select(
            VoiceTake.user_id,
            func.count(VoiceTake.id).label("takes_count"),
            func.sum(VoiceTake.reactions_count).label("total_reactions"),
        )
        .where(VoiceTake.status == "published", VoiceTake.user_id.is_not(None))
        .group_by(VoiceTake.user_id)
        .order_by(func.sum(VoiceTake.reactions_count).desc())
        .limit(limit)
    ).all()

    labels = ["Top Voice", "Sharpest Take", "Balanced View", "Rising Voice"]
    result: list[TopVoiceOut] = []
    for i, row in enumerate(rows):
        user = db.get(User, row.user_id)
        if user:
            result.append(
                TopVoiceOut(
                    id=user.id,
                    name=user.display_name,
                    label=labels[i] if i < len(labels) else "Voice",
                    takes_count=row.takes_count,
                )
            )
    return result


# ---------------------------------------------------------------------------
# Participation stream
# ---------------------------------------------------------------------------

@router.get("/participation-stream", response_model=list[ParticipationStreamItem])
def get_participation_stream(
    limit: int = Query(default=3, ge=1, le=10),
    db: Session = Depends(get_db),
) -> list[ParticipationStreamItem]:
    # Recent activity: takes grouped by issue in the last hour
    rows = db.execute(
        select(
            VoiceIssue.title,
            func.count(VoiceTake.id).label("take_count"),
        )
        .join(VoiceTake, VoiceTake.issue_id == VoiceIssue.id)
        .where(VoiceTake.status == "published")
        .group_by(VoiceIssue.id, VoiceIssue.title)
        .order_by(func.count(VoiceTake.id).desc())
        .limit(limit)
    ).all()

    items = [
        ParticipationStreamItem(
            text=f"{row.take_count} people commented in \"{row.title}\"."
        )
        for row in rows
    ]

    # Fallback if no activity yet
    if not items:
        items = [ParticipationStreamItem(text="Be the first to join the discussion.")]

    return items


@router.get("/users/{user_id}/activity", response_model=list[VoiceUserActivityItemOut])
def get_user_voice_activity(
    user_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[VoiceUserActivityItemOut]:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    items: list[VoiceUserActivityItemOut] = []

    issues = db.execute(
        select(VoiceIssue)
        .where(VoiceIssue.created_by_user_id == user_id)
        .order_by(VoiceIssue.created_at.desc())
        .limit(limit)
    ).scalars().all()
    for issue in issues:
        items.append(
            VoiceUserActivityItemOut(
                id=f"issue-{issue.id}",
                kind="issue_created",
                created_at=issue.created_at,
                issue_id=issue.id,
                issue_title=issue.title,
                content=issue.context,
            )
        )

    takes = db.execute(
        select(VoiceTake, VoiceIssue.title)
        .join(VoiceIssue, VoiceIssue.id == VoiceTake.issue_id)
        .where(VoiceTake.user_id == user_id, VoiceTake.status == "published")
        .order_by(VoiceTake.created_at.desc())
        .limit(limit)
    ).all()
    for take, issue_title in takes:
        items.append(
            VoiceUserActivityItemOut(
                id=f"take-{take.id}",
                kind="take_created",
                created_at=take.created_at,
                issue_id=take.issue_id,
                issue_title=issue_title,
                stance=take.stance,
                content=take.body,
            )
        )

    stances = db.execute(
        select(VoiceStance, VoiceIssue.title)
        .join(VoiceIssue, VoiceIssue.id == VoiceStance.issue_id)
        .where(VoiceStance.user_id == user_id)
        .order_by(VoiceStance.updated_at.desc())
        .limit(limit)
    ).all()
    for stance, issue_title in stances:
        items.append(
            VoiceUserActivityItemOut(
                id=f"stance-{stance.id}",
                kind="stance_set",
                created_at=stance.updated_at,
                issue_id=stance.issue_id,
                issue_title=issue_title,
                stance=stance.stance,
            )
        )

    poll_votes = db.execute(
        select(VoicePollVote, VoicePoll.question)
        .join(VoicePoll, VoicePoll.id == VoicePollVote.poll_id)
        .where(VoicePollVote.user_id == user_id)
        .order_by(VoicePollVote.created_at.desc())
        .limit(limit)
    ).all()
    for vote, poll_question in poll_votes:
        items.append(
            VoiceUserActivityItemOut(
                id=f"poll-vote-{vote.id}",
                kind="poll_voted",
                created_at=vote.created_at,
                poll_id=vote.poll_id,
                poll_question=poll_question,
            )
        )

    items.sort(key=lambda item: item.created_at, reverse=True)
    return items[:limit]
