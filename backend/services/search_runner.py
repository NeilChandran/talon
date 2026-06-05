"""Origami-only search pipeline — poll, store leads, heuristic score."""
import asyncio
import os
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import select

from database import AsyncSessionLocal
from models import Lead, Search
from services.origami_service import (
    build_auto_answer,
    build_search_prompt,
    continue_agent_run,
    create_agent_run,
    extract_primary_table,
    fetch_table_rows,
    get_run,
    map_origami_row,
    parse_agent_run_ids,
    parse_pending_questions,
    poll_run_until_done,
    resolve_live_table,
    run_progress_message,
    wants_founders,
)
from services.outreach_templates import build_outreach_kit

search_jobs: Dict[str, Dict[str, Any]] = {}


def heuristic_score(lead: Dict[str, Any], prompt: str) -> int:
    """Simple 1–10 fit score without extra LLM calls."""
    s = 5
    prompt_l = prompt.lower()
    title = (lead.get("title") or "").lower()
    company = (lead.get("company") or "").lower()
    if lead.get("email"):
        s += 2
    if lead.get("linkedin_url"):
        s += 1
    senior = ("vp", "vice president", "director", "head of", "chief", "ceo", "founder", "president")
    if any(t in title for t in senior):
        s += 1
    if "saas" in prompt_l and ("saas" in company or "software" in company):
        s += 1
    if "series" in prompt_l and any(x in company + title for x in ("series", "raised", "funding")):
        s += 1
    return max(1, min(10, s))


async def _update_search(
    search_id: uuid.UUID,
    *,
    status: Optional[str] = None,
    message: Optional[str] = None,
    lead_count: Optional[int] = None,
    origami_job_id: Optional[str] = None,
    table_id: Optional[str] = None,
    table_url: Optional[str] = None,
):
    sid = str(search_id)
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Search).where(Search.id == search_id))
        s = r.scalar_one_or_none()
        if not s:
            return
        if status is not None:
            s.status = status
        if message is not None:
            s.status_message = message
        if lead_count is not None:
            s.lead_count = lead_count
        if origami_job_id is not None:
            s.origami_job_id = origami_job_id
        if table_id is not None:
            s.origami_table_id = table_id
        if table_url is not None:
            s.origami_table_url = table_url
        await db.commit()
    if sid in search_jobs and message:
        search_jobs[sid]["step"] = message
    if sid in search_jobs and lead_count is not None:
        search_jobs[sid]["count"] = lead_count


async def _email_exists(db, email: str) -> bool:
    if not email or not email.strip():
        return False
    from sqlalchemy import func

    em = email.strip().lower()
    r = await db.execute(select(Lead.id).where(func.lower(Lead.email) == em).limit(1))
    return r.scalar_one_or_none() is not None


def _is_founder_person(p: Dict[str, Any], *, want_founders: bool) -> bool:
    if not want_founders:
        return True
    if p.get("first_name") or p.get("last_name"):
        return True
    li = (p.get("linkedin_url") or "").lower()
    if "/in/" in li:
        return True
    title = (p.get("title") or "").lower()
    return any(t in title for t in ("founder", "ceo", "co-founder", "cofounder"))


async def _save_leads(
    search_id: uuid.UUID,
    rows: list,
    prompt: str,
    *,
    replace: bool,
    want_founders: bool = False,
) -> int:
    saved = 0
    async with AsyncSessionLocal() as db:
        if replace:
            old = await db.execute(select(Lead).where(Lead.search_id == search_id))
            for row in old.scalars().all():
                await db.delete(row)

        for raw in rows:
            p = map_origami_row(raw if isinstance(raw, dict) else {})
            if not _is_founder_person(p, want_founders=want_founders):
                continue
            email = (p.get("email") or "").strip()
            if email and await _email_exists(db, email):
                continue
            if email:
                email = email.lower()
            sc = heuristic_score(p, prompt)
            lead = Lead(
                id=uuid.uuid4(),
                search_id=search_id,
                first_name=p.get("first_name", ""),
                last_name=p.get("last_name", ""),
                name=p.get("name", ""),
                title=p.get("title", ""),
                company=p.get("company", ""),
                email=email,
                linkedin_url=p.get("linkedin_url", ""),
                score=sc,
                icp_score=sc,
                sequence_status="new",
                created_at=datetime.utcnow(),
            )
            db.add(lead)
            saved += 1
        await db.commit()
    return saved


