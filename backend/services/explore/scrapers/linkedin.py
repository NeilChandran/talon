"""
SCRAPER 1 — LinkedIn Companies (Playwright)
https://www.linkedin.com/search/results/companies/
Uses stored session cookies from Settings / browser login.
"""
import asyncio
import urllib.parse
from typing import Any, Dict, List

from pathlib import Path

from services.explore.playwright_browser import linkedin_cookies_for_playwright, run_playwright
from services.explore.scrapers.base import normalize_row

PERSISTENT_PROFILE_DIR = Path.home() / ".talon-chrome-profile"


def _build_company_keywords(parsed: Dict[str, Any]) -> str:
    parts: List[str] = []
    kw = parsed.get("keywords") or parsed.get("linkedin_keywords") or ""
    if kw:
        parts.append(str(kw))
    industry = parsed.get("industry")
    if industry:
        parts.append(industry[0] if isinstance(industry, list) else str(industry))
    location = parsed.get("location")
    if location:
        parts.append(str(location))
    q = " ".join(parts).strip()
    return " ".join(q.split()[:8]) if q else "B2B SaaS"


def _scrape_linkedin_companies_sync(parsed: Dict[str, Any]) -> List[Dict[str, Any]]:
    cookies = linkedin_cookies_for_playwright()
    if not cookies:
        print("[scraper:linkedin] no LinkedIn session — connect in Settings", flush=True)
        return []

    keywords = _build_company_keywords(parsed)
    url = (
        "https://www.linkedin.com/search/results/companies/?"
        + urllib.parse.urlencode({"keywords": keywords, "origin": "GLOBAL_SEARCH_HEADER"})
    )
    print(f"[scraper:linkedin] Playwright company search: {keywords!r}", flush=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[scraper:linkedin] playwright not installed — pip install playwright && playwright install chromium", flush=True)
        return []

    rows: List[Dict[str, Any]] = []

    with sync_playwright() as p:
        ua = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        browser = None
        use_profile = PERSISTENT_PROFILE_DIR.exists() and any(PERSISTENT_PROFILE_DIR.iterdir())

        if use_profile:
            print("[scraper:linkedin] using persistent Chrome profile", flush=True)
            try:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(PERSISTENT_PROFILE_DIR),
                    headless=True,
                    channel="chrome",
                    args=["--disable-blink-features=AutomationControlled"],
                    user_agent=ua,
                    locale="en-US",
                )
            except Exception:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(PERSISTENT_PROFILE_DIR),
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"],
                    user_agent=ua,
                    locale="en-US",
                )
            page = context.pages[0] if context.pages else context.new_page()
        else:
            print("[scraper:linkedin] using cookie session (connect LinkedIn in Settings)", flush=True)
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(user_agent=ua, locale="en-US")
            context.add_cookies(cookies)
            page = context.new_page()

        page.set_default_timeout(45_000)

        try:
            # Warm session on feed before company search (avoids redirect loops with cookie auth)
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(2000)
            if "login" in page.url or "authwall" in page.url:
                print("[scraper:linkedin] not logged in — Sign in with LinkedIn in Settings", flush=True)
                context.close()
                if browser:
                    browser.close()
                return []

            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(3000)

            if "login" in page.url or "checkpoint" in page.url or "authwall" in page.url:
                print("[scraper:linkedin] login wall — use Settings → Sign in with LinkedIn", flush=True)
                context.close()
                if browser:
                    browser.close()
                return []

            # Scroll results feed to load more company cards
            for _ in range(6):
                page.evaluate(
                    """() => {
                    const main = document.querySelector('.scaffold-finite-scroll__content')
                      || document.querySelector('main');
                    if (main) main.scrollTop = main.scrollHeight;
                    window.scrollTo(0, document.body.scrollHeight);
                }"""
                )
                page.wait_for_timeout(1200)

            extracted = page.evaluate(
                """() => {
                const results = [];
                const cards = document.querySelectorAll(
                  'li.reusable-search__result-container, div[data-chameleon-result-urn], li.org-search-result__list-item'
                );
                const seen = new Set();
                for (const card of cards) {
                  const titleA = card.querySelector(
                    '.entity-result__title-text a, a.app-aware-link[href*="/company/"]'
                  );
                  if (!titleA) continue;
                  const name = (titleA.querySelector('span[aria-hidden="true"]') || titleA).innerText?.trim();
                  if (!name || name.length < 2 || seen.has(name)) continue;
                  seen.add(name);
                  const href = titleA.href || '';
                  const primary = card.querySelector('.entity-result__primary-subtitle')?.innerText?.trim() || '';
                  const secondary = card.querySelector('.entity-result__secondary-subtitle')?.innerText?.trim() || '';
                  const snippet = card.querySelector('.entity-result__summary')?.innerText?.trim() || '';
                  let industry = '';
                  let headcount = '';
                  let location = '';
                  if (primary) {
                    const parts = primary.split('•').map(s => s.trim());
                    industry = parts[0] || primary;
                    if (parts[1]) headcount = parts[1];
                  }
                  if (secondary) location = secondary;
                  results.push({ name, href, industry, headcount, location, snippet });
                  if (results.length >= 35) break;
                }
                return results;
            }"""
            )

            for item in extracted or []:
                name = (item.get("name") or "").strip()
                if not name:
                    continue
                href = item.get("href") or ""
                website = ""
                if "/company/" in href:
                    slug = href.split("/company/")[-1].split("/")[0].split("?")[0]
                    if slug:
                        website = f"https://www.linkedin.com/company/{slug}"

                row = normalize_row(
                    name,
                    "linkedin",
                    website=website,
                    industry=item.get("industry", ""),
                    headcount=item.get("headcount", ""),
                    location=item.get("location", parsed.get("location", "") if isinstance(parsed.get("location"), str) else ""),
                    signals=["linkedin_company_search"],
                    raw_url=href,
                    raw_data={
                        "snippet": item.get("snippet", ""),
                        "search_keywords": keywords,
                    },
                )
                if row:
                    rows.append(row)

            print(f"[scraper:linkedin] extracted {len(rows)} companies", flush=True)
        except Exception as e:
            print(f"[scraper:linkedin] Playwright error: {e}", flush=True)
        finally:
            try:
                context.close()
            except Exception:
                pass
            if browser:
                browser.close()

    return rows


