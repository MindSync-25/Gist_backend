import html as _html
import importlib
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.share_token import decode_share_token
from app.models.comic import Comic
from app.models.post import Post

router = APIRouter(prefix="/share", tags=["share"])

_ANDROID_PACKAGE = "com.gist.app"
_PLAY_STORE = f"https://play.google.com/store/apps/details?id={_ANDROID_PACKAGE}"
_APP_STORE = "https://apps.apple.com/app/gist/id6738665797"
_SHARE_CANONICAL_BASE = "https://share.gistverse.com"

# 7 days — maximum R2/S3 presigned URL lifetime.
# Long enough so WhatsApp/Telegram crawlers still get the image days after sharing.
_SHARE_IMAGE_EXPIRY_SECONDS = 7 * 24 * 3600
_WA_PREVIEW_MAX_DIM = 1200
_WA_PREVIEW_TARGET_BYTES = 350 * 1024


def _resolve_share_image_url(image_url: str | None) -> str | None:
    """Return a publicly fetchable URL for use in OG <meta> tags.

    R2 and S3 objects are private — presign them with a 7-day expiry so social
    crawlers (WhatsApp, Telegram, Twitter) can download the image long after the
    link is pasted into a chat.
    """
    if not image_url:
        return None

    from app.core.r2 import is_r2_url, get_r2_client, extract_r2_bucket_and_key
    from app.api.routes.posts import _extract_s3_bucket_and_key, _s3_client

    # Cloudflare R2
    if is_r2_url(image_url):
        result = extract_r2_bucket_and_key(image_url)
        if result:
            bucket, key = result
            try:
                return get_r2_client().generate_presigned_url(
                    "get_object",
                    Params={"Bucket": bucket, "Key": key},
                    ExpiresIn=_SHARE_IMAGE_EXPIRY_SECONDS,
                )
            except Exception:
                pass
        return image_url

    # AWS S3
    s3_ref = _extract_s3_bucket_and_key(image_url)
    if s3_ref is not None:
        bucket, key = s3_ref
        try:
            return _s3_client().generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=_SHARE_IMAGE_EXPIRY_SECONDS,
            )
        except Exception:
            pass

    # Public CDN / external URL — use as-is
    return image_url

