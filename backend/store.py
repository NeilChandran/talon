"""
Supabase data layer — all persistence goes through supabase-py (service role key).
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from dotenv import load_dotenv

load_dotenv()


class Record:
    """Row wrapper with attribute access (replaces SQLAlchemy model instances)."""

    __slots__ = ("_data",)

    def __init__(self, data: dict):
        self._data = dict(data or {})

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return self._data.get(name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_data":
            object.__setattr__(self, name, value)
        else:
            self._data[name] = value

    def __bool__(self) -> bool:
        return bool(self._data)

    def to_dict(self) -> dict:
        return dict(self._data)


def _serialize(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize(v) for v in value]
    return value


def _prepare_row(row: dict) -> dict:
    out: Dict[str, Any] = {}
    for k, v in row.items():
        if v is None and k not in ("email", "name", "title", "company"):
            continue
        out[k] = _serialize(v)
    if "id" in out and out["id"]:
        out["id"] = str(out["id"])
    return out


class SupabaseStore:
    def __init__(self) -> None:
        url = os.getenv("SUPABASE_URL", "").strip()
        key = (
            os.getenv("SUPABASE_KEY", "").strip()
            or os.getenv("SUPABASE_SECRET_KEY", "").strip()
        )
        # Normalize common typo (ssb_secret → sb_secret)
        if key.startswith("ssb_secret_"):
            key = "sb_secret_" + key[len("ssb_secret_") :]
        if not url or not key:
            raise RuntimeError(
                "Set SUPABASE_URL and SUPABASE_KEY (service role / secret) in backend/.env"
            )
        from supabase import create_client

        self._client = create_client(url, key)

    async def _run(self, fn):
        return await asyncio.to_thread(fn)

    # ─── Generic CRUD ─────────────────────────────────────────────────────────

    async def select_one(self, table: str, id_val: Union[str, uuid.UUID]) -> Optional[Record]:
        def _q():
            r = self._client.table(table).select("*").eq("id", str(id_val)).limit(1).execute()
            rows = r.data or []
            return Record(rows[0]) if rows else None

        return await self._run(_q)

    async def select_many(
        self,
        table: str,
        *,
        filters: Optional[Dict[str, Any]] = None,
        in_filters: Optional[Dict[str, List[Any]]] = None,
        order: Optional[str] = None,
        desc: bool = True,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[Record]:
        def _q():
            q = self._client.table(table).select("*")
            for k, v in (filters or {}).items():
                if v is None:
                    q = q.is_(k, "null")
                else:
                    q = q.eq(k, _serialize(v))
            for k, vals in (in_filters or {}).items():
                q = q.in_(k, [_serialize(x) for x in vals])
            if order:
                q = q.order(order, desc=desc)
            if limit is not None:
                q = q.range(offset, offset + limit - 1)
            r = q.execute()
            return [Record(row) for row in (r.data or [])]

        return await self._run(_q)

    async def count(self, table: str, filters: Optional[Dict[str, Any]] = None) -> int:
        def _q():
            q = self._client.table(table).select("*", count="exact", head=True)
            for k, v in (filters or {}).items():
                q = q.eq(k, _serialize(v))
            r = q.execute()
            return r.count or 0

        return await self._run(_q)

    async def insert(self, table: str, row: dict) -> Record:
        payload = _prepare_row(row)

        def _q():
            r = self._client.table(table).insert(payload).execute()
            data = r.data or []
            if not data:
                return Record(payload)
            return Record(data[0])

        return await self._run(_q)

    async def insert_many(self, table: str, rows: List[dict]) -> List[Record]:
        if not rows:
            return []
        payloads = [_prepare_row(r) for r in rows]

        def _q():
            r = self._client.table(table).insert(payloads).execute()
            return [Record(row) for row in (r.data or payloads)]

        return await self._run(_q)

    async def update(
        self,
        table: str,
        id_val: Union[str, uuid.UUID],
        patch: dict,
    ) -> Optional[Record]:
        payload = _prepare_row(patch)
        payload.pop("id", None)

        def _q():
            r = (
                self._client.table(table)
                .update(payload)
                .eq("id", str(id_val))
                .execute()
            )
            rows = r.data or []
            return Record(rows[0]) if rows else None

        return await self._run(_q)

    async def delete_where(self, table: str, filters: Dict[str, Any]) -> None:
        def _q():
            q = self._client.table(table).delete()
            for k, v in filters.items():
                q = q.eq(k, _serialize(v))
            q.execute()

        await self._run(_q)

    async def delete_all(self, table: str) -> None:
        def _q():
            self._client.table(table).delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()

        await self._run(_q)

    # ─── Searches ─────────────────────────────────────────────────────────────

    async def get_search(self, search_id: Union[str, uuid.UUID]) -> Optional[Record]:
        return await self.select_one("searches", search_id)

    async def create_search(self, prompt: str, *, user_id: Optional[str] = None) -> Record:
        row: Dict[str, Any] = {
                "id": str(uuid.uuid4()),
                "prompt": prompt,
                "status": "running",
                "status_message": "Finding leads...",
                "lead_count": 0,
            }
        if user_id:
            row["user_id"] = user_id
        return await self.insert("searches", row)

    async def update_search(self, search_id: Union[str, uuid.UUID], **fields) -> Optional[Record]:
        return await self.update("searches", search_id, fields)

    async def list_recent_searches(self, limit: int = 12) -> List[Record]:
        return await self.select_many("searches", order="created_at", desc=True, limit=limit)

    async def get_running_search(self) -> Optional[Record]:
        rows = await self.select_many(
            "searches", filters={"status": "running"}, limit=1
        )
        return rows[0] if rows else None

    # ─── Leads ────────────────────────────────────────────────────────────────

    async def list_leads_by_search(
        self, search_id: Union[str, uuid.UUID], *, order: str = "created_at"
    ) -> List[Record]:
        return await self.select_many(
            "leads",
            filters={"search_id": str(search_id)},
            order=order,
            desc=False,
        )

    async def delete_leads_for_search(self, search_id: Union[str, uuid.UUID]) -> None:
        await self.delete_where("leads", {"search_id": str(search_id)})

    async def insert_lead(self, row: dict) -> Record:
        if "id" not in row:
            row["id"] = str(uuid.uuid4())
        row.setdefault("created_at", datetime.utcnow().isoformat())
        row.setdefault("updated_at", row["created_at"])
        return await self.insert("leads", row)

    async def update_lead(self, lead_id: Union[str, uuid.UUID], **fields) -> Optional[Record]:
        fields["updated_at"] = datetime.utcnow().isoformat()
        return await self.update("leads", lead_id, fields)

    async def lead_email_exists(self, email: str) -> bool:
        return await self.lead_email_exists_for_user(email, None)

    async def lead_email_exists_for_user(
        self, email: str, user_id: Optional[str]
    ) -> bool:
        if not email or not email.strip():
            return False
        em = email.strip().lower()

        def _q():
            q = self._client.table("leads").select("id").eq("email", em)
            if user_id:
                q = q.eq("user_id", user_id)
            r = q.limit(1).execute()
            return bool(r.data)

        return await self._run(_q)

    async def linkedin_urls_for_search(self, search_id: Union[str, uuid.UUID]) -> set:
        leads = await self.list_leads_by_search(search_id)
        return {(l.linkedin_url or "").strip() for l in leads if (l.linkedin_url or "").strip()}

    # ─── Campaigns ────────────────────────────────────────────────────────────

    async def delete_search(self, search_id: Union[str, uuid.UUID]) -> bool:
        s = await self.get_search(search_id)
        if not s:
            return False
        sid = str(search_id)
        job = (s.origami_job_id or "").strip()
        if job:
            try:
                from services.origami_service import cancel_agent, delete_agent, parse_agent_run_ids

                agent_id, _ = parse_agent_run_ids(job)
                if agent_id:
                    await cancel_agent(agent_id)
                    await delete_agent(agent_id)
            except Exception as e:
                print(f"[delete_search] research cleanup {sid}: {e}", flush=True)
        try:
            camps = await self.select_many("campaigns", filters={"search_id": sid})
            for camp in camps:
                await self.delete_where(
                    "campaign_enrollments", {"campaign_id": str(camp.id)}
                )
                await self.delete_where("campaigns", {"id": str(camp.id)})
        except Exception:
            pass
        await self.delete_leads_for_search(search_id)
        await self.delete_where("searches", {"id": sid})
        return True

    async def latest_campaign_for_search(
        self, search_id: Union[str, uuid.UUID]
    ) -> Optional[Record]:
        rows = await self.select_many(
            "campaigns",
            filters={"search_id": str(search_id)},
            order="created_at",
            desc=True,
            limit=1,
        )
        return rows[0] if rows else None

    async def list_enrollments(self, campaign_id: Union[str, uuid.UUID]) -> List[Record]:
        return await self.select_many(
            "campaign_enrollments",
            filters={"campaign_id": str(campaign_id)},
        )

    async def list_campaigns(self, limit: int = 200) -> List[Record]:
        return await self.select_many("campaigns", order="created_at", desc=True, limit=limit)

    async def count_enrollments(self, campaign_id: Union[str, uuid.UUID]) -> int:
        return await self.count(
            "campaign_enrollments", filters={"campaign_id": str(campaign_id)}
        )

    async def filter_leads(
        self,
        *,
        status: Optional[str] = None,
        min_score: Optional[int] = None,
        max_score: Optional[int] = None,
        search: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        limit: int = 200,
        offset: int = 0,
    ) -> List[Record]:
        def _q():
            q = self._client.table("leads").select("*")
            if status:
                q = q.eq("status", status)
            if min_score is not None:
                q = q.gte("icp_score", min_score)
            if max_score is not None:
                q = q.lte("icp_score", max_score)
            if search:
                pat = f"%{search}%"
                q = q.or_(f"name.ilike.{pat},company.ilike.{pat},email.ilike.{pat}")
            valid = {"created_at", "name", "company", "icp_score", "status"}
            col = sort_by if sort_by in valid else "created_at"
            q = q.order(col, desc=(sort_order == "desc"))
            q = q.range(offset, offset + limit - 1)
            r = q.execute()
            return [Record(row) for row in (r.data or [])]

        return await self._run(_q)

    async def count_leads_since(self, since_iso: str) -> int:
        def _q():
            r = (
                self._client.table("leads")
                .select("*", count="exact", head=True)
                .gte("created_at", since_iso)
                .execute()
            )
            return r.count or 0

        return await self._run(_q)

    async def count_table(self, table: str, filters: Optional[dict] = None) -> int:
        return await self.count(table, filters)

    async def delete_lead(self, lead_id: Union[str, uuid.UUID]) -> None:
        await self.delete_where("leads", {"id": str(lead_id)})

    async def purge_all_leads(self) -> None:
        await self.delete_all("linkedin_outreach_log")
        await self.delete_all("emails_sent")
        await self.delete_all("leads")

    # ─── Sequences ────────────────────────────────────────────────────────────

    async def list_sequences(self) -> List[Record]:
        return await self.select_many("sequences", order="delay_days", desc=False)

    # ─── Campaign enrollments (joins) ─────────────────────────────────────────

    async def enrollment_lead_ids(self, campaign_id: Union[str, uuid.UUID]) -> set:
        rows = await self.list_enrollments(campaign_id)
        return {r.lead_id for r in rows if r.lead_id}

    async def list_enrollments_with_leads(
        self, campaign_id: Union[str, uuid.UUID]
    ) -> List[tuple]:
        enrollments = await self.select_many(
            "campaign_enrollments",
            filters={"campaign_id": str(campaign_id)},
            order="updated_at",
            desc=True,
        )
        lead_ids = [e.lead_id for e in enrollments if e.lead_id]
        leads_map: Dict[str, Record] = {}
        if lead_ids:
            for lead in await self.select_many("leads", in_filters={"id": lead_ids}):
                leads_map[str(lead.id)] = lead
        return [(e, leads_map.get(str(e.lead_id))) for e in enrollments]

    async def count_enrollments_by_status(
        self, campaign_id: Union[str, uuid.UUID], status: str
    ) -> int:
        return await self.count(
            "campaign_enrollments",
            filters={"campaign_id": str(campaign_id), "status": status},
        )

    # ─── Leads (queries) ──────────────────────────────────────────────────────

    async def get_leads_by_ids(self, lead_ids: List[Union[str, uuid.UUID]]) -> List[Record]:
        if not lead_ids:
            return []
        return await self.select_many(
            "leads", in_filters={"id": [str(x) for x in lead_ids]}
        )

    async def list_leads_with_linkedin(self) -> List[Record]:
        def _q():
            r = (
                self._client.table("leads")
                .select("*")
                .not_.is_("linkedin_url", "null")
                .neq("linkedin_url", "")
                .execute()
            )
            return [Record(row) for row in (r.data or [])]

        return await self._run(_q)

    async def list_leads_by_status(
        self, status: str, *, require_member_id: bool = False
    ) -> List[Record]:
        def _q():
            q = self._client.table("leads").select("*").eq("status", status)
            if require_member_id:
                q = q.not_.is_("linkedin_member_id", "null").neq("linkedin_member_id", "")
            r = q.execute()
            return [Record(row) for row in (r.data or [])]

        return await self._run(_q)

    async def lead_exists_url_or_email(self, linkedin_url: str, email: str) -> bool:
        li = (linkedin_url or "").strip()
        em = (email or "").strip()
        if not li and not em:
            return False

        def _q():
            q = self._client.table("leads").select("id").limit(1)
            if li and em:
                q = q.or_(f"linkedin_url.eq.{li},email.eq.{em}")
            elif li:
                q = q.eq("linkedin_url", li)
            else:
                q = q.eq("email", em)
            return bool((q.execute().data or []))

        return await self._run(_q)

    async def count_leads_by_status(self, status: str) -> int:
        return await self.count("leads", filters={"status": status})

    async def count_leads_icp_gte(self, min_score: int) -> int:
        def _q():
            r = (
                self._client.table("leads")
                .select("*", count="exact", head=True)
                .gte("icp_score", min_score)
                .execute()
            )
            return r.count or 0

        return await self._run(_q)

    async def count_leads_icp_range(self, min_score: int, max_score: int) -> int:
        def _q():
            r = (
                self._client.table("leads")
                .select("*", count="exact", head=True)
                .gte("icp_score", min_score)
                .lt("icp_score", max_score)
                .execute()
            )
            return r.count or 0

        return await self._run(_q)

    async def count_leads_icp_lt(self, max_score: int) -> int:
        def _q():
            r = (
                self._client.table("leads")
                .select("*", count="exact", head=True)
                .lt("icp_score", max_score)
                .execute()
            )
            return r.count or 0

        return await self._run(_q)

    # ─── Outreach logs & emails ─────────────────────────────────────────────────

    async def insert_outreach_log(self, row: dict) -> Record:
        if "id" not in row:
            row["id"] = str(uuid.uuid4())
        row.setdefault("created_at", datetime.utcnow().isoformat())
        return await self.insert("linkedin_outreach_log", row)

    async def count_outreach_logs(self, *, status: Optional[str] = None) -> int:
        filters = {"status": status} if status else None
        return await self.count("linkedin_outreach_log", filters)

    async def count_outreach_logs_for_sequence(
        self, sequence_id: Union[str, uuid.UUID], status: str
    ) -> int:
        return await self.count(
            "linkedin_outreach_log",
            filters={"sequence_id": str(sequence_id), "status": status},
        )

    async def list_outreach_logs_since(self, since_iso: str, *, status: str = "sent") -> List[Record]:
        def _q():
            r = (
                self._client.table("linkedin_outreach_log")
                .select("*")
                .gte("sent_at", since_iso)
                .eq("status", status)
                .execute()
            )
            return [Record(row) for row in (r.data or [])]

        return await self._run(_q)

    async def list_emails_sent(self, limit: int = 100) -> List[Record]:
        return await self.select_many("emails_sent", order="sent_at", desc=True, limit=limit)

    # ─── Workspaces ───────────────────────────────────────────────────────────

    async def list_workspaces(self) -> List[Record]:
        return await self.select_many("workspaces", order="updated_at", desc=True)

    async def count_workspace_lists(self, workspace_id: Union[str, uuid.UUID]) -> int:
        return await self.count(
            "workspace_lists", filters={"workspace_id": str(workspace_id)}
        )

    async def list_workspace_lists(
        self, workspace_id: Union[str, uuid.UUID]
    ) -> List[Record]:
        return await self.select_many(
            "workspace_lists",
            filters={"workspace_id": str(workspace_id)},
            order="updated_at",
            desc=True,
        )

    async def get_workspace_list(
        self,
        list_id: Union[str, uuid.UUID],
        workspace_id: Optional[Union[str, uuid.UUID]] = None,
    ) -> Optional[Record]:
        filters: Dict[str, Any] = {"id": str(list_id)}
        if workspace_id is not None:
            filters["workspace_id"] = str(workspace_id)
        rows = await self.select_many("workspace_lists", filters=filters, limit=1)
        return rows[0] if rows else None

    async def delete_workspace_list_leads(self, list_id: Union[str, uuid.UUID]) -> None:
        await self.delete_where("workspace_list_leads", {"list_id": str(list_id)})

    async def list_workspace_list_leads_joined(
        self, list_id: Union[str, uuid.UUID]
    ) -> List[tuple]:
        wl_rows = await self.select_many(
            "workspace_list_leads",
            filters={"list_id": str(list_id)},
            order="sort_order",
            desc=False,
        )
        lead_ids = [r.lead_id for r in wl_rows if r.lead_id]
        leads_map: Dict[str, Record] = {}
        if lead_ids:
            for lead in await self.select_many("leads", in_filters={"id": lead_ids}):
                leads_map[str(lead.id)] = lead
        return [(wl, leads_map.get(str(wl.lead_id))) for wl in wl_rows]

    async def list_workspace_list_leads(
        self, list_id: Union[str, uuid.UUID]
    ) -> List[Record]:
        return await self.select_many(
            "workspace_list_leads", filters={"list_id": str(list_id)}
        )

    # ─── Agent chat ───────────────────────────────────────────────────────────

    async def list_agent_messages(
        self,
        *,
        workspace_id: Optional[Union[str, uuid.UUID]] = None,
        list_id: Optional[Union[str, uuid.UUID]] = None,
        campaign_id: Optional[Union[str, uuid.UUID]] = None,
        order: str = "created_at",
        desc: bool = False,
        limit: Optional[int] = None,
    ) -> List[Record]:
        filters: Dict[str, Any] = {}
        if workspace_id is not None:
            filters["workspace_id"] = str(workspace_id)
        if list_id is not None:
            filters["list_id"] = str(list_id)
        if campaign_id is not None:
            filters["campaign_id"] = str(campaign_id)
        return await self.select_many(
            "agent_chat_messages",
            filters=filters or None,
            order=order,
            desc=desc,
            limit=limit,
        )

    # ─── Explore ──────────────────────────────────────────────────────────────

    async def list_explore_rows(
        self, session_id: Union[str, uuid.UUID], *, order: str = "fit_score", desc: bool = True
    ) -> List[Record]:
        return await self.select_many(
            "explore_rows",
            filters={"session_id": str(session_id)},
            order=order,
            desc=desc,
        )

    async def list_explore_messages(
        self, session_id: Union[str, uuid.UUID]
    ) -> List[Record]:
        return await self.select_many(
            "explore_chat_messages",
            filters={"session_id": str(session_id)},
            order="created_at",
            desc=False,
        )

    async def explore_row_keys(self, session_id: Union[str, uuid.UUID]) -> set:
        rows = await self.select_many(
            "explore_rows",
            filters={"session_id": str(session_id)},
        )
        return {(r.company_name or "", r.website or "") for r in rows}


_store: Optional[SupabaseStore] = None


def get_store():
    global _store
    if _store is not None:
        return _store

    use_sqlite = os.getenv("USE_SQLITE", "").strip().lower() in ("1", "true", "yes")
    if use_sqlite:
        from sqlite_store import SQLiteStore

        print("Using local SQLite (USE_SQLITE=1)", flush=True)
        _store = SQLiteStore()  # type: ignore[assignment]
        return _store

    try:
        s = SupabaseStore()
        s._client.table("searches").select("id").limit(1).execute()
        _store = s
        return _store
    except Exception as e:
        err = str(e)
        if "PGRST205" in err or "Could not find the table" in err:
            from sqlite_store import SQLiteStore

            print(
                "Supabase tables missing — using local SQLite (talon.db). "
                "Run supabase/schema.sql in Supabase SQL Editor for cloud sync.",
                flush=True,
            )
            _store = SQLiteStore()  # type: ignore[assignment]
            return _store
        raise
