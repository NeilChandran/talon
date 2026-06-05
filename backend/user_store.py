"""User-scoped Supabase access — enforces user_id on searches and leads."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Union

from store import Record, SupabaseStore, get_store


class UserStore:
    def __init__(self, user_id: Optional[str], store: Optional[SupabaseStore] = None):
        self.user_id = str(user_id) if user_id else None
        self._store = store or get_store()

    def _owns_search(self, row: Optional[Record]) -> bool:
        if not self.user_id:
            return bool(row)
        return bool(row and str(row.user_id or "") == self.user_id)

    def _owns_lead(self, row: Optional[Record]) -> bool:
        if not self.user_id:
            return bool(row)
        return bool(row and str(row.user_id or "") == self.user_id)

    # ─── Searches ─────────────────────────────────────────────────────────────

    async def get_search(self, search_id: Union[str, uuid.UUID]) -> Optional[Record]:
        row = await self._store.get_search(search_id)
        return row if self._owns_search(row) else None

    async def create_search(self, prompt: str) -> Record:
        return await self._store.create_search(prompt, user_id=self.user_id)

    async def update_search(self, search_id: Union[str, uuid.UUID], **fields) -> Optional[Record]:
        if not await self.get_search(search_id):
            return None
        return await self._store.update_search(search_id, **fields)

    async def list_recent_searches(self, limit: int = 12) -> List[Record]:
        if self.user_id:
            return await self._store.select_many(
                "searches",
                filters={"user_id": self.user_id},
                order="created_at",
                desc=True,
                limit=limit,
            )
        return await self._store.list_recent_searches(limit)

    async def get_running_search(self) -> Optional[Record]:
        if self.user_id:
            rows = await self._store.select_many(
                "searches",
                filters={"user_id": self.user_id, "status": "running"},
                limit=1,
            )
            return rows[0] if rows else None
        return await self._store.get_running_search()

    # ─── Leads ────────────────────────────────────────────────────────────────

    async def list_leads_by_search(
        self, search_id: Union[str, uuid.UUID], *, order: str = "created_at"
    ) -> List[Record]:
        if not await self.get_search(search_id):
            return []
        filters: Dict[str, Any] = {"search_id": str(search_id)}
        if self.user_id:
            filters["user_id"] = self.user_id
        return await self._store.select_many(
            "leads",
            filters=filters,
            order=order,
            desc=False,
        )

    async def delete_leads_for_search(self, search_id: Union[str, uuid.UUID]) -> None:
        if await self.get_search(search_id):
            where: Dict[str, Any] = {"search_id": str(search_id)}
            if self.user_id:
                where["user_id"] = self.user_id
            await self._store.delete_where("leads", where)

    async def insert_lead(self, row: dict, *, search_id: Optional[str] = None) -> Record:
        sid = search_id or row.get("search_id")
        if sid and not await self.get_search(sid):
            raise PermissionError("Search not found")
        if self.user_id:
            row = {**row, "user_id": self.user_id}
        return await self._store.insert_lead(row)

    async def update_lead(self, lead_id: Union[str, uuid.UUID], **fields) -> Optional[Record]:
        row = await self._store.select_one("leads", lead_id)
        if not self._owns_lead(row):
            return None
        return await self._store.update_lead(lead_id, **fields)

    async def get_lead(self, lead_id: Union[str, uuid.UUID]) -> Optional[Record]:
        row = await self._store.select_one("leads", lead_id)
        return row if self._owns_lead(row) else None

    async def delete_lead(self, lead_id: Union[str, uuid.UUID]) -> bool:
        if await self.get_lead(lead_id):
            await self._store.delete_lead(lead_id)
            return True
        return False

    async def lead_email_exists(self, email: str) -> bool:
        if self.user_id:
            return await self._store.lead_email_exists_for_user(email, self.user_id)
        return await self._store.lead_email_exists(email)

    async def linkedin_urls_for_search(self, search_id: Union[str, uuid.UUID]) -> set:
        leads = await self.list_leads_by_search(search_id)
        return {(l.linkedin_url or "").strip() for l in leads if (l.linkedin_url or "").strip()}

    async def filter_leads(self, **kwargs) -> List[Record]:
        rows = await self._store.filter_leads(**kwargs)
        if not self.user_id:
            return rows
        return [r for r in rows if str(r.user_id or "") == self.user_id]

    async def count_leads_since(self, since_iso: str) -> int:
        filters = {"user_id": self.user_id} if self.user_id else None
        return await self._store.count("leads", filters=filters)

    async def purge_all_leads(self) -> None:
        if self.user_id:
            await self._store.delete_where("leads", {"user_id": self.user_id})
        else:
            await self._store.purge_all_leads()

    async def latest_campaign_for_search(self, search_id: Union[str, uuid.UUID]):
        if not await self.get_search(search_id):
            return None
        return await self._store.latest_campaign_for_search(search_id)

    async def delete_search(self, search_id: Union[str, uuid.UUID]) -> bool:
        return await self._store.delete_search(search_id)

    async def list_enrollments(self, campaign_id):
        return await self._store.list_enrollments(campaign_id)

    @property
    def raw(self) -> SupabaseStore:
        """Escape hatch for non-scoped tables (sequences, campaigns)."""
        return self._store

    def __getattr__(self, name: str):
        """Delegate explore/workspaces/campaigns helpers to the underlying store."""
        return getattr(self._store, name)
