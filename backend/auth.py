"""Supabase Auth — verify JWT from Authorization: Bearer <access_token>."""
import os
from typing import Optional

from dotenv import load_dotenv
from fastapi import Header, HTTPException, Request

load_dotenv()

_auth_client = None


def _auth_client():
    global _auth_client
    if _auth_client is None:
        from supabase import create_client

        url = os.getenv("SUPABASE_URL", "").strip()
        key = (
            os.getenv("SUPABASE_KEY", "").strip()
            or os.getenv("SUPABASE_SECRET_KEY", "").strip()
        )
        if key.startswith("ssb_secret_"):
            key = "sb_secret_" + key[len("ssb_secret_") :]
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_KEY required for auth")
        _auth_client = create_client(url, key)
    return _auth_client


def verify_access_token(token: str) -> str:
    """Return user id (UUID string) or raise."""
    token = (token or "").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing access token")
    try:
        res = _auth_client().auth.get_user(token)
        user = res.user
        if not user or not user.id:
            raise HTTPException(status_code=401, detail="Invalid or expired session")
        return str(user.id)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired session")


async def get_current_user_id(
    request: Request,
    authorization: Optional[str] = Header(None),
) -> Optional[str]:
    """FastAPI dependency — returns user id when authenticated, else None."""
    if getattr(request.state, "user_id", None):
        return request.state.user_id
    if authorization and authorization.lower().startswith("bearer "):
        try:
            user_id = verify_access_token(authorization[7:].strip())
            request.state.user_id = user_id
            return user_id
        except HTTPException:
            pass
    return None
