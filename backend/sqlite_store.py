"""Local SQLite store — used when Supabase tables are missing or USE_SQLITE=1."""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from store import Record, _prepare_row


def _db_path() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if "sqlite" in url:
        # sqlite+aiosqlite:////path or sqlite:///./talon.db
        path = url.split("///")[-1] if "///" in url else url.split("sqlite:///")[-1]
        if path.startswith("./"):
            path = str(Path(__file__).parent / path[2:])
        return path
    return str(Path(__file__).parent / "talon.db")


def _norm_id(val: Union[str, uuid.UUID, None]) -> str:
    if val is None:
        return ""
    return str(val).replace("-", "")


def _fmt_id(val: str) -> str:
    s = str(val).replace("-", "")
    if len(s) == 32:
        return f"{s[:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:]}"
    return str(val)


def _row_to_record(row: sqlite3.Row) -> Record:
    data = {k: row[k] for k in row.keys()}
    for k, v in list(data.items()):
        if v and (k == "id" or k.endswith("_id")):
            data[k] = _fmt_id(str(v))
    if "tech_stack" in data and isinstance(data["tech_stack"], str):
        try:
            data["tech_stack"] = json.loads(data["tech_stack"])
        except Exception:
            data["tech_stack"] = []
    return Record(data)


class SQLiteStore:
    def __init__(self) -> None:
        self._path = _db_path()
        self._ensure_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def _table_columns(self, conn: sqlite3.Connection, table: str) -> set:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}

    def _ensure_schema(self) -> None:
        with self._conn() as conn:
            search_cols = self._table_columns(conn, "searches")
            if search_cols and "linkedin_message_template" not in search_cols:
                conn.execute("ALTER TABLE searches ADD COLUMN linkedin_message_template TEXT DEFAULT ''")
            lead_cols = self._table_columns(conn, "leads")
            if lead_cols and "linkedin_draft" not in lead_cols:
                conn.execute("ALTER TABLE leads ADD COLUMN linkedin_draft TEXT")
            if lead_cols and "follow_up_draft" not in lead_cols:
                conn.execute("ALTER TABLE leads ADD COLUMN follow_up_draft TEXT")
            camp_cols = self._table_columns(conn, "campaigns")
            if camp_cols and "search_id" not in camp_cols:
                conn.execute("ALTER TABLE campaigns ADD COLUMN search_id CHAR(32)")
            if search_cols and "origami_launch_at" not in search_cols:
                conn.execute("ALTER TABLE searches ADD COLUMN origami_launch_at TEXT")
            enr_cols = self._table_columns(conn, "campaign_enrollments")
            if enr_cols and "scheduled_at" not in enr_cols:
                conn.execute("ALTER TABLE campaign_enrollments ADD COLUMN scheduled_at TEXT")
            if enr_cols and "origami_send_status" not in enr_cols:
                conn.execute("ALTER TABLE campaign_enrollments ADD COLUMN origami_send_status TEXT")

    async def _run(self, fn):
        return await asyncio.to_thread(fn)

    async def select_one(self, table: str, id_val: Union[str, uuid.UUID]) -> Optional[Record]:
        def _q():
            with self._conn() as conn:
                row = conn.execute(
                    f"SELECT * FROM {table} WHERE id = ? LIMIT 1",
                    (_norm_id(id_val),),
                ).fetchone()
                return _row_to_record(row) if row else None

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
            sql = f"SELECT * FROM {table}"
            params: List[Any] = []
            clauses: List[str] = []
            for k, v in (filters or {}).items():
                if v is None:
                    clauses.append(f"{k} IS NULL")
                else:
                    val = _norm_id(v) if k.endswith("_id") or k == "id" else v
                    clauses.append(f"{k} = ?")
                    params.append(val)
            for k, vals in (in_filters or {}).items():
                if not vals:
                    return []
                placeholders = ",".join("?" * len(vals))
                clauses.append(
                    f"{k} IN ({placeholders})"
                )
                params.extend(_norm_id(x) if k.endswith("_id") or k == "id" else x for x in vals)
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            if order:
                sql += f" ORDER BY {order} {'DESC' if desc else 'ASC'}"
            if limit is not None:
                sql += f" LIMIT {limit} OFFSET {offset}"
            with self._conn() as conn:
                rows = conn.execute(sql, params).fetchall()
                return [_row_to_record(r) for r in rows]

        return await self._run(_q)

    async def count(self, table: str, filters: Optional[Dict[str, Any]] = None) -> int:
        def _q():
            sql = f"SELECT COUNT(*) FROM {table}"
            params: List[Any] = []
            clauses: List[str] = []
            for k, v in (filters or {}).items():
                if v is None:
                    clauses.append(f"{k} IS NULL")
                else:
                    val = _norm_id(v) if k.endswith("_id") or k == "id" else v
                    clauses.append(f"{k} = ?")
                    params.append(val)
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            with self._conn() as conn:
                return conn.execute(sql, params).fetchone()[0]

        return await self._run(_q)

    async def insert(self, table: str, row: dict) -> Record:
        payload = _prepare_row(row)
        if "id" in payload:
            payload["id"] = _norm_id(payload["id"])
        for k in ("search_id", "user_id", "campaign_id", "lead_id", "workspace_id", "list_id"):
            if k in payload and payload[k]:
                payload[k] = _norm_id(payload[k])
        if "tech_stack" in payload and isinstance(payload["tech_stack"], (list, dict)):
            payload["tech_stack"] = json.dumps(payload["tech_stack"])
        payload.setdefault("created_at", datetime.utcnow().isoformat())

        def _q():
            cols = ", ".join(payload.keys())
            placeholders = ", ".join("?" * len(payload))
            with self._conn() as conn:
                conn.execute(
                    f"INSERT INTO {table} ({cols}) VALUES ({placeholders})",
                    list(payload.values()),
                )
            out = dict(payload)
            if "id" in out:
                out["id"] = _fmt_id(out["id"])
            return Record(out)

        return await self._run(_q)

    async def update(
        self, table: str, id_val: Union[str, uuid.UUID], patch: dict
    ) -> Optional[Record]:
        payload = _prepare_row(patch)
        payload.pop("id", None)
        if "tech_stack" in payload and isinstance(payload["tech_stack"], (list, dict)):
            payload["tech_stack"] = json.dumps(payload["tech_stack"])
        if not payload:
            return await self.select_one(table, id_val)

        def _q():
            sets = ", ".join(f"{k} = ?" for k in payload.keys())
            vals = list(payload.values()) + [_norm_id(id_val)]
            with self._conn() as conn:
                conn.execute(f"UPDATE {table} SET {sets} WHERE id = ?", vals)
                row = conn.execute(
                    f"SELECT * FROM {table} WHERE id = ? LIMIT 1",
                    (_norm_id(id_val),),
                ).fetchone()
                return _row_to_record(row) if row else None

        return await self._run(_q)

    async def delete_where(self, table: str, filters: Dict[str, Any]) -> None:
        if not filters:
            await self.delete_all(table)
            return

        def _q():
            clauses = []
            params = []
            for k, v in filters.items():
                val = _norm_id(v) if k.endswith("_id") or k == "id" else v
                clauses.append(f"{k} = ?")
                params.append(val)
            with self._conn() as conn:
                conn.execute(
                    f"DELETE FROM {table} WHERE {' AND '.join(clauses)}",
                    params,
                )

        await self._run(_q)

    async def delete_all(self, table: str) -> None:
        def _q():
            with self._conn() as conn:
                conn.execute(f"DELETE FROM {table}")

        await self._run(_q)

    # ─── Searches & leads (mirror SupabaseStore) ───────────────────────────────

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
        rows = await self.select_many("searches", filters={"status": "running"}, limit=1)
        return rows[0] if rows else None

    async def list_leads_by_search(
        self, search_id: Union[str, uuid.UUID], *, order: str = "created_at"
    ) -> List[Record]:
        return await self.select_many(
            "leads", filters={"search_id": str(search_id)}, order=order, desc=False
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

    async def lead_email_exists_for_user(self, email: str, user_id: Optional[str]) -> bool:
        if not email or not email.strip():
            return False
        em = email.strip().lower()

        def _q():
            with self._conn() as conn:
                if user_id:
                    row = conn.execute(
                        "SELECT id FROM leads WHERE lower(email) = ? AND user_id = ? LIMIT 1",
                        (em, _norm_id(user_id)),
                    ).fetchone()
                else:
                    row = conn.execute(
                        "SELECT id FROM leads WHERE lower(email) = ? LIMIT 1", (em,)
                    ).fetchone()
                return bool(row)

        return await self._run(_q)

    async def filter_leads(self, **kwargs) -> List[Record]:
        status = kwargs.get("status")
        limit = kwargs.get("limit", 200)
        filters = {"status": status} if status else None
        return await self.select_many("leads", filters=filters, limit=limit)

    async def count_leads_since(self, since_iso: str) -> int:
        def _q():
            with self._conn() as conn:
                return conn.execute(
                    "SELECT COUNT(*) FROM leads WHERE created_at >= ?", (since_iso,)
                ).fetchone()[0]

        return await self._run(_q)

    async def count_table(self, table: str, filters: Optional[dict] = None) -> int:
        return await self.count(table, filters)

    async def delete_lead(self, lead_id: Union[str, uuid.UUID]) -> None:
        await self.delete_where("leads", {"id": str(lead_id)})

    async def purge_all_leads(self) -> None:
        await self.delete_all("linkedin_outreach_log")
        await self.delete_all("emails_sent")
        await self.delete_all("leads")

    async def latest_campaign_for_search(self, search_id: Union[str, uuid.UUID]) -> Optional[Record]:
        def _q():
            with self._conn() as conn:
                cols = self._table_columns(conn, "campaigns")
                if "search_id" not in cols:
                    return None
            return "ok"

        if await self._run(_q) is None:
            return None
        rows = await self.select_many(
            "campaigns", filters={"search_id": str(search_id)}, order="created_at", desc=True, limit=1
        )
        return rows[0] if rows else None

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
            def _camp_cols():
                with self._conn() as conn:
                    return self._table_columns(conn, "campaigns")

            cols = await self._run(_camp_cols)
            if cols and "search_id" in cols:
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

    async def list_enrollments(self, campaign_id: Union[str, uuid.UUID]) -> List[Record]:
        return await self.select_many("campaign_enrollments", filters={"campaign_id": str(campaign_id)})

    async def list_campaigns(self, limit: int = 200) -> List[Record]:
        return await self.select_many("campaigns", order="created_at", desc=True, limit=limit)

    async def count_enrollments(self, campaign_id: Union[str, uuid.UUID]) -> int:
        return await self.count("campaign_enrollments", filters={"campaign_id": str(campaign_id)})

    async def count_enrollments_by_status(
        self, campaign_id: Union[str, uuid.UUID], status: str
    ) -> int:
        return await self.count(
            "campaign_enrollments",
            filters={"campaign_id": str(campaign_id), "status": status},
        )

    async def list_sequences(self) -> List[Record]:
        return await self.select_many("sequences", order="delay_days", desc=False)

    async def enrollment_lead_ids(self, campaign_id: Union[str, uuid.UUID]) -> set:
        rows = await self.list_enrollments(campaign_id)
        return {_norm_id(r.lead_id) for r in rows if r.lead_id}

    async def list_enrollments_with_leads(
        self, campaign_id: Union[str, uuid.UUID]
    ) -> List[tuple]:
        enrollments = await self.list_enrollments(campaign_id)
        lead_ids = [e.lead_id for e in enrollments if e.lead_id]
        leads_map: Dict[str, Record] = {}
        if lead_ids:
            for lead in await self.select_many("leads", in_filters={"id": lead_ids}):
                leads_map[_norm_id(lead.id)] = lead
        return [(e, leads_map.get(_norm_id(e.lead_id))) for e in enrollments]

    async def get_leads_by_ids(self, lead_ids: List[Union[str, uuid.UUID]]) -> List[Record]:
        if not lead_ids:
            return []
        return await self.select_many("leads", in_filters={"id": list(lead_ids)})

    async def list_leads_with_linkedin(self) -> List[Record]:
        rows = await self.select_many("leads")
        return [r for r in rows if (r.linkedin_url or "").strip()]

    def __getattr__(self, name: str):
        raise AttributeError(f"SQLiteStore.{name} not implemented — set up Supabase for full features")
