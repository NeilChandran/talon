"""
Database entrypoint — Supabase + optional authenticated user scope.
"""
from typing import Optional

from fastapi import Depends

from auth import get_current_user_id
from store import get_store
from user_store import UserStore


async def get_db(user_id: Optional[str] = Depends(get_current_user_id)):
    """FastAPI dependency — scoped store when logged in, shared store otherwise."""
    yield UserStore(user_id, get_store())
