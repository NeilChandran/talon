"""
Apify integration for LinkedIn prospecting.

Two-step pipeline:
  1. Google Search Scraper  → finds LinkedIn profile URLs for a keyword
  2. LinkedIn Profile Scraper → enriches those profiles with full data

Actor IDs (configurable via env vars):
  APIFY_GOOGLE_ACTOR  — default: apify/google-search-scraper (official, free tier available)
  APIFY_PROFILE_ACTOR — default: dev_fusion/Linkedin-Profile-Scraper (No Cookies, $10/1000)
"""
import asyncio
import json
import os
import re
from typing import Any, Dict, List, Optional

import httpx

APIFY_TOKEN = os.getenv("APIFY_API_TOKEN", "")
APIFY_BASE = "https://api.apify.com/v2"

# Official Apify Google Search Scraper — finds LinkedIn URLs via Google
# NOTE: Apify REST API requires ~ not / as separator in actor IDs
GOOGLE_ACTOR = os.getenv("APIFY_GOOGLE_ACTOR", "apify~google-search-scraper")

# LinkedIn Profile Scraper — enriches profiles (No Cookies required)
# Actor ID from: console.apify.com/actors/2SyF0bVxmgGr8IVCZ
PROFILE_ACTOR = os.getenv("APIFY_PROFILE_ACTOR", "dev_fusion~Linkedin-Profile-Scraper")


# ──────────────────────────────────────────────────────────────────────────────
# Core Apify API helpers
# ──────────────────────────────────────────────────────────────────────────────

async def _start_run(actor_id: str, input_data: Dict[str, Any]) -> Optional[str]:
    """Start an Apify actor run and return the run ID."""
    async with httpx.AsyncClient(timeout=30) as c:
        resp = await c.post(
            f"{APIFY_BASE}/acts/{actor_id}/runs",
            params={"token": APIFY_TOKEN},
            json=input_data,
        )
    if resp.status_code not in (200, 201):
        print(f"[apify] start {actor_id} failed: HTTP {resp.status_code} — {resp.text[:300]}", flush=True)
        return None
    data = resp.json().get("data", {})
    run_id = data.get("id")
    print(f"[apify] run started: {run_id} ({actor_id})", flush=True)
    return run_id


async def _wait_for_run(actor_id: str, run_id: str, timeout_s: int = 180) -> Optional[str]:
    """Poll until the run finishes. Returns datasetId on success, None on failure."""
    deadline = asyncio.get_event_loop().time() + timeout_s
    async with httpx.AsyncClient(timeout=15) as c:
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(4)
            r = await c.get(
                f"{APIFY_BASE}/acts/{actor_id}/runs/{run_id}",
                params={"token": APIFY_TOKEN},
            )
            if r.status_code != 200:
                continue
            run = r.json().get("data", {})
            status = run.get("status", "")
            print(f"[apify] run {run_id[:8]} status={status}", flush=True)
            if status == "SUCCEEDED":
                return run.get("defaultDatasetId")
            if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                print(f"[apify] run {run_id[:8]} ended with {status}", flush=True)
                return None
    print(f"[apify] run {run_id[:8]} timed out after {timeout_s}s", flush=True)
    return None


async def _get_dataset_items(dataset_id: str) -> List[Dict]:
    """Fetch all items from an Apify dataset."""
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(
            f"{APIFY_BASE}/datasets/{dataset_id}/items",
            params={"token": APIFY_TOKEN, "format": "json", "clean": "true"},
        )
    if r.status_code != 200:
        print(f"[apify] dataset fetch failed: HTTP {r.status_code}", flush=True)
        return []
    data = r.json()
    return data if isinstance(data, list) else []


async def _run_actor(actor_id: str, input_data: Dict, timeout_s: int = 180) -> List[Dict]:
    """Start an actor, wait for it, return its dataset items."""
    run_id = await _start_run(actor_id, input_data)
    if not run_id:
        return []
    dataset_id = await _wait_for_run(actor_id, run_id, timeout_s)
    if not dataset_id:
        return []
    items = await _get_dataset_items(dataset_id)
    print(f"[apify] {actor_id} returned {len(items)} items", flush=True)
    return items


# ──────────────────────────────────────────────────────────────────────────────
# Step 1: Google Search → LinkedIn profile URLs
# ──────────────────────────────────────────────────────────────────────────────

