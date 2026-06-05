"""Run parallel scrapers and stream rows into session."""
import asyncio
import uuid
from datetime import datetime
from typing import Any, Dict, List

from services.explore.icp_parser import parse_icp_prompt
from services.explore.scoring import score_row
from services.explore.scrapers.base import domain_key, merge_rows_by_domain
from services.explore.scrapers.linkedin import scrape_linkedin
from services.explore.scrapers.google_maps import scrape_google_maps
from services.explore.scrapers.crunchbase import scrape_crunchbase
from services.explore.scrapers.jobs import scrape_jobs
from services.explore.scrapers.news import scrape_news
from services.explore.scrapers.shopify import scrape_shopify
from store import Record, SupabaseStore, get_store

SCRAPERS_PHASE1 = {
    "linkedin": scrape_linkedin,
    "google_maps": scrape_google_maps,
    "crunchbase": scrape_crunchbase,
    "jobs": scrape_jobs,
    "news": scrape_news,
}

ALL_SCRAPER_KEYS = list(SCRAPERS_PHASE1.keys()) + ["shopify"]

_job_state: Dict[str, Dict[str, Any]] = {}


def get_job_state(session_id: str) -> Dict[str, Any]:
    return _job_state.get(session_id, {})


async def _run_scraper(
    name: str,
    fn,
    parsed: Dict[str, Any],
    session_id: str,
    **kwargs,
) -> List[Dict[str, Any]]:
    state = _job_state.setdefault(session_id, {"scrapers": {}, "rows_added": 0, "buffer": []})
    state["scrapers"][name] = {"status": "running", "error": None, "count": 0}
    try:
        rows = await (fn(parsed, **kwargs) if kwargs else fn(parsed))
        state["scrapers"][name] = {"status": "done", "error": None, "count": len(rows)}
        state["buffer"].extend(rows)
        return rows
    except Exception as e:
        print(f"[orchestrator] {name} failed: {e}", flush=True)
        state["scrapers"][name] = {"status": "failed", "error": str(e)[:200], "count": 0}
        return []


async def _persist_rows(
    db: SupabaseStore,
    session: Record,
    rows: List[Dict[str, Any]],
    parsed: Dict[str, Any],
) -> int:
    added = 0
    existing_rows = await db.list_explore_rows(session.id)
    seen_keys = set()
    for r in existing_rows:
        seen_keys.add(domain_key(r.website or "", r.company_name or ""))

    now = datetime.utcnow().isoformat()
    payloads = []
    for data in rows:
        key = domain_key(data.get("website", ""), data.get("company_name", ""))
        if not data.get("company_name") or key in seen_keys:
            continue
        seen_keys.add(key)
        fit = score_row(data, parsed, session.icp_prompt)
        raw = dict(data.get("raw_data") or {})
        raw["signals"] = data.get("signals") or []
        if data.get("raw_url"):
            raw["raw_url"] = data["raw_url"]
        payloads.append({
            "id": str(uuid.uuid4()),
            "session_id": str(session.id),
            "company_name": data["company_name"],
            "website": data.get("website", ""),
            "industry": data.get("industry", ""),
            "headcount": data.get("headcount", ""),
            "location": data.get("location", ""),
            "source": data.get("source", ""),
            "raw_data": raw,
            "fit_score": fit,
            "enrichment": {},
            "hidden": False,
            "created_at": now,
        })
        added += 1
        sid = str(session.id)
        if sid in _job_state:
            _job_state[sid]["rows_added"] = _job_state[sid].get("rows_added", 0) + 1

    if payloads:
        await db.insert_many("explore_rows", payloads)
    return added


async def _merge_buffer_into_db(db: SupabaseStore, session: Record, parsed: Dict[str, Any], sid: str) -> None:
    merged = merge_rows_by_domain(_job_state[sid]["buffer"])
    if merged:
        await _persist_rows(db, session, merged, parsed)
    await db.update(
        "explore_sessions",
        session.id,
        {"scraper_status": dict(_job_state[sid]["scrapers"])},
    )


