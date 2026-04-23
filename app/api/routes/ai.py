from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])

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

_XAI_BASE = "https://api.x.ai/v1"
_MODEL = "grok-3-mini"


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)


class ChatResponse(BaseModel):
    content: str


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    current_user: User = Depends(get_current_user),
) -> ChatResponse:
    settings = get_settings()
    if not settings.xai_api_key:
        raise HTTPException(status_code=503, detail="AI service not configured")

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        *[{"role": m.role, "content": m.content} for m in body.messages],
    ]

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{_XAI_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.xai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": _MODEL,
                    "messages": messages,
                    "stream": False,
                    "max_tokens": 1024,
                },
            )

        if resp.status_code != 200:
            logger.error("xAI error %s: %s", resp.status_code, resp.text)
            raise HTTPException(status_code=502, detail="AI service error")

        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return ChatResponse(content=content)

    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="AI request timed out")
    except Exception as exc:
        logger.exception("Unexpected error in AI chat: %s", exc)
        raise HTTPException(status_code=500, detail="Unexpected error")
