from __future__ import annotations

import json
import logging
import re
from datetime import date

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.models.post import Post
from app.models.user import User
from app.models.voice_issue import VoiceIssue

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])

_DAILY_CHAT_LIMIT = 3

_SYSTEM_PROMPT = (
    "You are Gist AI — the intelligent assistant built into the Gist app, "
    "an Indian news platform that delivers current events through AI-generated "
    "comics, live Voice debates, and short videos.\n\n"
    "Your role:\n"
    "- Answer general knowledge and current events questions clearly and concisely.\n"
    "- Help users understand news stories, complex topics, and current affairs.\n"
    "- Provide balanced, factual perspectives without taking political sides.\n"
    "- Keep answers focused and readable — this is a mobile news app.\n\n"
    "You are Gist AI. Do not identify yourself as Grok, xAI, or any third-party "
    "AI service. If asked what model or AI you are, say you are Gist AI, "
    "the AI assistant built into the Gist app."
)

_GREET_SYSTEM = (
    "You are Gist AI — warm, sharp, and personal assistant inside the Gist social news app.\n"
    "Write a short, friendly opening message (2-3 sentences max) addressed to the user by first name. "
    "Reference something specific from the live content provided — a real debate or story title. "
    "Sound like a smart friend checking in, not a bot. "
    "Do NOT use phrases like 'How can I help you today?' or 'I am here to assist'. "
    "End with a natural hook that makes them want to reply.\n"
    "Also produce exactly 3 short reply chips (5-8 words each) the user can tap to reply quickly. "
    "Chips should feel conversational and natural.\n"
    "Respond ONLY in this exact JSON format with no extra text:\n"
    "{\"message\": \"...\", \"chips\": [\"...\", \"...\", \"...\"]}"
)

_XAI_BASE = "https://api.x.ai/v1"
_MODEL = "grok-3-mini"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ChatAction(BaseModel):
    label: str
    route: str


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)


class ChatResponse(BaseModel):
    content: str
    actions: list[ChatAction] = []
    remaining_today: int


class GreetResponse(BaseModel):
    message: str
    chips: list[str]
    action: ChatAction | None = None
    remaining_today: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_daily_usage(db: Session, user_id: int) -> int:
    today = date.today()
    row = db.execute(
        text("SELECT chat_count FROM ai_daily_usage WHERE user_id = :uid AND usage_date = :d"),
        {"uid": user_id, "d": today},
    ).one_or_none()
    return row[0] if row else 0


def _increment_daily_usage(db: Session, user_id: int) -> int:
    today = date.today()
    db.execute(
        text(
            """
            INSERT INTO ai_daily_usage (user_id, usage_date, chat_count)
            VALUES (:uid, :d, 1)
            ON CONFLICT (user_id, usage_date)
            DO UPDATE SET chat_count = ai_daily_usage.chat_count + 1
            """
        ),
        {"uid": user_id, "d": today},
    )
    db.commit()
    row = db.execute(
        text("SELECT chat_count FROM ai_daily_usage WHERE user_id = :uid AND usage_date = :d"),
        {"uid": user_id, "d": today},
    ).one_or_none()
    return row[0] if row else 1


async def _call_xai(messages: list[dict], settings, max_tokens: int = 512) -> str:
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{_XAI_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.xai_api_key}",
                "Content-Type": "application/json",
            },
            json={"model": _MODEL, "messages": messages, "stream": False, "max_tokens": max_tokens},
        )
    if resp.status_code != 200:
        logger.error("xAI error %s: %s", resp.status_code, resp.text)
        raise HTTPException(status_code=502, detail="AI service error")
    return resp.json()["choices"][0]["message"]["content"]


def _fetch_live_context(
    db: Session, keyword: str | None = None
) -> tuple[list[dict], list[dict]]:
    """Fetch recent posts and open voice issues, optionally narrowed by keyword."""
    post_stmt = select(Post.id, Post.title, Post.context).where(
        Post.status == "published", Post.visibility == "public"
    )
    if keyword:
        needle = f"%{keyword.lower()[:60]}%"
        post_stmt = post_stmt.where(
            or_(func.lower(Post.title).like(needle), func.lower(Post.context).like(needle))
        )
    post_rows = db.execute(post_stmt.order_by(Post.published_at.desc()).limit(3)).all()
    posts = [{"id": r.id, "title": r.title or "", "context": (r.context or "")[:150]} for r in post_rows]

    voice_stmt = select(VoiceIssue.id, VoiceIssue.title, VoiceIssue.context).where(
        VoiceIssue.status == "open"
    )
    if keyword:
        needle = f"%{keyword.lower()[:60]}%"
        voice_stmt = voice_stmt.where(
            or_(
                func.lower(VoiceIssue.title).like(needle),
                func.lower(VoiceIssue.context).like(needle),
            )
        )
    voice_rows = db.execute(voice_stmt.order_by(VoiceIssue.created_at.desc()).limit(3)).all()
    voices = [{"id": r.id, "title": r.title, "context": (r.context or "")[:150]} for r in voice_rows]

    # Always fall back to latest if keyword returned nothing
    if not posts:
        rows = db.execute(
            select(Post.id, Post.title, Post.context)
            .where(Post.status == "published", Post.visibility == "public")
            .order_by(Post.published_at.desc())
            .limit(3)
        ).all()
        posts = [{"id": r.id, "title": r.title or "", "context": (r.context or "")[:150]} for r in rows]

    if not voices:
        rows = db.execute(
            select(VoiceIssue.id, VoiceIssue.title, VoiceIssue.context)
            .where(VoiceIssue.status == "open")
            .order_by(VoiceIssue.created_at.desc())
            .limit(3)
        ).all()
        voices = [{"id": r.id, "title": r.title, "context": (r.context or "")[:150]} for r in rows]

    return posts, voices


