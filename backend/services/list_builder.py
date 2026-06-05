"""Build workspace list — Serper agent pipeline (preferred) or Playwright fallback."""
import os
import uuid
from datetime import datetime
from typing import Any, Dict

from store import get_store

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

    db = get_store()
    wl = await db.get_workspace_list(list_id)
    if not wl:
        build_jobs[lid] = {"status": "failed", "error": "List not found"}
        return
    await db.update(
        "workspace_lists",
        list_id,
        {
            "status": "building",
            "build_step": "Running search agents…",
            "icp_prompt": prompt,
            "updated_at": datetime.utcnow().isoformat(),
        },
    )

    if os.getenv("ORIGAMI_API_KEY"):
        from services.origami_list_builder import run_origami_list_build

        await run_origami_list_build(list_id, prompt, job=build_jobs[lid])
        return

    if os.getenv("SERPER_API_KEY") and os.getenv("ANTHROPIC_API_KEY"):
        from services.lead_agent import run_agent_pipeline

        await run_agent_pipeline(list_id, prompt, job=build_jobs[lid])
        return

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
            db = get_store()
            wl = await db.get_workspace_list(list_id)
            if wl:
                await db.update(
                    "workspace_lists",
                    list_id,
                    {
                        "status": "failed",
                        "build_step": "Configure Serper API or LinkedIn",
                    },
                )
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

        db = get_store()
        await db.delete_workspace_list_leads(list_id)
        now = datetime.utcnow().isoformat()
        rows_to_insert = []
        for i, p in enumerate(scored[:50]):
            first, last = _split_name(p.get("name", ""))
            lead_id = str(uuid.uuid4())
            await db.insert(
                "leads",
                {
                    "id": lead_id,
                    "name": p.get("name", ""),
                    "first_name": first,
                    "last_name": last,
                    "title": p.get("title", ""),
                    "company": p.get("company", ""),
                    "linkedin_url": p.get("linkedin_url", ""),
                    "icp_score": p.get("icp_score", 5),
                    "score_reason": p.get("score_reason", ""),
                    "created_at": now,
                    "updated_at": now,
                },
            )
            rows_to_insert.append({
                "id": str(uuid.uuid4()),
                "list_id": str(list_id),
                "lead_id": lead_id,
                "first_name": first,
                "last_name": last,
                "title": p.get("title", "") or "",
                "company": p.get("company", "") or "",
                "linkedin_url": p.get("linkedin_url", "") or "",
                "icp_score": p.get("icp_score", 5),
                "sort_order": i,
                "created_at": now,
            })
        if rows_to_insert:
            await db.insert_many("workspace_list_leads", rows_to_insert)

        await db.update(
            "workspace_lists",
            list_id,
            {
                "status": "ready",
                "row_count": len(scored[:50]),
                "build_step": f"Done — {len(scored[:50])} leads",
                "updated_at": now,
            },
        )
        build_jobs[lid] = {"status": "completed", "count": len(scored[:50])}
    except Exception as e:
        build_jobs[lid] = {"status": "failed", "error": str(e)[:200]}
        db = get_store()
        wl = await db.get_workspace_list(list_id)
        if wl:
            await db.update(
                "workspace_lists",
                list_id,
                {"status": "failed", "build_step": str(e)[:200]},
            )