_PAGE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>{title_esc} – Gist</title>
  <meta name="description" content="{desc_esc}"/>

  <meta property="og:type" content="article"/>
  <meta property="og:site_name" content="Gist"/>
  <meta property="og:title" content="{title_esc}"/>
  <meta property="og:description" content="{desc_esc}"/>
  <meta property="og:url" content="{canonical_url}"/>
  {og_image}

  <meta name="twitter:card" content="summary_large_image"/>
  <meta name="twitter:title" content="{title_esc}"/>
  <meta name="twitter:description" content="{desc_esc}"/>
  {tw_image}

  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:system-ui,-apple-system,sans-serif;background:#0F172A;color:#F8FAFC;
          min-height:100vh;display:flex;flex-direction:column;align-items:center;
          justify-content:center;padding:24px}}
    .logo{{font-size:28px;font-weight:800;margin-bottom:20px;letter-spacing:-.5px}}
    .logo span{{color:rgb(31,198,188)}}
    .card{{background:#1E293B;border-radius:20px;padding:32px 24px;max-width:420px;
            width:100%;text-align:center;border:1px solid rgba(255,255,255,.08)}}
    .spinner{{width:42px;height:42px;border:3px solid rgba(31,198,188,.2);
               border-top-color:rgb(31,198,188);border-radius:50%;
               animation:spin .9s linear infinite;margin:0 auto 20px}}
    @keyframes spin{{to{{transform:rotate(360deg)}}}}
    h1{{font-size:20px;font-weight:700;margin-bottom:8px}}
    .sub{{font-size:14px;color:#94A3B8;margin-bottom:22px;line-height:1.6}}
    #status{{font-size:13px;color:rgb(31,198,188);margin-bottom:14px;min-height:18px}}
    .btn{{display:block;padding:14px 18px;border-radius:12px;font-size:15px;
           font-weight:600;text-decoration:none;margin-bottom:10px;transition:opacity .2s}}
    .btn:hover{{opacity:.85}}
    .primary{{background:linear-gradient(135deg,rgb(31,198,188),rgb(45,123,248));color:#fff}}
    .secondary{{background:rgba(255,255,255,.07);color:#F8FAFC;
                 border:1px solid rgba(255,255,255,.12)}}
    hr{{border:none;border-top:1px solid rgba(255,255,255,.08);margin:14px 0}}
  </style>
</head>
<body>
  <div class="logo">gist<span>.</span></div>
  <div class="card">
    <div class="spinner" id="sp"></div>
    <h1>Opening Gist&hellip;</h1>
    <p id="status">Launching the app</p>
    <p class="sub">{title_esc}</p>
    <a href="#" class="btn primary" id="storeBtn" style="display:none">Download Gist</a>
    <hr/>
    <a href="https://gistverse.com" class="btn secondary">Visit Gistverse.com</a>
  </div>
  <script>
  (function(){{
    var PKG   = '{pkg}';
    var PLAY  = '{play}';
    var STORE = '{store}';
    var DEEP  = 'gist://post/{deep_link_id}';
    var ua = navigator.userAgent || '';
    var isAndroid = /android/i.test(ua);
    var isIOS     = /iphone|ipad|ipod/i.test(ua);
    var btn    = document.getElementById('storeBtn');
    var status = document.getElementById('status');
    var sp     = document.getElementById('sp');

    function showFallback(msg, href, label) {{
      sp.style.display = 'none';
      status.textContent = msg;
      btn.href = href;
      btn.textContent = label;
      btn.style.display = 'block';
    }}

    if (isAndroid) {{
      // Android intent URL: tries custom scheme; falls back to Play Store automatically
      var intentUrl =
        'intent://post/{deep_link_id}' +
        '#Intent;scheme=gist;package=' + PKG +
        ';S.browser_fallback_url=' + encodeURIComponent(PLAY) + ';end';
      window.location.href = intentUrl;
      setTimeout(function() {{
        showFallback('App not found. Download Gist to view this post.', PLAY, 'Get Gist on Google Play');
      }}, 2200);
    }} else if (isIOS) {{
      window.location.href = DEEP;
      setTimeout(function() {{
        showFallback('App not found. Download Gist to view this post.', STORE, 'Get Gist on the App Store');
      }}, 2200);
    }} else {{
      // Desktop
      sp.style.display = 'none';
      status.textContent = 'Open this link on your phone to view the post in Gist.';
    }}
  }})();
  </script>
</body>
</html>"""


def _fresh_comic_image_url(comic: Comic) -> str | None:
    """Generate a fresh 7-day presigned URL from the comic's raw s3_key.

    comic.s3_url is a short-lived presigned URL stored at generation time and
    is always expired by the time someone uses a share link.  We re-sign from
    the raw key instead with the full share expiry.
    """
    if not comic.s3_key:
        return None

    from app.core.r2 import get_r2_client
    from app.core.config import get_settings
    settings = get_settings()

    try:
        return get_r2_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.r2_images_bucket, "Key": comic.s3_key},
            ExpiresIn=_SHARE_IMAGE_EXPIRY_SECONDS,
        )
    except Exception:
        pass

    # Legacy S3 fallback
    try:
        from app.api.routes.posts import _s3_client
        return _s3_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.s3_bucket_name, "Key": comic.s3_key},
            ExpiresIn=_SHARE_IMAGE_EXPIRY_SECONDS,
        )
    except Exception:
        return None


def _normalize_preview_image(content: bytes, media_type: str) -> tuple[bytes, str]:
    """Convert source image into a WhatsApp-friendly JPEG preview payload.

    Some crawlers are sensitive to heavy PNG/WEBP images. We convert to JPEG,
    cap dimensions, and compress to a smaller payload for consistent unfurling.
    """
    try:
        image_mod = importlib.import_module("PIL.Image")
        with image_mod.open(BytesIO(content)) as img:
            rgb = img.convert("RGB")
            rgb.thumbnail((_WA_PREVIEW_MAX_DIM, _WA_PREVIEW_MAX_DIM))

            # Try a few quality levels to keep payload crawler-friendly.
            for quality in (85, 75, 65):
                out = BytesIO()
                rgb.save(out, format="JPEG", quality=quality, optimize=True, progressive=False)
                candidate = out.getvalue()
                if len(candidate) <= _WA_PREVIEW_TARGET_BYTES:
                    return candidate, "image/jpeg"

            # Fallback to the last candidate even if still bigger than target.
            return candidate, "image/jpeg"
    except Exception:
        return content, media_type


def _make_page(
    deep_link_id: str,
    title: str,
    description: str,
    image_url: str | None,
    token: str,
    cache_bust: str | None = None,
) -> str:
    title_esc = _html.escape(title[:180])
    desc_esc = _html.escape(description[:200]) if description else ""
    canonical = f"{_SHARE_CANONICAL_BASE}/share/post/{token}"
    if cache_bust:
        canonical = f"{canonical}?v={cache_bust}"
    # Serve OG image via our domain for better compatibility with chat crawlers.
    # Some crawlers fail on long signed storage URLs but succeed with same-origin image URLs.
    og_image_url = f"{_SHARE_CANONICAL_BASE}/share/image/{token}" if image_url else None
    if og_image_url and cache_bust:
        og_image_url = f"{og_image_url}?v={cache_bust}"
    og_image = ""
    if og_image_url:
        og_image_esc = _html.escape(og_image_url)
        og_image = "\n".join([
            f'<meta property="og:image" content="{og_image_esc}"/>',
            f'<meta property="og:image:secure_url" content="{og_image_esc}"/>',
            '<meta property="og:image:type" content="image/jpeg"/>',
            '<meta property="og:image:width" content="1200"/>',
            '<meta property="og:image:height" content="630"/>',
        ])
    tw_image = f'<meta name="twitter:image" content="{_html.escape(og_image_url)}"/>' if og_image_url else ""
    return _PAGE_TEMPLATE.format(
        title_esc=title_esc,
        desc_esc=desc_esc,
        canonical_url=_html.escape(canonical),
        og_image=og_image,
        tw_image=tw_image,
        pkg=_ANDROID_PACKAGE,
        play=_PLAY_STORE,
        store=_APP_STORE,
        deep_link_id=deep_link_id,
    )


@router.get("/post/{token}", response_class=HTMLResponse, include_in_schema=False)
def share_post_page(token: str, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    settings = get_settings()
    decoded = decode_share_token(token, settings.jwt_secret)
    if decoded is None:
        raise HTTPException(status_code=404, detail="Not found")

    content_type, item_id = decoded
    cache_bust = request.query_params.get("v")

    if content_type == "comic":
        comic = db.get(Comic, item_id)
        if comic is None:
            raise HTTPException(status_code=404, detail="Not found")
        page = _make_page(
            deep_link_id=f"db-{item_id}",
            title=comic.banner_title or comic.headline or "Check out this comic on Gist",
            description=comic.summary or comic.headline or "Discover AI-generated news comics on Gist.",
            image_url=_fresh_comic_image_url(comic),
            token=token,
            cache_bust=cache_bust,
        )
    else:
        post = db.get(Post, item_id)
        if post is None or post.status != "published" or post.visibility != "public":
            raise HTTPException(status_code=404, detail="Not found")
        image_url = _resolve_share_image_url(post.image_url)
        deep_link_id = f"post-{item_id}"

        # Some legacy shares point to a post row backed by a comic where post.image_url may be empty.
        # In that case, use the comic image so social previews still render.
        if not image_url and post.comic_id:
            linked_comic = db.get(Comic, post.comic_id)
            if linked_comic is not None:
                image_url = _fresh_comic_image_url(linked_comic)
                deep_link_id = f"db-{linked_comic.id}"
        elif not image_url and post.source_type == "comic_pipeline":
            linked_comic = db.get(Comic, post.id)
            if linked_comic is not None:
                image_url = _fresh_comic_image_url(linked_comic)
                deep_link_id = f"db-{linked_comic.id}"

        page = _make_page(
            deep_link_id=deep_link_id,
            title=post.title or "Check out this post on Gist",
            description=post.description or "Discover AI-generated news comics, Voice debates, and short video on Gist.",
            image_url=image_url,
            token=token,
            cache_bust=cache_bust,
        )

    return HTMLResponse(content=page, status_code=200)


@router.get("/image/{token}", include_in_schema=False)
def share_image(token: str, db: Session = Depends(get_db)) -> Response:
    settings = get_settings()
    decoded = decode_share_token(token, settings.jwt_secret)
    if decoded is None:
        raise HTTPException(status_code=404, detail="Not found")

    content_type, item_id = decoded

    if content_type == "comic":
        comic = db.get(Comic, item_id)
        if comic is None:
            raise HTTPException(status_code=404, detail="Not found")
        image_url = _fresh_comic_image_url(comic)
    else:
        post = db.get(Post, item_id)
        if post is None or post.status != "published" or post.visibility != "public":
            raise HTTPException(status_code=404, detail="Not found")
        image_url = _resolve_share_image_url(post.image_url)
        if not image_url and post.comic_id:
            linked_comic = db.get(Comic, post.comic_id)
            if linked_comic is not None:
                image_url = _fresh_comic_image_url(linked_comic)
        elif not image_url and post.source_type == "comic_pipeline":
            linked_comic = db.get(Comic, post.id)
            if linked_comic is not None:
                image_url = _fresh_comic_image_url(linked_comic)

    if not image_url:
        raise HTTPException(status_code=404, detail="Not found")

    try:
        upstream = httpx.get(
            image_url,
            timeout=20.0,
            follow_redirects=True,
            headers={
                "User-Agent": "WhatsApp/2.24 ShareCrawler",
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            },
        )
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")

    if upstream.status_code != 200:
        raise HTTPException(status_code=404, detail="Not found")

    media_type = upstream.headers.get("content-type", "image/png").split(";", 1)[0].strip().lower()
    content = upstream.content

    # Normalize all preview images to lightweight JPEG for crawler compatibility.
    content, media_type = _normalize_preview_image(content, media_type)

    if not media_type.startswith("image/"):
        media_type = "image/jpeg"

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Cache-Control": "public, max-age=86400, s-maxage=86400",
            "Content-Disposition": "inline",
            "X-Robots-Tag": "noindex",
        },
    )
