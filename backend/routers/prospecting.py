"""
Prospecting router — real Playwright scrapers (no Apify in the primary path).
Uses the same explore pipeline: LinkedIn, Google Maps, Crunchbase, Jobs, News, Shopify.
"""
import asyncio
import uuid
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, BackgroundTasks, HTTPException

from store import get_store
from schemas import ProspectingRequest
from services.claude_service import parse_prospecting_query, score_lead, enrich_linkedin_leads
from services.explore.icp_parser import parse_icp_prompt
from services.explore.scrapers.linkedin import scrape_linkedin
from services.explore.scrapers.google_maps import scrape_google_maps
from services.explore.scrapers.crunchbase import scrape_crunchbase
from services.explore.scrapers.jobs import scrape_jobs
from services.explore.scrapers.news import scrape_news
from services.linkedin_service import load_session, search_people, _relaunch_browser_for_search_sync, _pw_executor

router = APIRouter()

jobs: Dict[str, Any] = {}

SCRAPER_LABELS = {
    "linkedin": "LinkedIn",
    "google_maps": "Google Maps",
    "crunchbase": "Crunchbase",
    "jobs": "Job boards",
    "news": "News",
}

PARALLEL_SCRAPERS = {
    "google_maps": scrape_google_maps,
    "crunchbase": scrape_crunchbase,
    "jobs": scrape_jobs,
    "news": scrape_news,
}


def _init_job(job_id: str, query: str, source: str = "playwright") -> None:
    jobs[job_id] = {
        "status": "pending",
        "step": "Parsing your ICP...",
        "leads": [],
        "total": 0,
        "query": query,
        "source": source,
        "scraper_status": {k: "pending" for k in list(SCRAPER_LABELS.keys())},
    }


async def _find_people_via_playwright(parsed: Dict[str, Any], query: str, job_id: str) -> List[Dict[str, Any]]:
    """LinkedIn people search — CDP browser first, then explore linkedin scraper fallback."""
    raw_kw = parsed.get("linkedin_keywords") or parsed.get("keywords") or " ".join(
        (parsed.get("target_roles") or ["founder"])[:2]
    )
    keywords = " ".join(str(raw_kw).split()[:4])
    jobs[job_id]["step"] = f"LinkedIn Playwright: searching for «{keywords}»..."
    jobs[job_id]["scraper_status"]["linkedin"] = "running"

    people: List[Dict] = []
    sess = load_session()

    if sess:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(_pw_executor, _relaunch_browser_for_search_sync)
        _known = {"li_at", "jsessionid", "bcookie", "bscookie", "name", "headline", "linkedin_url"}
        extra = {k: v for k, v in sess.items() if k not in _known and isinstance(v, str) and v}
        try:
            people = await search_people(
                keywords=keywords,
                li_at=sess["li_at"],
                jsessionid=sess.get("jsessionid", "ajax:0"),
                count=25,
                bcookie=sess.get("bcookie", ""),
                bscookie=sess.get("bscookie", ""),
                extra_cookies=extra or None,
            ) or []
        except Exception as e:
            print(f"[prospecting] CDP people search: {e}", flush=True)

    if not people:
        jobs[job_id]["step"] = f"LinkedIn Playwright: company search + people fallback..."
        try:
            companies = await scrape_linkedin(parsed)
            # scrape_linkedin includes people-search fallback internally
            from services.explore.scrapers.linkedin import _people_search_companies_fallback

            people = await _people_search_companies_fallback(parsed, keywords)
            if not people and companies:
                jobs[job_id]["step"] = (
                    f"Found {len(companies)} companies — connect LinkedIn in Settings for people profiles"
                )
        except Exception as e:
            print(f"[prospecting] linkedin scraper: {e}", flush=True)

    jobs[job_id]["scraper_status"]["linkedin"] = f"done ({len(people)} people)" if people else "done (0)"
    return people


async def _run_parallel_scrapers(parsed: Dict[str, Any], job_id: str) -> Dict[str, List[Dict]]:
    """Run company scrapers in parallel; update job status per scraper."""

    async def one(name: str, fn):
        label = SCRAPER_LABELS.get(name, name)
        jobs[job_id]["scraper_status"][name] = "running"
        jobs[job_id]["step"] = f"Running {label} scraper..."
        try:
            rows = await fn(parsed)
            jobs[job_id]["scraper_status"][name] = f"done ({len(rows)} rows)"
            return name, rows
        except Exception as e:
            jobs[job_id]["scraper_status"][name] = f"failed"
            print(f"[prospecting] {name}: {e}", flush=True)
            return name, []

    results = await asyncio.gather(
        *[one(n, fn) for n, fn in PARALLEL_SCRAPERS.items()],
        return_exceptions=True,
    )
    out: Dict[str, List[Dict]] = {}
    for r in results:
        if isinstance(r, tuple):
            out[r[0]] = r[1]
    return out


