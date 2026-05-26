"""
Scraper service — uses httpx + BeautifulSoup against DuckDuckGo HTML search.
No browser / Playwright needed. Fast, reliable, no bot-detection issues.
"""

import asyncio
import random
import re
from typing import List, Dict, Any
from urllib.parse import unquote

import httpx
from bs4 import BeautifulSoup

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

TECH_STACK_SIGNALS = [
    "notion", "linear", "slack", "figma", "github", "stripe", "vercel",
    "aws", "gcp", "supabase", "postgres", "react", "next.js", "python",
    "typescript", "anthropic", "openai", "shopify", "intercom", "segment",
    "mixpanel", "amplitude", "retool", "airtable", "zapier", "gmail",
    "superhuman", "hubspot", "salesforce", "jira",
]


def _extract_ddg_url(href: str) -> str:
    """DDG wraps links as //duckduckgo.com/l/?uddg=<encoded-url>. Decode it."""
    if "uddg=" in href:
        m = re.search(r"uddg=([^&]+)", href)
        if m:
            return unquote(m.group(1))
    if href.startswith("//"):
        href = "https:" + href
    return href


async def search_ddg(query: str, max_results: int = 10) -> List[Dict[str, Any]]:
    """Search DuckDuckGo HTML endpoint — returns static results, no JS needed."""
    results = []
    url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"

    try:
        async with httpx.AsyncClient(
            headers={
                "User-Agent": random.choice(USER_AGENTS),
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml",
            },
            follow_redirects=True,
            timeout=12.0,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")

        # DDG HTML: <a class="result__a"> = title + link
        #           <a class="result__snippet"> or <span class="result__snippet"> = snippet
        for result_div in soup.find_all("div", class_="result")[:max_results * 2]:
            title_tag = result_div.find("a", class_="result__a")
            if not title_tag:
                continue

            raw_href = title_tag.get("href", "")
            real_url = _extract_ddg_url(raw_href)
            if not real_url.startswith("http"):
                continue

            snip_tag = result_div.find("a", class_="result__snippet") or \
                       result_div.find("span", class_="result__snippet")
            snippet = snip_tag.get_text(" ", strip=True) if snip_tag else ""

            results.append({
                "title": title_tag.get_text(strip=True),
                "url": real_url,
                "snippet": snippet,
            })
            if len(results) >= max_results:
                break

    except Exception as e:
        print(f"[scraper] DDG search error for '{query[:50]}': {e}")

    return results


def _parse_linkedin_title(title: str) -> Dict[str, str]:
    """
    Parse LinkedIn profile titles from DDG/Google into name/title/company.
    DDG titles typically look like: "Name - Title at Company | LinkedIn"
    """
    # Strip trailing " | LinkedIn" or "- LinkedIn"
    clean = re.sub(r'\s*[-|]\s*LinkedIn.*$', '', title, flags=re.IGNORECASE).strip()
    # Also strip " | LinkedIn" style with period
    clean = re.sub(r'\s*\.\s*$', '', clean).strip()

    # "Name - Title at/@ Company"
    m = re.match(r'^(.+?)\s*[-–]\s*(.+?)\s+(?:at|@|·)\s+(.+)$', clean, re.IGNORECASE)
    if m:
        return {
            "name": m.group(1).strip(),
            "title": m.group(2).strip(),
            "company": m.group(3).strip(),
        }

    # "Name - Title"
    m = re.match(r'^(.+?)\s*[-–]\s*(.+)$', clean)
    if m:
        return {"name": m.group(1).strip(), "title": m.group(2).strip(), "company": ""}

    return {"name": clean, "title": "", "company": ""}


def _results_to_people(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    people = []
    for result in results:
        url = result.get("url", "")
        title = result.get("title", "")
        snippet = result.get("snippet", "")

        if "linkedin.com/in/" not in url:
            continue

        parsed = _parse_linkedin_title(title)
        person: Dict[str, Any] = {
            "name": parsed["name"],
            "title": parsed["title"],
            "company": parsed["company"],
            "linkedin_url": url,
            "source_url": url,
            "tech_stack": [],
            "description": snippet,
        }

        # Fallback company from snippet
        if not person["company"] and snippet:
            m = re.search(
                r'(?:at|@)\s+([A-Z][A-Za-z0-9\s&,\.]+?)(?:\s*[-·|]|\s*\.|$)',
                snippet,
            )
            if m:
                person["company"] = m.group(1).strip()[:80]

        # Tech signals from snippet
        snippet_lower = snippet.lower()
        for tech in TECH_STACK_SIGNALS:
            if tech.lower() in snippet_lower:
                person["tech_stack"].append(tech)

        if person["name"]:
            people.append(person)

    return people


async def find_people_batch(queries: List[str]) -> List[Dict[str, Any]]:
    """
    Find LinkedIn profiles for all queries concurrently via DuckDuckGo.
    Staggered 1s apart to avoid rate-limiting.
    """
    linkedin_queries = [f"site:linkedin.com/in {q}" for q in queries]

    async def search_with_delay(q: str, delay: float) -> List[Dict[str, Any]]:
        if delay > 0:
            await asyncio.sleep(delay)
        return await search_ddg(q)

    tasks = [
        search_with_delay(q, i * 1.2)
        for i, q in enumerate(linkedin_queries)
    ]
    all_results = await asyncio.gather(*tasks, return_exceptions=True)

    seen_urls: set = set()
    people: List[Dict[str, Any]] = []
    for result_set in all_results:
        if isinstance(result_set, Exception):
            print(f"[scraper] gather error: {result_set}")
            continue
        for person in _results_to_people(result_set):
            url = person.get("linkedin_url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                people.append(person)

    return people


async def find_people_from_search(query: str) -> List[Dict[str, Any]]:
    """Legacy single-query wrapper."""
    return await find_people_batch([query])