async def _ingest_table(
    search_id: uuid.UUID,
    prompt: str,
    tbl: Dict[str, Any],
    *,
    sid: str,
    replace: bool = True,
    want_founders: bool = False,
) -> int:
    table_id = tbl.get("id")
    if not table_id:
        return 0
    rows = await fetch_table_rows(table_id)
    if not rows:
        return 0
    n = await _save_leads(search_id, rows, prompt, replace=replace, want_founders=want_founders)
    name = tbl.get("name") or "table"
    count = tbl.get("leadCount") or n
    if want_founders and n == 0 and "compan" in name.lower():
        msg = "Building founder profiles… (company list ready, waiting for people table)"
    elif n > 0:
        msg = f"{n} founders ready — outreach messages prepared"
    else:
        msg = f"{name}: {count} rows ({n} in Talon)"
    await _update_search(
        search_id,
        lead_count=n,
        message=msg,
        table_id=table_id,
        table_url=tbl.get("url", ""),
    )
    search_jobs[sid]["count"] = n
    return n


async def sync_search_progress(search_id: uuid.UUID) -> Optional[int]:
    """Lightweight sync (safe to call from GET /searches/:id while run is in flight)."""
    sid = str(search_id)
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Search).where(Search.id == search_id))
        s = r.scalar_one_or_none()
        if not s or not s.origami_job_id:
            return None
        prompt = s.prompt
        prior_count = s.lead_count or 0
        agent_id, run_id = parse_agent_run_ids(s.origami_job_id)
        table_hint = s.origami_table_id or ""
        founder_search = wants_founders(prompt)

    if not agent_id or not run_id:
        return None

    try:
        body, _ = await get_run(agent_id, run_id)
        run = body.get("run") or body
        msg = run_progress_message(run)
        if founder_search:
            msg = msg.replace("Finding leads", "Finding founders")
        await _update_search(search_id, message=msg)
        tbl = await resolve_live_table(
            run,
            workspace_id=run.get("workspaceId"),
            table_id_hint=table_hint or None,
            want_founders=founder_search,
        )
        if not tbl or not (tbl.get("leadCount") or 0):
            if founder_search:
                await _update_search(search_id, message="Building founder profiles…")
            return prior_count
        return await _ingest_table(
            search_id, prompt, tbl, sid=sid, replace=True, want_founders=founder_search
        )
    except Exception as e:
        print(f"[search_runner] sync {search_id}: {e}", flush=True)
        return None


