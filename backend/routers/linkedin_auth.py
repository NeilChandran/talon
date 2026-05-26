"""
LinkedIn session management.
Users paste only their li_at cookie — JSESSIONID is derived automatically.
Session is cached permanently; no live LinkedIn call on status checks.
"""
from fastapi import APIRouter
from pydantic import BaseModel

from services.linkedin_service import (
    clear_session,
    load_session,
    save_session,
    setup_session,
)

router = APIRouter()


class SessionCreate(BaseModel):
    li_at: str


@router.post("/session")
async def set_session(body: SessionCreate):
    """Save LinkedIn li_at cookie, auto-derive JSESSIONID, and validate."""
    li_at = body.li_at.strip()
    result = await setup_session(li_at)

    if result["valid"]:
        jsessionid = result.get("jsessionid", "ajax:0")
        save_session(
            li_at,
            jsessionid,
            {
                "name": result["name"],
                "headline": result.get("headline", ""),
                "linkedin_url": result.get("linkedin_url", ""),
            },
        )
        return {
            "connected": True,
            "name": result["name"],
            "headline": result.get("headline", ""),
            "linkedin_url": result.get("linkedin_url", ""),
        }
    else:
        return {"connected": False, "error": result.get("error", "Invalid session")}


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


@router.delete("/session")
async def disconnect():
    """Clear saved LinkedIn session."""
    clear_session()
    return {"connected": False, "message": "LinkedIn disconnected"}
