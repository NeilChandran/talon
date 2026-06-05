"""
Lead generation agent — Serper → LinkedIn URLs → Proxycurl → Hunter → Claude score.
Replaces Playwright-first path when SERPER_API_KEY is set.
"""
import asyncio
import json
import os
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import or_, select

from database import AsyncSessionLocal
from models import Lead, Search, Workspace, WorkspaceList, WorkspaceListLead
from services.claude_service import client, MODEL
from services.hunter_service import find_email
from services.proxycurl_service import enrich_linkedin_profile
from services.serper_service import extract_linkedin_urls, run_parallel_searches

MAX_LEADS_PER_SEARCH = int(os.getenv("MAX_LEADS_PER_SEARCH", "50"))
NUM_SERPER_QUERIES = 15

QUERY_SYSTEM = (
    "You are a lead generation agent. Given a plain English description of a target audience, "
    "generate 15 varied Google search query strings that would find matching people on LinkedIn, "
    "Crunchbase, Twitter, and personal websites. Use site: operators, quoted phrases, title "
    "variations, and keyword combinations. Return only a JSON array of strings, no other text."
)

SCORE_SYSTEM = (
    "You are a lead scoring agent. Given a list of enriched leads and the original search prompt, "
    "score each lead 1-10 for how well they match. Return a JSON array with fields: linkedin_url, "
    "score, reason. No other text."
)


async def generate_search_queries(prompt: str) -> List[str]:
    message = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=QUERY_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    text = message.content[0].text.strip()
    try:
        queries = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("["), text.rfind("]") + 1
        queries = json.loads(text[start:end]) if start >= 0 and end > start else []
    if not isinstance(queries, list):
        return []
    return [str(q) for q in queries[:NUM_SERPER_QUERIES] if q]


async def score_leads_batch(prompt: str, leads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not leads:
        return []
    payload = json.dumps(
        [
            {
                "linkedin_url": l.get("linkedin_url"),
                "first_name": l.get("first_name"),
                "last_name": l.get("last_name"),
                "title": l.get("title"),
                "company": l.get("company"),
                "email": l.get("email"),
            }
            for l in leads
        ],
        indent=0,
    )[:12000]

    message = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SCORE_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": f"Search prompt: {prompt}\n\nLeads:\n{payload}",
            }
        ],
    )
    text = message.content[0].text.strip()
    try:
        scores = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("["), text.rfind("]") + 1
        scores = json.loads(text[start:end]) if start >= 0 and end > start else []

    by_url = {s.get("linkedin_url", "").lower(): s for s in scores if isinstance(s, dict)}
    for lead in leads:
        key = (lead.get("linkedin_url") or "").lower()
        s = by_url.get(key, {})
        lead["icp_score"] = int(s.get("score", 5))
        lead["score_reason"] = s.get("reason", "")
    return leads


async def _enrich_one(url: str, sem: asyncio.Semaphore) -> Dict[str, Any]:
    async with sem:
        profile = await enrich_linkedin_profile(url)
        if not profile.get("email") and profile.get("first_name"):
            email = await find_email(
                profile.get("first_name", ""),
                profile.get("last_name", ""),
                profile.get("company", ""),
            )
            if email:
                profile["email"] = email
        return profile


async def _update_list_step(list_id: uuid.UUID, step: str, job: Optional[Dict[str, Any]] = None):
    if job is not None:
        job["step"] = step
    async with AsyncSessionLocal() as db:
        lr = await db.execute(select(WorkspaceList).where(WorkspaceList.id == list_id))
        wl = lr.scalar_one_or_none()
        if wl:
            wl.build_step = step
            await db.commit()


async def _lead_exists(db, linkedin_url: str, email: str) -> bool:
    q = select(Lead.id).limit(1)
    filters = []
    if linkedin_url:
        filters.append(Lead.linkedin_url == linkedin_url)
    if email:
        filters.append(Lead.email == email)
    if not filters:
        return False
    r = await db.execute(q.where(or_(*filters)))
    return r.scalar_one_or_none() is not None


