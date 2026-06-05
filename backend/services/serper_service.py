"""Google search via Serper.dev — parallel query execution."""
import asyncio
import os
import re
from typing import List, Set

import httpx

SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
SERPER_URL = "https://google.serper.dev/search"

LINKEDIN_IN_RE = re.compile(r"https?://(?:[\w.]+)?linkedin\.com/in/[\w%-]+", re.I)


async def serper_search(query: str, num: int = 10) -> List[str]:
    """Return organic result URLs for one query."""
    if not SERPER_API_KEY:
        return []
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(
                SERPER_URL,
                headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
                json={"q": query, "num": num},
            )
            if resp.status_code != 200:
                print(f"[serper] {query[:40]}: HTTP {resp.status_code}", flush=True)
                return []
            data = resp.json()
            urls: List[str] = []
            for item in data.get("organic", []) or []:
                link = item.get("link") or ""
                if link:
                    urls.append(link)
            return urls
        except Exception as e:
            print(f"[serper] {e}", flush=True)
            return []


async def run_parallel_searches(queries: List[str], num_per_query: int = 10) -> List[str]:
    """Run all queries in parallel; return deduplicated URLs."""
    if not queries:
        return []
    results = await asyncio.gather(*[serper_search(q, num_per_query) for q in queries])
    seen: Set[str] = set()
    out: List[str] = []
    for batch in results:
        for url in batch:
            norm = url.rstrip("/").split("#")[0]
            if norm not in seen:
                seen.add(norm)
                out.append(url)
    return out


def extract_linkedin_urls(urls: List[str]) -> List[str]:
    """Extract unique normalized LinkedIn /in/ profile URLs."""
    seen: Set[str] = set()
    out: List[str] = []
    for url in urls:
        for m in LINKEDIN_IN_RE.finditer(url):
            u = m.group(0).split("?")[0].rstrip("/")
            key = u.lower()
            if key not in seen:
                seen.add(key)
                out.append(u)
    return out
