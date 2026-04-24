import html as _html

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.post import Post

router = APIRouter(prefix="/share", tags=["share"])

_ANDROID_PACKAGE = "com.gist.app"
_PLAY_STORE = f"https://play.google.com/store/apps/details?id={_ANDROID_PACKAGE}"
# TODO: replace the id below with the real numeric App Store ID once the app is published
_APP_STORE = "https://apps.apple.com/app/gist/id6738665797"

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
    var DEEP  = 'gist://post/post-{post_id}';
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
        'intent://post/post-{post_id}' +
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


def _make_page(post_id: int, title: str, description: str, image_url: str | None) -> str:
    title_esc = _html.escape(title[:180])
    desc_esc = _html.escape(description[:200]) if description else ""
    canonical = f"https://gist-backend.fly.dev/share/post/{post_id}"
    og_image = f'<meta property="og:image" content="{_html.escape(image_url)}"/>' if image_url else ""
    tw_image = f'<meta name="twitter:image" content="{_html.escape(image_url)}"/>' if image_url else ""
    return _PAGE_TEMPLATE.format(
        title_esc=title_esc,
        desc_esc=desc_esc,
        canonical_url=_html.escape(canonical),
        og_image=og_image,
        tw_image=tw_image,
        pkg=_ANDROID_PACKAGE,
        play=_PLAY_STORE,
        store=_APP_STORE,
        post_id=post_id,
    )


@router.get("/post/{post_id}", response_class=HTMLResponse, include_in_schema=False)
def share_post_page(post_id: int, db: Session = Depends(get_db)) -> HTMLResponse:
    post = db.get(Post, post_id)
    if post is None or post.status != "published" or post.visibility != "public":
        raise HTTPException(status_code=404, detail="Post not found")

    html = _make_page(
        post_id=post_id,
        title=post.title or "Check out this post on Gist",
        description=post.description or "Discover AI-generated news comics, Voice debates, and short video on Gist.",
        image_url=post.image_url,
    )
    return HTMLResponse(content=html, status_code=200)