async def run_agent_pipeline(
    list_id: uuid.UUID,
    prompt: str,
    job: Optional[Dict[str, Any]] = None,
) -> None:
    """Full 5-step agent; stores up to MAX_LEADS_PER_SEARCH in workspace list."""
    lid = str(list_id)
    if job is not None:
        job["status"] = "running"

    search_id = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        lr = await db.execute(select(WorkspaceList).where(WorkspaceList.id == list_id))
        wl = lr.scalar_one_or_none()
        if not wl:
            if job:
                job["status"] = "failed"
                job["error"] = "List not found"
            return
        wl.status = "building"
        wl.icp_prompt = prompt
        db.add(Search(id=search_id, prompt=prompt, list_id=list_id, status="running", created_at=datetime.utcnow()))
        await db.commit()

    try:
        await _update_list_step(list_id, "Generating search queries...", job)
        queries = await generate_search_queries(prompt)
        if not queries:
            raise RuntimeError("AI did not return search queries")

        await _update_list_step(list_id, f"Running {len(queries)} searches...", job)
        urls = await run_parallel_searches(queries)
        linkedin_urls = extract_linkedin_urls(urls)[:MAX_LEADS_PER_SEARCH]
        if not linkedin_urls:
            raise RuntimeError("No LinkedIn profiles found in search results")

        await _update_list_step(list_id, f"Enriching {len(linkedin_urls)} leads...", job)
        sem = asyncio.Semaphore(5)

        async with AsyncSessionLocal() as db:
            old = await db.execute(select(WorkspaceListLead).where(WorkspaceListLead.list_id == list_id))
            for row in old.scalars().all():
                await db.delete(row)
            await db.commit()

        enriched: List[Dict[str, Any]] = []
        saved = 0
        sort_order = 0

        for idx, url in enumerate(linkedin_urls):
            profile = await _enrich_one(url, sem)
            enriched.append(profile)

            li = (profile.get("linkedin_url") or "").strip()
            em = (profile.get("email") or "").strip()
            async with AsyncSessionLocal() as db:
                if await _lead_exists(db, li, em):
                    await db.commit()
                    continue
                first = profile.get("first_name", "")
                last = profile.get("last_name", "")
                name = profile.get("name") or f"{first} {last}".strip()
                lead_row = Lead(
                    id=uuid.uuid4(),
                    search_id=search_id,
                    name=name,
                    first_name=first,
                    last_name=last,
                    title=profile.get("title", ""),
                    company=profile.get("company", ""),
                    email=em,
                    linkedin_url=li,
                    icp_score=0,
                    score_reason="",
                    source_url=profile.get("source_url", li),
                    sequence_status="new",
                )
                db.add(lead_row)
                db.add(
                    WorkspaceListLead(
                        id=uuid.uuid4(),
                        list_id=list_id,
                        lead_id=lead_row.id,
                        first_name=first,
                        last_name=last,
                        title=profile.get("title", "") or "",
                        company=profile.get("company", "") or "",
                        linkedin_url=li,
                        icp_score=0,
                        extra={"email": em},
                        sort_order=sort_order,
                    )
                )
                sort_order += 1
                saved += 1
                lr = await db.execute(select(WorkspaceList).where(WorkspaceList.id == list_id))
                wl = lr.scalar_one_or_none()
                if wl:
                    wl.row_count = saved
                    wl.build_step = f"Enriching leads… ({saved}/{len(linkedin_urls)})"
                await db.commit()

            if job is not None:
                job["count"] = saved
                job["step"] = f"Enriching leads… ({saved}/{len(linkedin_urls)})"

        await _update_list_step(list_id, "Scoring leads...", job)
        await score_leads_batch(prompt, enriched)
        score_by_url = {(p.get("linkedin_url") or "").lower(): p for p in enriched}

        async with AsyncSessionLocal() as db:
            rr = await db.execute(
                select(WorkspaceListLead, Lead)
                .join(Lead, Lead.id == WorkspaceListLead.lead_id)
                .where(WorkspaceListLead.list_id == list_id)
            )
            for wl_row, lead_row in rr.all():
                key = (wl_row.linkedin_url or "").lower()
                s = score_by_url.get(key, {})
                sc = int(s.get("icp_score", 5))
                reason = s.get("score_reason", "")
                wl_row.icp_score = sc
                wl_row.extra = {**(wl_row.extra or {}), "score_reason": reason}
                lead_row.icp_score = sc
                lead_row.score_reason = reason

            lr = await db.execute(select(WorkspaceList).where(WorkspaceList.id == list_id))
            wl = lr.scalar_one_or_none()
            sr = await db.execute(select(Search).where(Search.id == search_id))
            search = sr.scalar_one_or_none()
            if wl:
                wl.status = "ready"
                wl.row_count = saved
                wl.build_step = f"Done — {saved} leads"
                wl.updated_at = datetime.utcnow()
            if search:
                search.status = "completed"
            if wl:
                wr = await db.execute(select(Workspace).where(Workspace.id == wl.workspace_id))
                ws = wr.scalar_one_or_none()
                if ws:
                    ws.updated_at = datetime.utcnow()
            await db.commit()

        if job:
            job["status"] = "completed"
            job["count"] = saved
            job["step"] = f"Done — {saved} leads"

    except Exception as e:
        print(f"[lead_agent] {list_id}: {e}", flush=True)
        if job:
            job["status"] = "failed"
            job["error"] = str(e)[:200]
        async with AsyncSessionLocal() as db:
            lr = await db.execute(select(WorkspaceList).where(WorkspaceList.id == list_id))
            wl = lr.scalar_one_or_none()
            if wl:
                wl.status = "failed"
                wl.build_step = str(e)[:200]
            sr = await db.execute(select(Search).where(Search.id == search_id))
            search = sr.scalar_one_or_none()
            if search:
                search.status = "failed"
            await db.commit()
