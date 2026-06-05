"""
SCRAPER 6 — News and funding signals (Playwright)
TechCrunch search + BusinessWire search.
"""
import re
import urllib.parse
from typing import Any, Dict, List

from services.explore.playwright_browser import pick_user_agent, run_playwright
from services.explore.scrapers.base import normalize_row


def _search_terms(parsed: Dict[str, Any]) -> str:
    industry = parsed.get("industry", "startup")
    if isinstance(industry, list):
        industry = industry[0] if industry else "startup"
    return str(parsed.get("keywords") or f"{industry} funding startup")[:80]


def _company_from_headline(headline: str) -> str:
    h = headline.strip()
    # "Acme raises $10M" -> Acme
    m = re.match(r"^([A-Za-z0-9][A-Za-z0-9 '&.-]{1,50}?)\s+(raises|raised|announces|launches|secures|closes|gets)", h, re.I)
    if m:
        return m.group(1).strip()
    # "Acme Inc. announces..."
    m2 = re.match(r"^([A-Za-z0-9][^–—|-]{2,40}?)(?:\s+(Inc|LLC|Corp|Ltd))?\s+(announces|raises)", h, re.I)
    if m2:
        return m2.group(1).strip()
    return h.split("–")[0].split("|")[0].strip()[:60]


def _scrape_techcrunch_sync(query: str) -> List[Dict[str, Any]]:
    url = f"https://techcrunch.com/search/{urllib.parse.quote(query)}"
    print(f"[scraper:news] TechCrunch: {query!r}", flush=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return []

    rows: List[Dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(user_agent=pick_user_agent(), locale="en-US")
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(2500)
            extracted = page.evaluate(
                """() => {
                const out = [];
                const seen = new Set();
                const articles = document.querySelectorAll(
                  'article.post-block, li.wp-block-post, div.post-block, a[href*="/20"]'
                );
                const links = document.querySelectorAll('a[href*="techcrunch.com/20"]');
                for (const a of links) {
                  const headline = a.innerText?.trim() || a.getAttribute('title') || '';
                  const href = a.href || '';
                  if (!headline || headline.length < 12 || seen.has(headline)) continue;
                  if (/subscribe|newsletter|events/i.test(headline)) continue;
                  seen.add(headline);
                  const time = a.closest('article, li')?.querySelector('time')?.innerText?.trim() || '';
                  out.push({ headline, href, date: time, source: 'techcrunch' });
                  if (out.length >= 15) break;
                }
                return out;
            }"""
            )
            for item in extracted or []:
                company = _company_from_headline(item.get("headline", ""))
                if len(company) < 2:
                    continue
                signal_type = "press"
                hl = item.get("headline", "").lower()
                if "fund" in hl or "raise" in hl or "series" in hl or "$" in hl:
                    signal_type = "funding"
                elif "ceo" in hl or "appoint" in hl:
                    signal_type = "leadership"
                row = normalize_row(
                    company,
                    "news",
                    signals=[f"news:{signal_type}", "techcrunch"],
                    raw_url=item.get("href", ""),
                    raw_data={
                        "headline": item.get("headline", ""),
                        "date": item.get("date", ""),
                        "signal_type": signal_type,
                    },
                )
                if row:
                    rows.append(row)
            print(f"[scraper:news] TechCrunch: {len(rows)} signals", flush=True)
        except Exception as e:
            print(f"[scraper:news] TechCrunch error: {e}", flush=True)
        finally:
            browser.close()

    return rows


def _scrape_businesswire_sync(query: str) -> List[Dict[str, Any]]:
    url = f"https://www.businesswire.com/newsroom?keywords={urllib.parse.quote(query)}"
    print(f"[scraper:news] BusinessWire: {query!r}", flush=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return []

    rows: List[Dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(user_agent=pick_user_agent(), locale="en-US")
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(2500)
            extracted = page.evaluate(
                """() => {
                const out = [];
                const seen = new Set();
                const items = document.querySelectorAll(
                  'div[class*="newsItem"], li[class*="bwlist"], a[href*="/news/home"]'
                );
                const links = document.querySelectorAll('a[href*="/news/home"]');
                for (const a of links) {
                  const headline = a.innerText?.trim() || '';
                  const href = a.href || '';
                  if (!headline || headline.length < 15 || seen.has(headline)) continue;
                  seen.add(headline);
                  const date = a.closest('div, li')?.querySelector('time, span.date')?.innerText?.trim() || '';
                  out.push({ headline, href, date, source: 'businesswire' });
                  if (out.length >= 12) break;
                }
                return out;
            }"""
            )
            for item in extracted or []:
                company = _company_from_headline(item.get("headline", ""))
                if len(company) < 2:
                    continue
                row = normalize_row(
                    company,
                    "news",
                    signals=["news:press_release", "businesswire"],
                    raw_url=item.get("href", ""),
                    raw_data={
                        "headline": item.get("headline", ""),
                        "date": item.get("date", ""),
                        "signal_type": "press_release",
                    },
                )
                if row:
                    rows.append(row)
            print(f"[scraper:news] BusinessWire: {len(rows)} signals", flush=True)
        except Exception as e:
            print(f"[scraper:news] BusinessWire error: {e}", flush=True)
        finally:
            browser.close()

    return rows


def _scrape_news_sync(parsed: Dict[str, Any]) -> List[Dict[str, Any]]:
    query = _search_terms(parsed)
    by_name: Dict[str, Dict[str, Any]] = {}

    for batch in (_scrape_techcrunch_sync(query), _scrape_businesswire_sync(query)):
        for r in batch:
            key = r.get("company_name", "").lower()
            if not key:
                continue
            if key in by_name:
                ex = by_name[key]
                ex["signals"] = sorted(set(ex.get("signals", []) + r.get("signals", [])))
                if r.get("raw_url"):
                    ex["raw_data"]["extra_headline"] = r["raw_data"].get("headline", "")
            else:
                by_name[key] = r

    return list(by_name.values())


async def scrape_news(parsed: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        return await run_playwright(lambda: _scrape_news_sync(parsed))
    except Exception as e:
        print(f"[scraper:news] failed: {e}", flush=True)
        return []
