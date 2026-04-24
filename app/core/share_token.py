"""
Signed share token utility.

Encodes a content type + ID as an opaque, tamper-proof URL-safe base64 token
so share URLs cannot be enumerated by incrementing numbers.

Token structure (22 chars):
  base64url( packed_uint64 [8 bytes] + HMAC-SHA256(secret, hmac_msg) [8 bytes] )

  packed_uint64 layout:
    - bits 63-32  : content type code (0 = post, 1 = comic)
    - bits 31-0   : item ID

  HMAC message:
    - post  : "share:{post_id}"      (legacy format, backward-compatible)
    - comic : "share:comic:{comic_id}"

The token is signed with the app's jwt_secret.
"""

import base64
import hashlib
import hmac
import struct

_TYPE_POST = 0
_TYPE_COMIC = 1


def _pad(s: str) -> str:
    return s + "=" * (4 - len(s) % 4)


def encode_share_token(item_id: int, secret: str, content_type: str = "post") -> str:
    """Return an opaque URL-safe token for the given item.

    Args:
        item_id: Numeric DB primary key.
        secret: Application JWT secret.
        content_type: ``"post"`` (default) or ``"comic"``.
    """
    if content_type == "comic":
        type_code = _TYPE_COMIC
        hmac_msg = f"share:comic:{item_id}"
    else:
        type_code = _TYPE_POST
        hmac_msg = f"share:{item_id}"

    packed_id = (type_code << 32) | item_id
    id_bytes = struct.pack(">Q", packed_id)
    sig = hmac.new(secret.encode(), hmac_msg.encode(), hashlib.sha256).digest()[:8]
    return base64.urlsafe_b64encode(id_bytes + sig).rstrip(b"=").decode()


def decode_share_token(token: str, secret: str) -> tuple[str, int] | None:
    """Return ``(content_type, item_id)`` or ``None`` if the token is invalid.

    Backward-compatible with tokens generated before content-type support was
    added (those have type_code = 0 = post).
    """
    try:
        raw = base64.urlsafe_b64decode(_pad(token))
    except Exception:
        return None

    if len(raw) != 16:
        return None

    packed_id = struct.unpack(">Q", raw[:8])[0]
    type_code = packed_id >> 32
    item_id = packed_id & 0xFFFF_FFFF

    if type_code == _TYPE_COMIC:
        hmac_msg = f"share:comic:{item_id}"
        content_type = "comic"
    else:
        # Legacy post tokens: type_code == 0, HMAC was "share:{full_packed_id}"
        # Since top 32 bits were 0 the full packed_id == item_id for all real posts.
        hmac_msg = f"share:{item_id}"
        content_type = "post"

    expected_sig = hmac.new(secret.encode(), hmac_msg.encode(), hashlib.sha256).digest()[:8]

    if not hmac.compare_digest(raw[8:], expected_sig):
        return None

    return content_type, item_id
