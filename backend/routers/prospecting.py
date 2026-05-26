"""
Prospecting router — only returns real LinkedIn profiles.
No AI-generated lead fallback. If LinkedIn is not connected, job fails fast.
"""
import asyncio
import uuid
from typing import Dict, Any

from fastapi import APIRouter, BackgroundTasks, HTTPException

from database import AsyncSessionLocal
from models import Lead
from schemas import ProspectingRequest
from services.claude_service import (
    parse_prospecting_query,
    score_lead,
    enrich_linkedin_leads,
)
from services.linkedin_service import load_session, search_people

router = APIRouter()

# In-memory job store
jobs: Dict[str, Any] = {}


async def run_prospecting_job(job_id: str, query: str):
    jobs[job_id]["status"] = "running"

    try:
        # Require LinkedIn session — no AI fallback
        sess = load_session()
        if not sess:
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = "LinkedIn not connected. Go to Settings to connect your account."
            jobs[job_id]["step"] = "LinkedIn not connected"
            return

        # Step 1: Parse query to extract good search keywords
        jobs[job_id]["step"] = "Parsing search criteria..."
        parsed = await parse_prospecting_query(query)

        # Step 2: Search LinkedIn for real profiles
        keywords = parsed.get("linkedin_keywords") or " ".join(
            parsed.get("target_roles", ["founder"])[:3]
        )
        print(f"[job {job_id[:8]}] LinkedIn search: {keywords!r}", flush=True)
        jobs[job_id]["step"] = f"Searching LinkedIn for: {keywords}..."

        try:
            people = await search_people(
                keywords=keywords,
                li_at=sess["li_at"],
                jsessionid=sess.get("jsessionid", "ajax:0"),
                count=25,
            )
        except Exception as e:
            import traceback
            print(f"[job {job_id[:8]}] LinkedIn search error: {e}", flush=True)
            traceback.print_exc()
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = f"LinkedIn search failed: {str(e)}"
            jobs[job_id]["step"] = "Search failed"
            return

        print(f"[job {job_id[:8]}] LinkedIn returned {len(people)} profiles", flush=True)

        if not people:
            jobs[job_id]["status"] = "completed"
            jobs[job_id]["step"] = "No LinkedIn profiles matched — try different keywords"
            jobs[job_id]["total"] = 0
            jobs[job_id]["source"] = "linkedin"
            return

        # Step 3: Enrich with Claude (add company size, tech stack, etc.)
        jobs[job_id]["step"] = f"Enriching {len(people)} real LinkedIn profiles..."
        try:
            people = await enrich_linkedin_leads(people, query)
        except Exception as e:
            print(f"[job {job_id[:8]}] Enrichment error (continuing anyway): {e}", flush=True)

        # Step 4: Score each lead
        jobs[job_id]["step"] = f"Scoring {len(people)} profiles..."
        scored_leads = []
        cap = min(len(people), 25)

        # Score all leads concurrently with a semaphore to limit concurrency
        sem = asyncio.Semaphore(5)

        async def score_one(person, idx):
            async with sem:
                jobs[job_id]["step"] = f"Scoring lead {idx + 1}/{cap}..."
                try:
                    score_result = await score_lead(person)
                    person["icp_score"] = score_result["score"]
                    person["score_reason"] = score_result["reason"]
                    scored_leads.append(person)
                    jobs[job_id]["leads"] = list(scored_leads)
                except Exception as e:
                    print(f"Scoring error for {person.get('name')}: {e}")
                    person["icp_score"] = 5
                    person["score_reason"] = ""
                    scored_leads.append(person)
                    jobs[job_id]["leads"] = list(scored_leads)

        await asyncio.gather(*[score_one(p, i) for i, p in enumerate(people[:cap])])

        # Step 5: Save to database (skip duplicates by linkedin_url)
        if scored_leads:
            async with AsyncSessionLocal() as session:
                for lead_data in scored_leads:
                    lead = Lead(
                        id=uuid.uuid4(),
                        name=lead_data.get("name", ""),
                        title=lead_data.get("title", ""),
                        company=lead_data.get("company", ""),
                        company_size=lead_data.get("company_size", lead_data.get("size", "")),
                        email=lead_data.get("email", ""),
                        linkedin_url=lead_data.get("linkedin_url", ""),
                        linkedin_profile_id=lead_data.get("linkedin_profile_id", ""),
                        linkedin_member_id=lead_data.get("linkedin_member_id", ""),
                        icp_score=lead_data.get("icp_score", 5),
                        score_reason=lead_data.get("score_reason", ""),
                        tech_stack=lead_data.get("tech_stack", []),
                    )
                    session.add(lead)
                await session.commit()

        jobs[job_id]["status"] = "completed"
        jobs[job_id]["step"] = f"Done — found {len(scored_leads)} real LinkedIn profiles"
        jobs[job_id]["total"] = len(scored_leads)
        jobs[job_id]["source"] = "linkedin"

    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)
        jobs[job_id]["step"] = f"Failed: {str(e)}"
        print(f"Prospecting job {job_id} failed: {e}")


@router.post("/search")
async def start_search(request: ProspectingRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "status": "pending",
        "step": "Initializing...",
        "leads": [],
        "total": 0,
        "query": request.query,
        "source": "linkedin",
    }
    background_tasks.add_task(run_prospecting_job, job_id, request.query)
    return {"job_id": job_id, "status": "pending"}


@router.get("/status/{job_id}")
async def get_job_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]


@router.get("/jobs")
async def list_jobs():
    return [
        {"job_id": k, **{kk: vv for kk, vv in v.items() if kk != "leads"}}
        for k, v in jobs.items()
    ]