def _extract_linkedin_urls_from_google(items: List[Dict]) -> List[str]:
    """Extract linkedin.com/in/ URLs from Google Search Scraper results."""
    urls: List[str] = []
    seen: set = set()

    for item in items:
        # organicResults is a list of search results in each item
        for result in item.get("organicResults", []):
            url = result.get("url", "")
            if "linkedin.com/in/" in url:
                # Normalize URL
                clean = url.split("?")[0].rstrip("/")
                if clean not in seen:
                    seen.add(clean)
                    urls.append(clean)

        # Also check top-level url field (some scraper versions)
        url = item.get("url", "")
        if "linkedin.com/in/" in url:
            clean = url.split("?")[0].rstrip("/")
            if clean not in seen:
                seen.add(clean)
                urls.append(clean)

    return urls


def _parse_google_snippet(result: Dict) -> Optional[Dict[str, Any]]:
    """
    Parse a Google result snippet for a LinkedIn profile into a lead dict.
    Title format: "FirstName LastName - Title at Company | LinkedIn"
    Description: contains brief bio.
    """
    url = result.get("url", "")
    if "linkedin.com/in/" not in url:
        return None

    title = result.get("title", "")
    description = result.get("description") or result.get("snippet", "")

    # Extract public ID
    match = re.search(r"linkedin\.com/in/([^/?&#\s]+)", url)
    if not match:
        return None
    public_id = match.group(1)

    # Parse title: "Name - Headline | LinkedIn" or "Name | LinkedIn"
    name = ""
    role_hint = ""
    if " - " in title:
        parts = title.split(" - ", 1)
        name = parts[0].strip()
        role_hint = parts[1].replace("| LinkedIn", "").strip()
    elif " | LinkedIn" in title:
        name = title.replace("| LinkedIn", "").strip()
    else:
        name = title.strip()

    # Skip generic/empty names
    if not name or name.lower() in ("linkedin", "sign up | linkedin", ""):
        return None

    # Parse title/company from role_hint: "Title at Company"
    job_title, company = "", ""
    if " at " in role_hint:
        parts = role_hint.split(" at ", 1)
        job_title = parts[0].strip()
        company = parts[1].strip()
    else:
        job_title = role_hint

    clean_url = url.split("?")[0].rstrip("/")

    return {
        "name": name,
        "title": job_title,
        "company": company,
        "company_size": "",
        "email": "",
        "linkedin_url": clean_url,
        "linkedin_public_id": public_id,
        "linkedin_profile_id": "",
        "linkedin_member_id": "",
        "tech_stack": [],
        "description": description,
    }


