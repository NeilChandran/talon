"""Build workspace list — Serper agent pipeline (preferred) or Playwright fallback."""
import os
import uuid
from datetime import datetime
from typing import Any, Dict

from sqlalchemy import select

from database import AsyncSessionLocal
from models import Lead, Workspace, WorkspaceList, WorkspaceListLead

build_jobs: Dict[str, Dict[str, Any]] = {}


def _split_name(full: str) -> tuple:
    parts = (full or "").strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


async def run_list_build(list_id: uuid.UUID, prompt: str) -> None:
    """Populate workspace list from ICP prompt."""
    lid = str(list_id)
    build_jobs[lid] = {"status": "running", "step": "Running search agents…", "count": 0}

    async with AsyncSessionLocal() as db:
        lr = await db.execute(select(WorkspaceList).where(WorkspaceList.id == list_id))
        wl = lr.scalar_one_or_none()
        if not wl:
            build_jobs[lid] = {"status": "failed", "error": "List not found"}
            return
        wl.status = "building"
        wl.build_step = "Running search agents…"
        wl.icp_prompt = prompt
        await db.commit()

    if os.getenv("ORIGAMI_API_KEY"):
        from services.origami_list_builder import run_origami_list_build

        await run_origami_list_build(list_id, prompt, job=build_jobs[lid])
        return

    if os.getenv("SERPER_API_KEY") and os.getenv("ANTHROPIC_API_KEY"):
        from services.lead_agent import run_agent_pipeline

        await run_agent_pipeline(list_id, prompt, job=build_jobs[lid])
        return

    # Fallback: LinkedIn Playwright when Serper not configured
    await _run_playwright_fallback(list_id, prompt, lid)


async def _run_playwright_fallback(list_id: uuid.UUID, prompt: str, lid: str) -> None:
    from routers.prospecting import (
        _find_people_via_playwright,
        _score_and_save,
        parse_prospecting_query,
    )
    from services.explore.icp_parser import parse_icp_prompt
    from services.linkedin_service import load_session

    try:
        if not load_session():
            build_jobs[lid] = {"status": "failed", "error": "Add SERPER_API_KEY or connect LinkedIn in Settings."}
            async with AsyncSessionLocal() as db:
                lr = await db.execute(select(WorkspaceList).where(WorkspaceList.id == list_id))
                wl = lr.scalar_one_or_none()
                if wl:
                    wl.status = "failed"
                    wl.build_step = "Configure Serper API or LinkedIn"
                    await db.commit()
            return

        build_jobs[lid]["step"] = "Running search agents (LinkedIn)..."
        parsed = await parse_icp_prompt(prompt)
        legacy = await parse_prospecting_query(prompt)
        if legacy.get("linkedin_keywords"):
            parsed["linkedin_keywords"] = legacy["linkedin_keywords"]

        from routers import prospecting as pr

        fake_job = str(list_id)
        pr.jobs[fake_job] = {"status": "running", "step": "Finding people...", "leads": [], "scraper_status": {}}
        people = await _find_people_via_playwright(parsed, prompt, fake_job)
        if not people:
            raise RuntimeError("No people found.")
        scored = await _score_and_save(fake_job, people, prompt, persist=False)

        async with AsyncSessionLocal() as db:
            old = await db.execute(select(WorkspaceListLead).where(WorkspaceListLead.list_id == list_id))
            for row in old.scalars().all():
                await db.delete(row)
            for i, p in enumerate(scored[:50]):
                first, last = _split_name(p.get("name", ""))
                lead_row = Lead(
                    id=uuid.uuid4(),
                    name=p.get("name", ""),
                    first_name=first,
                    last_name=last,
                    title=p.get("title", ""),
                    company=p.get("company", ""),
                    linkedin_url=p.get("linkedin_url", ""),
                    icp_score=p.get("icp_score", 5),
                    score_reason=p.get("score_reason", ""),
                )
                db.add(lead_row)
                db.add(
                    WorkspaceListLead(
                        id=uuid.uuid4(),
                        list_id=list_id,
                        lead_id=lead_row.id,
                        first_name=first,
                        last_name=last,
                        title=p.get("title", "") or "",
                        company=p.get("company", "") or "",
                        linkedin_url=p.get("linkedin_url", "") or "",
                        icp_score=p.get("icp_score", 5),
                        sort_order=i,
                    )
                )
            lr = await db.execute(select(WorkspaceList).where(WorkspaceList.id == list_id))
            wl = lr.scalar_one_or_none()
            if wl:
                wl.status = "ready"
                wl.row_count = len(scored[:50])
                wl.build_step = f"Done — {wl.row_count} leads"
                wl.updated_at = datetime.utcnow()
            await db.commit()
        build_jobs[lid] = {"status": "completed", "count": len(scored[:50])}
    except Exception as e:
        build_jobs[lid] = {"status": "failed", "error": str(e)[:200]}
        async with AsyncSessionLocal() as db:
            lr = await db.execute(select(WorkspaceList).where(WorkspaceList.id == list_id))
            wl = lr.scalar_one_or_none()
            if wl:
                wl.status = "failed"
                wl.build_step = str(e)[:200]
                await db.commit()
