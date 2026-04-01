import re
from dataclasses import dataclass

from app.core.config import get_settings


@dataclass(frozen=True)
class ModerationResult:
    allowed: bool
    reason: str | None = None


DEFAULT_BLOCKLIST = {
    "kill yourself",
    "kys",
    "nigga",
    "nigger",
    "faggot",
    "retard",
    "slut",
    "whore",
}


def _load_blocklist() -> set[str]:
    settings = get_settings()
    raw = getattr(settings, "comment_moderation_blocklist", "")
    configured = {
        token.strip().lower()
        for token in str(raw).split(",")
        if token.strip()
    }
    return DEFAULT_BLOCKLIST.union(configured)


def _normalized_text(text: str) -> str:
    lowered = text.lower().strip()
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered


def moderate_comment_text(text: str) -> ModerationResult:
    body = _normalized_text(text)
    if not body:
        return ModerationResult(allowed=False, reason="Comment cannot be empty.")

    blocklist = _load_blocklist()
    for phrase in blocklist:
        if phrase and phrase in body:
            return ModerationResult(allowed=False, reason="Comment violates moderation guidelines.")

    url_count = len(re.findall(r"https?://", body))
    if url_count >= 3:
        return ModerationResult(allowed=False, reason="Too many links. Please remove spammy content.")

    if re.search(r"(.)\1{9,}", body):
        return ModerationResult(allowed=False, reason="Comment looks like spam.")

    return ModerationResult(allowed=True)