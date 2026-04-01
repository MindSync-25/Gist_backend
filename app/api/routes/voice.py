import json
import re
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.notifications import create_notification
from app.models.user import User
from app.models.voice_issue import VoiceIssue
from app.models.voice_poll import VoicePoll, VoicePollOption, VoicePollVote
from app.models.voice_stance import VoiceStance
from app.models.voice_take import VoiceTake
from app.schemas.voice import (
    ParticipationStreamItem,
    TopVoiceOut,
    VoiceTakeDeleteOut,
    VoiceIssueCreateIn,
    VoiceIssueOut,
    VoicePollCreateIn,
    VoicePollOut,
    VoicePollOptionOut,
    VoicePollVoteIn,
    VoicePollVoteOut,
    VoiceStanceIn,
    VoiceStanceOut,
    VoiceTakeCreateIn,
    VoiceTakeOut,
    VoiceTakeReplyOut,
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


def _issue_to_out(issue: VoiceIssue, viewer_stance: str | None = None) -> VoiceIssueOut:
    return VoiceIssueOut(
        id=issue.id,
        title=issue.title,
        context=issue.context,
        tags=_parse_tags(issue.tags),
        created_by_type=issue.created_by_type,
        is_featured=issue.is_featured,
        support_count=issue.support_count,
        oppose_count=issue.oppose_count,
        question_count=issue.question_count,
        takes_count=issue.takes_count,
        reacting_now=issue.support_count + issue.oppose_count + issue.question_count,
        created_at=issue.created_at,
        viewer_stance=viewer_stance,
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
    issue = db.execute(
        select(VoiceIssue)
        .where(VoiceIssue.is_featured.is_(True), VoiceIssue.status == "open")
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

    return _issue_to_out(issue, viewer_stance)


@router.get("/issues", response_model=list[VoiceIssueOut])
def list_issues(
    filter: str = Query(default="Trending"),
    q: str = Query(default=""),
    viewer_user_id: int | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[VoiceIssueOut]:
    stmt = (
        select(VoiceIssue)
        .where(VoiceIssue.status == "open", VoiceIssue.is_featured.is_(False))
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

    return [_issue_to_out(issue, stance_map.get(issue.id)) for issue in issues]


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

    return _issue_to_out(issue, viewer_stance)


@router.post("/issues", response_model=VoiceIssueOut, status_code=201)
def create_issue(
    body: VoiceIssueCreateIn,
    db: Session = Depends(get_db),
) -> VoiceIssueOut:
    issue = VoiceIssue(
        slug=_make_slug(body.title),
        title=body.title,
        context=body.context,
        tags=",".join(body.tags) if body.tags else None,
        created_by_type="user",
        created_by_user_id=body.user_id,
        is_featured=False,
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)
    return _issue_to_out(issue)


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
                reactions_count=take.reactions_count,
                replies_count=take.replies_count,
                created_at=take.created_at,
                replies=replies,
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

    take = VoiceTake(
        issue_id=issue_id,
        user_id=body.user_id,
        body=body.body,
        stance=body.stance,
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
        .limit(3)
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
