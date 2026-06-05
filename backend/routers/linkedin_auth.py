"""
LinkedIn session management.
Users paste both li_at AND JSESSIONID cookies from Chrome DevTools.
Session is cached permanently; no live LinkedIn call on status checks.
"""
from fastapi import APIRouter
from pydantic import BaseModel

from services.linkedin_service import (
    _extra_cookies_from_session,
    clear_session,
    launch_login_browser,
    load_session,
    save_session,
    setup_session,
    validate_session,
)

router = APIRouter()


class SessionCreate(BaseModel):
    li_at: str
    jsessionid: str = "ajax:0"
    bcookie: str = ""
    bscookie: str = ""


@router.post("/session")
async def set_session(body: SessionCreate):
    """Validate li_at + JSESSIONID via Voyager API (httpx, no browser)."""
    li_at = body.li_at.strip()
    jsessionid = (body.jsessionid or "ajax:0").strip().strip('"')
    bcookie = body.bcookie.strip() if body.bcookie else ""
    bscookie = body.bscookie.strip() if body.bscookie else ""
    result = await setup_session(li_at, jsessionid=jsessionid, bcookie=bcookie, bscookie=bscookie)

    if not result.get("valid"):
        return {
            "connected": False,
            "error": result.get("error", "LinkedIn rejected the cookies — try Sign in with LinkedIn instead"),
        }

    jsessionid = result.get("jsessionid", "ajax:0")
    save_session(
        li_at,
        jsessionid,
        {
            "name": result.get("name", "LinkedIn User"),
            "headline": result.get("headline", ""),
            "linkedin_url": result.get("linkedin_url", ""),
        },
        bcookie=bcookie,
        bscookie=body.bscookie.strip() if body.bscookie else "",
    )
    return {
        "connected": True,
        "name": result.get("name", "LinkedIn User"),
        "headline": result.get("headline", ""),
        "linkedin_url": result.get("linkedin_url", ""),
    }


@router.post("/session/browser-login")
async def browser_login():
    """
    Open a visible Chrome window so the user can log in to LinkedIn normally.
    Waits for login, extracts cookies, validates profile, saves session.
    """
    result = await launch_login_browser()

    if not result.get("valid"):
        return {"connected": False, "error": result.get("error", "Login failed")}

    li_at = result["li_at"]
    jsessionid = result["jsessionid"]
    # All extra cookies (bcookie, bscookie, lang, liap, etc.) from the browser session
    extra_cookies = {k: v for k, v in result.items() if k not in ("valid", "li_at", "jsessionid")}

    bcookie = extra_cookies.pop("bcookie", "")
    bscookie = extra_cookies.pop("bscookie", "")

    # Profile may already be fetched inside _launch_login_browser_sync (from the live page).
    # If not, fall back to "LinkedIn User" — no extra validation Chrome needed.
    name = result.get("name", "LinkedIn User")
    headline = result.get("headline", "")
    linkedin_url = result.get("linkedin_url", "")

    save_session(
        li_at,
        jsessionid or "ajax:0",
        {"name": name, "headline": headline, "linkedin_url": linkedin_url},
        bcookie=bcookie,
        bscookie=bscookie,
        extra=extra_cookies,
    )

    # Refresh session via API — picks up rotated JSESSIONID + validates write-ready cookies
    saved = load_session()
    if saved:
        verified = await validate_session(
            saved["li_at"],
            saved.get("jsessionid", "ajax:0"),
            saved.get("bcookie", ""),
            saved.get("bscookie", ""),
            _extra_cookies_from_session(saved),
        )
        if verified.get("valid"):
            save_session(
                saved["li_at"],
                verified.get("jsessionid", saved.get("jsessionid", "ajax:0")),
                {
                    "name": verified.get("name", name),
                    "headline": verified.get("headline", headline),
                    "linkedin_url": verified.get("linkedin_url", linkedin_url),
                },
                bcookie=saved.get("bcookie", ""),
                bscookie=saved.get("bscookie", ""),
                extra=_extra_cookies_from_session(saved),
            )
            name = verified.get("name", name)
        else:
            # Browser cookies are saved — httpx check can fail but session may still work
            print(
                f"[linkedin] post-login httpx check failed: {verified.get('error')} — keeping browser session",
                flush=True,
            )

    return {"connected": True, "name": name, "headline": headline, "linkedin_url": linkedin_url}


@router.get("/session/status")
async def get_session_status():
    """
    Return current LinkedIn connection status from cache.
    Does NOT make a live LinkedIn API call — session is permanent until
    the user explicitly disconnects.
    """
    sess = load_session()
    if not sess:
        return {"connected": False}

    # Return cached data — no live validation (session is permanent)
    return {
        "connected": True,
        "name": sess.get("name", "LinkedIn User"),
        "headline": sess.get("headline", ""),
        "linkedin_url": sess.get("linkedin_url", ""),
    }


@router.get("/session/test")
async def test_session():
    """Make a live LinkedIn API call to verify the session is still valid."""
    sess = load_session()
    if not sess:
        return {"connected": False, "error": "No session — connect LinkedIn in Settings"}

    extra = _extra_cookies_from_session(sess)
    result = await validate_session(
        sess["li_at"],
        sess.get("jsessionid", "ajax:0"),
        sess.get("bcookie", ""),
        sess.get("bscookie", ""),
        extra,
    )
    if result["valid"]:
        save_session(
            sess["li_at"],
            result.get("jsessionid", sess.get("jsessionid", "ajax:0")),
            {
                "name": result["name"],
                "headline": result.get("headline", ""),
                "linkedin_url": result.get("linkedin_url", sess.get("linkedin_url", "")),
            },
            bcookie=sess.get("bcookie", ""),
            bscookie=sess.get("bscookie", ""),
            extra=extra,
        )
        return {
            "connected": True,
            "name": result["name"],
            "headline": result.get("headline", ""),
        }
    else:
        return {"connected": False, "error": result.get("error", "Session invalid")}


@router.delete("/session")
async def disconnect():
    """Clear saved LinkedIn session."""
    clear_session()
    return {"connected": False, "message": "LinkedIn disconnected"}