async def run_search(search_id: uuid.UUID, prompt: str, *, resume: bool = False) -> None:
    """Full Origami flow for one search record."""
    sid = str(search_id)
    search_jobs[sid] = {"status": "running", "step": "Finding leads...", "count": 0}

    if not os.getenv("ORIGAMI_API_KEY"):
        await _update_search(search_id, status="failed", message="ORIGAMI_API_KEY not configured")
        search_jobs[sid] = {"status": "failed", "error": "Missing ORIGAMI_API_KEY"}
        return

    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    table_id: Optional[str] = None
    founder_search = wants_founders(prompt)

    async def on_tick(run: Dict[str, Any]):
        nonlocal table_id
        msg = run_progress_message(run)
        if founder_search:
            msg = msg.replace("Finding leads", "Finding founders")
        await _update_search(search_id, message=msg)
        try:
            tbl = await resolve_live_table(
                run,
                workspace_id=run.get("workspaceId"),
                table_id_hint=table_id,
                want_founders=founder_search,
            )
            if tbl and tbl.get("id"):
                table_id = tbl["id"]
                await _ingest_table(
                    search_id, prompt, tbl, sid=sid, replace=True, want_founders=founder_search
                )
        except Exception as e:
            print(f"[search_runner] partial: {e}", flush=True)

    try:
        await _update_search(search_id, status="running", message="Finding leads...")

        terminal: Optional[Dict[str, Any]] = None
        existing_job = ""
        if resume:
            async with AsyncSessionLocal() as db:
                r = await db.execute(select(Search).where(Search.id == search_id))
                s = r.scalar_one_or_none()
                existing_job = (s.origami_job_id or "") if s else ""

        if resume and existing_job:
            agent_id, run_id = parse_agent_run_ids(existing_job)
            if agent_id and run_id:
                from services.origami_service import get_run

                body, _ = await get_run(agent_id, run_id)
                terminal = body.get("run") or body
                if terminal.get("status") == "running":
                    terminal = await poll_run_until_done(agent_id, run_id, on_tick=on_tick, max_wait_sec=900)
                elif terminal.get("status") == "needs_input":
                    await _update_search(search_id, message="Answering Origami questions...")
                    answer = build_auto_answer(terminal, prompt)
                    cont = await continue_agent_run(agent_id, answer)
                    run_next = cont.get("run") or cont
                    run_id = str(run_next.get("id") or "")
                    await _update_search(search_id, origami_job_id=f"{agent_id}:{run_id}")
                    terminal = await poll_run_until_done(agent_id, run_id, on_tick=on_tick, max_wait_sec=900)

        if terminal is None:
            admission = await create_agent_run(build_search_prompt(prompt))
            agent = admission.get("agent") or {}
            run0 = admission.get("run") or {}
            agent_id = str(agent.get("id") or admission.get("agentId") or "")
            run_id = str(run0.get("id") or admission.get("runId") or "")
            if not agent_id or not run_id:
                raise RuntimeError("Origami did not return agent/run ids")

            await _update_search(
                search_id,
                origami_job_id=f"{agent_id}:{run_id}",
                message="Finding leads...",
            )
            search_jobs[sid]["step"] = "Finding leads..."

            terminal = await poll_run_until_done(agent_id, run_id, on_tick=on_tick, max_wait_sec=900)

        for _ in range(3):
            if terminal.get("status") != "needs_input":
                break
            await _update_search(search_id, message="Answering Origami questions...")
            answer = build_auto_answer(terminal, prompt)
            cont = await continue_agent_run(agent_id, answer)
            run_next = cont.get("run") or cont
            run_id = str(run_next.get("id") or "")
            if not run_id:
                break
            await _update_search(search_id, origami_job_id=f"{agent_id}:{run_id}")
            terminal = await poll_run_until_done(agent_id, run_id, on_tick=on_tick, max_wait_sec=900)

        if terminal.get("status") == "needs_input":
            qs = parse_pending_questions(terminal)
            preview = qs[0].get("question", "")[:120] if qs else "Open Origami to answer"
            await _update_search(
                search_id,
                status="needs_input",
                message=f"Still needs input: {preview}",
            )
            search_jobs[sid] = {"status": "needs_input", "step": "Needs input", "questions": qs}
            return

        if terminal.get("status") in ("errored", "timed_out", "cancelled"):
            raise RuntimeError(f"Origami run {terminal.get('status')}")

        tbl = extract_primary_table(terminal)
        if not tbl or not tbl.get("id"):
            import httpx
            from services.origami_service import ORIGAMI_BASE, _headers

            materialize = (
                "Materialize a PEOPLE table of founders with first name, last name, title, company, LinkedIn /in/ URLs."
                if founder_search
                else "Materialize the table with all leads from your research now."
            )
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{ORIGAMI_BASE}/api/v2/agents/{agent_id}/runs",
                    headers=_headers(),
                    json={"prompt": materialize},
                )
                if resp.status_code in (200, 202):
                    run2 = resp.json().get("run") or resp.json()
                    rid2 = run2.get("id")
                    if rid2:
                        terminal = await poll_run_until_done(agent_id, str(rid2), on_tick=on_tick)
                        tbl = extract_primary_table(terminal)

        live = await resolve_live_table(
            terminal,
            workspace_id=terminal.get("workspaceId"),
            table_id_hint=table_id,
            want_founders=founder_search,
        )
        if live and live.get("id"):
            table_id = live["id"]
            table_url = live.get("url", "")
        elif tbl and tbl.get("id"):
            table_id = tbl["id"]
            table_url = tbl.get("url", "")
        else:
            raise RuntimeError(
                "No founder profiles returned from Origami" if founder_search else "No table returned from Origami"
            )
        await _update_search(search_id, message="Enriching...", table_id=table_id, table_url=table_url)

        cells_running = (tbl.get("cells") or {}).get("running", 0)
        if cells_running > 0:
            n = 0
            for _ in range(6):
                await asyncio.sleep(5)
                partial = await fetch_table_rows(table_id)
                if partial:
                    n = await _save_leads(
                        search_id, partial, prompt, replace=True, want_founders=founder_search
                    )
                    await _update_search(search_id, lead_count=n, message=f"Enriching… ({n} founders)")
                    search_jobs[sid]["count"] = n
                if n and n >= (tbl.get("leadCount") or 0):
                    break

        await _update_search(search_id, message="Scoring leads...")
        rows = await fetch_table_rows(table_id)
        if not rows:
            raise RuntimeError("Origami table empty")

        saved = await _save_leads(search_id, rows, prompt, replace=True, want_founders=founder_search)
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(Search).where(Search.id == search_id))
            srow = r.scalar_one_or_none()
            tpl = (srow.linkedin_message_template or "").strip() if srow else ""
        kit = build_outreach_kit(prompt, linkedin_template=tpl)
        done_msg = (
            f"Done — {saved} founders ready. LinkedIn + email copy prepared — use Send & export."
            if founder_search and saved
            else f"Done — {saved} leads found"
        )
        await _update_search(
            search_id,
            status="completed",
            message=done_msg,
            lead_count=saved,
            table_id=table_id,
            table_url=table_url,
        )
        search_jobs[sid] = {
            "status": "completed",
            "count": saved,
            "step": done_msg,
            "outreach": kit,
        }

    except Exception as e:
        print(f"[search_runner] {search_id}: {e}", flush=True)
        await _update_search(search_id, status="failed", message=str(e)[:200])
        search_jobs[sid] = {"status": "failed", "error": str(e)[:200]}