async def _score_and_save(job_id: str, people: List[Dict], query: str, persist: bool = True) -> List[Dict]:
    if not people:
        return []

    jobs[job_id]["step"] = f"Enriching {len(people)} profiles with AI..."
    try:
        people = await enrich_linkedin_leads(people, query)
    except Exception as e:
        print(f"[prospecting] enrich: {e}", flush=True)

    jobs[job_id]["step"] = f"Scoring {len(people)} leads..."
    scored: List[Dict] = []
    sem = asyncio.Semaphore(5)
    cap = min(len(people), 25)

    async def score_one(person: Dict, idx: int):
        async with sem:
            jobs[job_id]["step"] = f"Scoring lead {idx + 1}/{cap}..."
            try:
                result = await score_lead(person)
                person["icp_score"] = result["score"]
                person["score_reason"] = result["reason"]
            except Exception:
                person["icp_score"] = 5
                person["score_reason"] = ""
            scored.append(person)
            jobs[job_id]["leads"] = list(scored)

    await asyncio.gather(*[score_one(p, i) for i, p in enumerate(people[:cap])])

    if persist:
        db = get_store()
        now = datetime.utcnow().isoformat()
        rows = []
        for lead_data in scored:
            rows.append({
                "id": str(uuid.uuid4()),
                "name": lead_data.get("name", ""),
                "title": lead_data.get("title", ""),
                "company": lead_data.get("company", ""),
                "company_size": lead_data.get("company_size", lead_data.get("size", "")),
                "email": lead_data.get("email", ""),
                "linkedin_url": lead_data.get("linkedin_url", ""),
                "linkedin_profile_id": lead_data.get("linkedin_profile_id", ""),
                "linkedin_member_id": lead_data.get("linkedin_member_id", ""),
                "icp_score": lead_data.get("icp_score", 5),
                "score_reason": lead_data.get("score_reason", ""),
                "tech_stack": lead_data.get("tech_stack", []),
                "created_at": now,
                "updated_at": now,
            })
        if rows:
            await db.insert_many("leads", rows)

    return scored


async def run_prospecting_job(job_id: str, query: str):
    jobs[job_id]["status"] = "running"

    try:
        if not load_session():
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = "LinkedIn not connected — go to Settings → Sign in with LinkedIn."
            jobs[job_id]["step"] = "LinkedIn required"
            return

        jobs[job_id]["step"] = "Parsing ICP with AI..."
        parsed = await parse_icp_prompt(query)
        # Merge prospecting-specific linkedin keywords
        legacy = await parse_prospecting_query(query)
        if legacy.get("linkedin_keywords"):
            parsed["linkedin_keywords"] = legacy["linkedin_keywords"]

        # Company scrapers in parallel (real Playwright — not Apify)
        await _run_parallel_scrapers(parsed, job_id)

        # People via LinkedIn Playwright
        people = await _find_people_via_playwright(parsed, query, job_id)

        if not people:
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = (
                "No LinkedIn profiles found. Try broader terms or reconnect LinkedIn in Settings."
            )
            jobs[job_id]["step"] = "No people found"
            return

        scored = await _score_and_save(job_id, people, query)
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["step"] = f"Done — {len(scored)} leads from Playwright scrapers"
        jobs[job_id]["total"] = len(scored)
        jobs[job_id]["source"] = "playwright"

    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)
        jobs[job_id]["step"] = f"Failed: {str(e)[:120]}"
        print(f"[prospecting] job {job_id[:8]} failed: {e}", flush=True)


async def run_signal_job(job_id: str, mode: str):
    """Signal modes using Playwright scrapers instead of Apify."""
    jobs[job_id]["status"] = "running"
    labels = {"funded": "Funded startups", "jobs": "Hiring companies", "competitor": "Competitor users"}
    label = labels.get(mode, mode)

    try:
        if not load_session():
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = "Connect LinkedIn in Settings first."
            return

        jobs[job_id]["step"] = f"Parsing signal: {label}..."
        base_queries = {
            "funded": "recently funded Series A B startup founders CEOs",
            "jobs": "companies hiring VP Sales SDR account executive",
            "competitor": "Superhuman SaneBox Shortwave email tool users founders",
        }
        query = base_queries.get(mode, label)
        parsed = await parse_icp_prompt(query)
        parsed["signals"] = list(parsed.get("signals") or []) + [mode]

        if mode == "funded":
            jobs[job_id]["step"] = "Running Crunchbase + News Playwright scrapers..."
            jobs[job_id]["scraper_status"] = {"crunchbase": "running", "news": "running", "linkedin": "pending"}
            await asyncio.gather(scrape_crunchbase(parsed), scrape_news(parsed))
            jobs[job_id]["scraper_status"]["crunchbase"] = "done"
            jobs[job_id]["scraper_status"]["news"] = "done"
        elif mode == "jobs":
            jobs[job_id]["step"] = "Running Job boards Playwright scraper (LinkedIn + Indeed)..."
            jobs[job_id]["scraper_status"] = {"jobs": "running", "linkedin": "pending"}
            await scrape_jobs(parsed)
            jobs[job_id]["scraper_status"]["jobs"] = "done"
        else:
            jobs[job_id]["step"] = "Running Google Maps + LinkedIn Playwright..."
            jobs[job_id]["scraper_status"] = {"google_maps": "running", "linkedin": "pending"}
            await scrape_google_maps(parsed)
            jobs[job_id]["scraper_status"]["google_maps"] = "done"

        people = await _find_people_via_playwright(parsed, query, job_id)
        if not people:
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = f"No profiles found for {label}. Try LinkedIn Search mode."
            return

        scored = await _score_and_save(job_id, people, query)
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["step"] = f"Done — {len(scored)} {label} leads (Playwright)"
        jobs[job_id]["total"] = len(scored)
        jobs[job_id]["source"] = "playwright"

    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)
        jobs[job_id]["step"] = str(e)[:120]


@router.post("/search")
async def start_search(request: ProspectingRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    _init_job(job_id, request.query, "playwright")
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


@router.post("/signal")
async def start_signal_search(mode: str, background_tasks: BackgroundTasks):
    valid = ("funded", "jobs", "competitor")
    if mode not in valid:
        raise HTTPException(status_code=400, detail=f"Invalid mode. Must be one of: {valid}")

    job_id = str(uuid.uuid4())
    _init_job(job_id, f"Signal: {mode}", "playwright")
    jobs[job_id]["mode"] = mode
    background_tasks.add_task(run_signal_job, job_id, mode)
    return {"job_id": job_id, "status": "pending", "mode": mode}