async def run_explore_pipeline(session_id: uuid.UUID, db: SupabaseStore) -> None:
    session = await db.select_one("explore_sessions", session_id)
    if not session:
        return

    sid = str(session_id)
    _job_state[sid] = {
        "scrapers": {k: {"status": "pending", "error": None, "count": 0} for k in ALL_SCRAPER_KEYS},
        "rows_added": 0,
        "buffer": [],
    }

    await db.update(
        "explore_sessions",
        session_id,
        {
            "status": "running",
            "scraper_status": _job_state[sid]["scrapers"],
        },
    )

    parsed = session.parsed_icp or await parse_icp_prompt(session.icp_prompt)
    if not session.parsed_icp:
        await db.update("explore_sessions", session_id, {"parsed_icp": parsed})
        session.parsed_icp = parsed

    async def run_one(name: str, fn):
        await _run_scraper(name, fn, parsed, sid)
        session_fresh = await db.select_one("explore_sessions", session_id)
        if session_fresh:
            await _merge_buffer_into_db(db, session_fresh, parsed, sid)

    await asyncio.gather(
        *[run_one(n, fn) for n, fn in SCRAPERS_PHASE1.items()],
        return_exceptions=True,
    )

    for name in SCRAPERS_PHASE1.keys():
        if _job_state[sid]["scrapers"].get(name, {}).get("status") == "pending":
            _job_state[sid]["scrapers"][name] = {
                "status": "failed",
                "error": "Unknown error",
                "count": 0,
            }

    _job_state[sid]["scrapers"]["shopify"] = {"status": "running", "error": None, "count": 0}
    session_fresh = await db.select_one("explore_sessions", session_id)
    if session_fresh:
        await db.update(
            "explore_sessions",
            session_id,
            {"scraper_status": dict(_job_state[sid]["scrapers"])},
        )

    website_batch = [
        {
            "company_name": r.get("company_name", ""),
            "website": r.get("website", ""),
            "industry": r.get("industry", ""),
            "location": r.get("location", ""),
        }
        for r in merge_rows_by_domain(_job_state[sid]["buffer"])
        if r.get("website")
    ]
    try:
        shopify_rows = await scrape_shopify(parsed, websites=website_batch)
        _job_state[sid]["scrapers"]["shopify"] = {
            "status": "done",
            "error": None,
            "count": len(shopify_rows),
        }
        _job_state[sid]["buffer"].extend(shopify_rows)
        session_fresh = await db.select_one("explore_sessions", session_id)
        if session_fresh:
            await _merge_buffer_into_db(db, session_fresh, parsed, sid)
    except Exception as e:
        print(f"[orchestrator] shopify failed: {e}", flush=True)
        _job_state[sid]["scrapers"]["shopify"] = {"status": "failed", "error": str(e)[:200], "count": 0}

    explore_rows = await db.list_explore_rows(session_id, order="created_at", desc=False)
    for row in explore_rows:
        fit = score_row(
            {
                "company_name": row.company_name,
                "website": row.website,
                "industry": row.industry,
                "headcount": row.headcount,
                "location": row.location,
                "source": row.source,
                "enrichment": row.enrichment,
                "signals": (row.raw_data or {}).get("signals", []),
            },
            parsed,
            session.icp_prompt,
        )
        await db.update("explore_rows", row.id, {"fit_score": fit})

    await db.update(
        "explore_sessions",
        session_id,
        {
            "status": "completed",
            "scraper_status": _job_state[sid]["scrapers"],
            "updated_at": datetime.utcnow().isoformat(),
        },
    )
    print(
        f"[orchestrator] session {sid[:8]} done — "
        + ", ".join(f"{k}={v['status']}({v.get('count',0)})" for k, v in _job_state[sid]["scrapers"].items()),
        flush=True,
    )