async def _google_search_linkedin(keywords: str, count: int) -> List[Dict[str, Any]]:
    """
    Use Apify's Google Search Scraper to find LinkedIn profiles for `keywords`.
    Returns a list of basic lead dicts (name, title, company, linkedin_url).
    """
    # Search Google for LinkedIn profiles matching the keyword
    queries = [
        f'site:linkedin.com/in/ "{keywords}"',
        f'site:linkedin.com/in/ {keywords}',
    ]

    pages_needed = max(1, (count + 9) // 10)  # 10 results per page

    input_data = {
        "queries": "\n".join(queries),
        "maxPagesPerQuery": pages_needed,
        "resultsPerPage": 10,
        "countryCode": "us",
        "languageCode": "en",
        "mobileResults": False,
        "saveHtml": False,
        "saveHtmlToKeyValueStore": False,
    }

    items = await _run_actor(GOOGLE_ACTOR, input_data, timeout_s=60)
    if not items:
        return []

    results: List[Dict[str, Any]] = []
    seen_ids: set = set()

    for item in items:
        for result in item.get("organicResults", []):
            lead = _parse_google_snippet(result)
            if lead and lead["linkedin_public_id"] not in seen_ids:
                seen_ids.add(lead["linkedin_public_id"])
                results.append(lead)
                if len(results) >= count:
                    break
        if len(results) >= count:
            break

    print(f"[apify] Google search found {len(results)} LinkedIn profiles for '{keywords}'", flush=True)
    return results


# ──────────────────────────────────────────────────────────────────────────────
# Step 2: LinkedIn Profile Scraper → enrich profiles
# ──────────────────────────────────────────────────────────────────────────────

def _normalize_profile(item: Dict) -> Optional[Dict[str, Any]]:
    """Normalize a LinkedIn Profile Scraper result into our lead format."""
    name = (
        item.get("fullName") or
        item.get("name") or
        f"{item.get('firstName', '')} {item.get('lastName', '')}".strip()
    )
    if not name:
        return None

    url = (
        item.get("linkedinUrl") or
        item.get("url") or
        item.get("profileUrl") or
        ""
    )
    public_id = ""
    if "/in/" in url:
        public_id = url.split("/in/")[-1].strip("/").split("?")[0]

    # Current position
    positions = item.get("positions") or item.get("experience") or []
    job_title, company, company_size = "", "", ""
    if positions:
        pos = positions[0] if isinstance(positions, list) else {}
        job_title = pos.get("title") or pos.get("jobTitle") or ""
        company_data = pos.get("company") or pos.get("companyName") or {}
        if isinstance(company_data, dict):
            company = company_data.get("name") or ""
            sz = company_data.get("employeeCount") or company_data.get("staffCount") or 0
            company_size = str(sz) if sz else ""
        else:
            company = str(company_data)
    if not job_title:
        job_title = item.get("headline") or item.get("title") or ""
    if not company:
        company = item.get("company") or item.get("companyName") or ""

    return {
        "name": name,
        "title": job_title,
        "company": company,
        "company_size": company_size,
        "email": item.get("email") or "",
        "linkedin_url": url or f"https://linkedin.com/in/{public_id}" if public_id else "",
        "linkedin_public_id": public_id,
        "linkedin_profile_id": item.get("profileId") or "",
        "linkedin_member_id": item.get("memberId") or str(item.get("id") or ""),
        "tech_stack": [],
        "description": item.get("summary") or item.get("about") or "",
    }


async def _enrich_profiles_apify(linkedin_urls: List[str]) -> List[Dict[str, Any]]:
    """
    Use the LinkedIn Profile Scraper (No Cookies) to get full data for a list of profile URLs.
    """
    if not linkedin_urls:
        return []

    print(f"[apify] enriching {len(linkedin_urls)} profiles via {PROFILE_ACTOR}...", flush=True)

    input_data = {
        "profileUrls": linkedin_urls,
        "proxyConfig": {"useApifyProxy": True},
    }

    items = await _run_actor(PROFILE_ACTOR, input_data, timeout_s=180)
    if not items:
        return []

    results = []
    for item in items:
        lead = _normalize_profile(item)
        if lead:
            results.append(lead)

    print(f"[apify] profile scraper returned {len(results)} enriched profiles", flush=True)
    return results


# ──────────────────────────────────────────────────────────────────────────────
# Main public function
# ──────────────────────────────────────────────────────────────────────────────

async def search_people_apify(keywords: str, count: int = 25) -> List[Dict[str, Any]]:
    """
    Full Apify pipeline: Google Search → LinkedIn Profile Scraper.

    1. Google Search finds LinkedIn profile URLs for the keyword.
    2. LinkedIn Profile Scraper enriches those profiles with full data.

    Returns a list of lead dicts, or [] if Apify token not set / search fails.
    """
    if not APIFY_TOKEN:
        print("[apify] APIFY_API_TOKEN not set — skipping Apify search", flush=True)
        return []

    print(f"[apify] Starting Apify pipeline for '{keywords}' (target: {count} profiles)...", flush=True)

    # Step 1: Google Search → get LinkedIn profile URLs + basic data
    basic_leads = await _google_search_linkedin(keywords, count=count)

    if not basic_leads:
        print(f"[apify] Google search returned 0 results for '{keywords}'", flush=True)
        return []

    # Step 2: Enrich with full profile data (optional — expensive if many profiles)
    # Only enrich if PROFILE_ACTOR is set and we want rich data.
    urls = [l["linkedin_url"] for l in basic_leads if l.get("linkedin_url")]

    enriched_map: Dict[str, Dict] = {}
    if APIFY_TOKEN and urls:
        try:
            enriched = await _enrich_profiles_apify(urls[:count])
            for e in enriched:
                pid = e.get("linkedin_public_id", "")
                if pid:
                    enriched_map[pid] = e
        except Exception as e:
            print(f"[apify] profile enrichment error (using basic data): {e}", flush=True)

    # Merge: prefer enriched data, fall back to Google snippet data
    results: List[Dict[str, Any]] = []
    for lead in basic_leads:
        pid = lead.get("linkedin_public_id", "")
        if pid and pid in enriched_map:
            enriched_lead = enriched_map[pid]
            # Keep fields from enriched, fall back to basic for missing ones
            merged = {**lead, **{k: v for k, v in enriched_lead.items() if v}}
            results.append(merged)
        else:
            results.append(lead)

    print(f"[apify] pipeline complete: {len(results)} profiles ready", flush=True)
    return results[:count]