def _scrape_via_cdp_sync(parsed: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Use existing Talon Chrome (CDP :9223) if user logged in via Settings."""
    import json
    import urllib.parse
    import urllib.request

    try:
        tabs = json.loads(urllib.request.urlopen("http://127.0.0.1:9223/json", timeout=2).read())
    except Exception:
        return []

    if not tabs:
        return []

    keywords = _build_company_keywords(parsed)
    url = (
        "https://www.linkedin.com/search/results/companies/?"
        + urllib.parse.urlencode({"keywords": keywords, "origin": "GLOBAL_SEARCH_HEADER"})
    )

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return []

    rows: List[Dict[str, Any]] = []
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp("http://127.0.0.1:9223")
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(3000)
            for _ in range(5):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1000)
            extracted = page.evaluate(
                """() => {
                const results = [];
                const cards = document.querySelectorAll('li.reusable-search__result-container, div[data-chameleon-result-urn]');
                for (const card of cards) {
                  const titleA = card.querySelector('.entity-result__title-text a, a[href*="/company/"]');
                  if (!titleA) continue;
                  const name = (titleA.querySelector('span[aria-hidden="true"]') || titleA).innerText?.trim();
                  if (!name) continue;
                  results.push({
                    name,
                    href: titleA.href || '',
                    industry: card.querySelector('.entity-result__primary-subtitle')?.innerText?.trim() || '',
                    headcount: '',
                    location: card.querySelector('.entity-result__secondary-subtitle')?.innerText?.trim() || ''
                  });
                  if (results.length >= 30) break;
                }
                return results;
            }"""
            )
            page.close()
            for item in extracted or []:
                href = item.get("href") or ""
                row = normalize_row(
                    item.get("name", ""),
                    "linkedin",
                    website=href.split("?")[0] if "/company/" in href else "",
                    industry=item.get("industry", ""),
                    headcount=item.get("headcount", ""),
                    location=item.get("location", ""),
                    signals=["linkedin_company_search"],
                    raw_url=href,
                )
                if row:
                    rows.append(row)
            print(f"[scraper:linkedin] CDP extracted {len(rows)} companies", flush=True)
        except Exception as e:
            print(f"[scraper:linkedin] CDP error: {e}", flush=True)
    return rows


async def _people_search_companies_fallback(parsed: Dict[str, Any], keywords: str) -> List[Dict[str, Any]]:
    """Derive company rows from LinkedIn people search (CDP Voyager — Playwright browser)."""
    from services.linkedin_service import load_session, search_people, _relaunch_browser_for_search_sync, _pw_executor

    people: List[Dict] = []
    li_kw = " ".join(str(parsed.get("linkedin_keywords") or keywords).split()[:3])

    sess = load_session()
    if sess:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(_pw_executor, _relaunch_browser_for_search_sync)
        _known = {"li_at", "jsessionid", "bcookie", "bscookie", "name", "headline", "linkedin_url"}
        extra = {k: v for k, v in sess.items() if k not in _known and isinstance(v, str) and v}
        people = await search_people(
            keywords=li_kw,
            li_at=sess["li_at"],
            jsessionid=sess.get("jsessionid", "ajax:0"),
            count=25,
            bcookie=sess.get("bcookie", ""),
            bscookie=sess.get("bscookie", ""),
            extra_cookies=extra or None,
        ) or []

    by_company: Dict[str, Dict[str, Any]] = {}
    for p in people:
        company = (p.get("company") or "").strip()
        if not company:
            continue
        if company not in by_company:
            by_company[company] = normalize_row(
                company,
                "linkedin",
                industry=parsed.get("industry", "") if isinstance(parsed.get("industry"), str) else "",
                headcount=p.get("company_size", ""),
                location=parsed.get("location", "") if isinstance(parsed.get("location"), str) else "",
                signals=["linkedin_people_search"],
                raw_data={"sample_person": p.get("name"), "title": p.get("title")},
            )
    out = [r for r in by_company.values() if r]
    if out:
        print(f"[scraper:linkedin] people-search fallback: {len(out)} companies", flush=True)
    return out


async def scrape_linkedin(parsed: Dict[str, Any]) -> List[Dict[str, Any]]:
    keywords = _build_company_keywords(parsed)

    # 1) Playwright company search via CDP (real browser — best for /search/results/companies/)
    try:
        sess = load_session()
        if sess:
            from services.linkedin_service import _relaunch_browser_for_search_sync, _pw_executor

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(_pw_executor, _relaunch_browser_for_search_sync)
        rows = await run_playwright(lambda: _scrape_via_cdp_sync(parsed))
        if rows:
            return rows
    except Exception as e:
        print(f"[scraper:linkedin] cdp company search: {e}", flush=True)

    # 2) Voyager API company endpoint (works when httpx session is accepted)
    try:
        from services.explore.scrapers.linkedin_voyager import search_companies_voyager

        rows = await search_companies_voyager(keywords)
        if rows:
            return rows
    except Exception as e:
        print(f"[scraper:linkedin] voyager: {e}", flush=True)

    # 3) Standalone Playwright (persistent profile or cookies)
    try:
        rows = await run_playwright(lambda: _scrape_linkedin_companies_sync(parsed))
        if rows:
            return rows
    except Exception as e:
        print(f"[scraper:linkedin] playwright: {e}", flush=True)

    # 4) People search → aggregate by company (proven CDP path)
    return await _people_search_companies_fallback(parsed, keywords)