def _parse_greet_json(raw: str, first_name: str) -> tuple[str, list[str]]:
    """Robustly parse the JSON the model returns for greet."""
    try:
        match = re.search(r'\{.*"message".*"chips".*\}', raw, re.DOTALL)
        if not match:
            match = re.search(r'\{.*\}', raw, re.DOTALL)
        parsed = json.loads(match.group()) if match else {}
        message = str(parsed.get("message", "")).strip()
        chips = parsed.get("chips", [])
        if not message:
            raise ValueError("empty message")
        if not isinstance(chips, list) or len(chips) < 3:
            raise ValueError("bad chips")
        return message, [str(c).strip() for c in chips[:3]]
    except Exception:
        return (
            f"Hey {first_name}! What's on your mind today?",
            ["What's happening today?", "Explain a topic", "Start a debate"],
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/greet", response_model=GreetResponse)
async def greet(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GreetResponse:
    settings = get_settings()
    if not settings.xai_api_key:
        raise HTTPException(status_code=503, detail="AI service not configured")

    remaining = _DAILY_CHAT_LIMIT - _get_daily_usage(db, current_user.id)
    first_name = (current_user.display_name or current_user.username).split()[0]
    topic_slugs = current_user.preferred_topic_slugs or []
    language = current_user.language or "en"

    posts, voices = _fetch_live_context(db)

    context_lines = [f"User's name: {first_name}"]
    if topic_slugs:
        context_lines.append(f"User's interests: {', '.join(topic_slugs[:5])}")
    if language != "en":
        context_lines.append(f"Respond in language code: {language}")
    context_lines.append("\nLive on Gist right now:")
    for v in voices[:2]:
        context_lines.append(f"  Debate: \"{v['title']}\"")
    for p in posts[:2]:
        context_lines.append(f"  Story: \"{p['title']}\"")

    try:
        raw = await _call_xai(
            [
                {"role": "system", "content": _GREET_SYSTEM},
                {"role": "user", "content": "\n".join(context_lines)},
            ],
            settings,
            max_tokens=300,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Greet AI error: %s", exc)
        raise HTTPException(status_code=500, detail="Unexpected error")

    message, chips = _parse_greet_json(raw, first_name)

    action: ChatAction | None = None
    if voices:
        top = voices[0]
        label = f"Join debate: {top['title'][:35]}"
        action = ChatAction(label=label, route=f"/(tabs)/voice-detail/{top['id']}")

    return GreetResponse(
        message=message,
        chips=chips,
        action=action,
        remaining_today=max(0, remaining),
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatResponse:
    settings = get_settings()
    if not settings.xai_api_key:
        raise HTTPException(status_code=503, detail="AI service not configured")

    used = _get_daily_usage(db, current_user.id)
    if used >= _DAILY_CHAT_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"You've used all {_DAILY_CHAT_LIMIT} questions for today. Come back tomorrow!",
        )

    last_user_msg = next((m.content for m in reversed(body.messages) if m.role == "user"), "")
    posts, voices = _fetch_live_context(db, keyword=last_user_msg[:80] if last_user_msg else None)

    actions: list[ChatAction] = []
    context_block = ""
    if posts or voices:
        lines = ["\nRelevant Gist content (use as context if applicable, ignore if not):"]
        for p in posts[:2]:
            lines.append(f"[POST id={p['id']}] {p['title']} — {p['context']}")
        for v in voices[:2]:
            lines.append(f"[DEBATE id={v['id']}] {v['title']} — {v['context']}")
        context_block = "\n".join(lines)
        if posts:
            actions.append(ChatAction(
                label=f"Read: {posts[0]['title'][:40]}",
                route=f"/(tabs)/post/{posts[0]['id']}",
            ))
        if voices:
            actions.append(ChatAction(
                label="Join the debate",
                route=f"/(tabs)/voice-detail/{voices[0]['id']}",
            ))

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT + context_block},
        *[{"role": m.role, "content": m.content} for m in body.messages],
    ]

    try:
        content = await _call_xai(messages, settings, max_tokens=1024)
    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="AI request timed out")
    except Exception as exc:
        logger.exception("Unexpected error in AI chat: %s", exc)
        raise HTTPException(status_code=500, detail="Unexpected error")

    new_count = _increment_daily_usage(db, current_user.id)
    remaining = max(0, _DAILY_CHAT_LIMIT - new_count)

    return ChatResponse(content=content, actions=actions, remaining_today=remaining)
