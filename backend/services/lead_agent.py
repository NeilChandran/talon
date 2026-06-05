"""
Lead generation agent — Serper → LinkedIn URLs → Proxycurl → Hunter → Claude score.
"""
import asyncio
import json
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from services.claude_service import client, MODEL
from services.hunter_service import find_email
from services.proxycurl_service import enrich_linkedin_profile
from services.serper_service import extract_linkedin_urls, run_parallel_searches
from store import get_store

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
    db = get_store()
    wl = await db.get_workspace_list(list_id)
    if wl:
        await db.update("workspace_lists", list_id, {"build_step": step})


async def _lead_exists(db, linkedin_url: str, email: str) -> bool:
    return await db.lead_exists_url_or_email(linkedin_url, email)


async def run_agent_pipeline(
    list_id: uuid.UUID,
    prompt: str,
    job: Optional[Dict[str, Any]] = None,
) -> None:
    """Full 5-step agent; stores up to MAX_LEADS_PER_SEARCH in workspace list."""
    if job is not None:
        job["status"] = "running"

    search_id = str(uuid.uuid4())
    db = get_store()
    wl = await db.get_workspace_list(list_id)
    if not wl:
        if job:
            job["status"] = "failed"
            job["error"] = "List not found"
        return

    now = datetime.utcnow().isoformat()
    await db.update(
        "workspace_lists",
        list_id,
        {"status": "building", "icp_prompt": prompt, "updated_at": now},
    )
    await db.insert(
        "searches",
        {
            "id": search_id,
            "prompt": prompt,
            "list_id": str(list_id),
            "status": "running",
            "created_at": now,
        },
    )

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

        await db.delete_workspace_list_leads(list_id)

        enriched: List[Dict[str, Any]] = []
        saved = 0
        sort_order = 0

        for idx, url in enumerate(linkedin_urls):
            profile = await _enrich_one(url, sem)
            enriched.append(profile)

            li = (profile.get("linkedin_url") or "").strip()
            em = (profile.get("email") or "").strip()
            if await _lead_exists(db, li, em):
                continue

            first = profile.get("first_name", "")
            last = profile.get("last_name", "")
            name = profile.get("name") or f"{first} {last}".strip()
            lead_id = str(uuid.uuid4())
            row_now = datetime.utcnow().isoformat()
            await db.insert(
                "leads",
                {
                    "id": lead_id,
                    "search_id": search_id,
                    "name": name,
                    "first_name": first,
                    "last_name": last,
                    "title": profile.get("title", ""),
                    "company": profile.get("company", ""),
                    "email": em,
                    "linkedin_url": li,
                    "icp_score": 0,
                    "score_reason": "",
                    "source_url": profile.get("source_url", li),
                    "sequence_status": "new",
                    "created_at": row_now,
                    "updated_at": row_now,
                },
            )
            await db.insert(
                "workspace_list_leads",
                {
                    "id": str(uuid.uuid4()),
                    "list_id": str(list_id),
                    "lead_id": lead_id,
                    "first_name": first,
                    "last_name": last,
                    "title": profile.get("title", "") or "",
                    "company": profile.get("company", "") or "",
                    "linkedin_url": li,
                    "icp_score": 0,
                    "extra": {"email": em},
                    "sort_order": sort_order,
                    "created_at": row_now,
                },
            )
            sort_order += 1
            saved += 1
            await db.update(
                "workspace_lists",
                list_id,
                {
                    "row_count": saved,
                    "build_step": f"Enriching leads… ({saved}/{len(linkedin_urls)})",
                },
            )

            if job is not None:
                job["count"] = saved
                job["step"] = f"Enriching leads… ({saved}/{len(linkedin_urls)})"

        await _update_list_step(list_id, "Scoring leads...", job)
        await score_leads_batch(prompt, enriched)
        score_by_url = {(p.get("linkedin_url") or "").lower(): p for p in enriched}

        pairs = await db.list_workspace_list_leads_joined(list_id)
        for wl_row, lead_row in pairs:
            if not lead_row:
                continue
            key = (wl_row.linkedin_url or "").lower()
            s = score_by_url.get(key, {})
            sc = int(s.get("icp_score", 5))
            reason = s.get("score_reason", "")
            await db.update(
                "workspace_list_leads",
                wl_row.id,
                {
                    "icp_score": sc,
                    "extra": {**(wl_row.extra or {}), "score_reason": reason},
                },
            )
            await db.update(
                "leads",
                lead_row.id,
                {"icp_score": sc, "score_reason": reason, "updated_at": datetime.utcnow().isoformat()},
            )

        done_now = datetime.utcnow().isoformat()
        await db.update(
            "workspace_lists",
            list_id,
            {
                "status": "ready",
                "row_count": saved,
                "build_step": f"Done — {saved} leads",
                "updated_at": done_now,
            },
        )
        await db.update_search(search_id, status="completed")
        wl = await db.get_workspace_list(list_id)
        if wl:
            await db.update(
                "workspaces",
                wl.workspace_id,
                {"updated_at": done_now},
            )

        if job:
            job["status"] = "completed"
            job["count"] = saved
            job["step"] = f"Done — {saved} leads"

    except Exception as e:
        print(f"[lead_agent] {list_id}: {e}", flush=True)
        if job:
            job["status"] = "failed"
            job["error"] = str(e)[:200]
        wl = await db.get_workspace_list(list_id)
        if wl:
            await db.update(
                "workspace_lists",
                list_id,
                {"status": "failed", "build_step": str(e)[:200]},
            )
        search = await db.get_search(search_id)
        if search:
            await db.update_search(search_id, status="failed")
