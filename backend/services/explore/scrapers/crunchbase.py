"""
SCRAPER 3 — Crunchbase (Playwright)
https://www.crunchbase.com/discover/organization.companies
"""
import re
import urllib.parse
from typing import Any, Dict, List

from services.explore.playwright_browser import new_stealth_context, pick_user_agent, run_playwright
from services.explore.scrapers.base import normalize_row


def _build_crunchbase_url(parsed: Dict[str, Any]) -> str:
    industry = parsed.get("industry", "software")
    if isinstance(industry, list):
        industry = industry[0] if industry else "software"
    location = (parsed.get("location") or "united-states").lower().replace(" ", "-")
    kw = parsed.get("keywords") or industry
    slug = re.sub(r"[^a-z0-9]+", "-", str(kw).lower()).strip("-")[:40] or "software"

    min_e = parsed.get("company_size_min")
    max_e = parsed.get("company_size_max")
    # Discover hub + search fallback
    base = "https://www.crunchbase.com/discover/organization.companies"
    params = []
    if location and location != "united-states":
        params.append(f"location={urllib.parse.quote(location)}")
    if slug:
        params.append(f"q={urllib.parse.quote(str(kw)[:80])}")
    if min_e and max_e:
        params.append(f"employees={min_e}-{max_e}")
    elif min_e:
        params.append(f"employees={min_e}+")

    if params:
        return base + "?" + "&".join(params)
    return f"https://www.crunchbase.com/search/organizations/{urllib.parse.quote(str(kw)[:60])}"


def _scrape_crunchbase_sync(parsed: Dict[str, Any]) -> List[Dict[str, Any]]:
    url = _build_crunchbase_url(parsed)
    print(f"[scraper:crunchbase] Playwright: {url[:100]}", flush=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return []

    rows: List[Dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent=pick_user_agent(),
            locale="en-US",
            viewport={"width": 1400, "height": 900},
        )
        page = context.new_page()
        page.set_default_timeout(50_000)

        try:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(3500)

            if "login" in page.url or page.locator("text=Log In").first.is_visible(timeout=2000):
                # Public search page fallback
                kw = parsed.get("keywords") or parsed.get("industry", "saas")
                fallback = f"https://www.crunchbase.com/search/organizations/{urllib.parse.quote(str(kw)[:50])}"
                print("[scraper:crunchbase] login wall — trying public search URL", flush=True)
                page.goto(fallback, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)

            for _ in range(4):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1200)

            extracted = page.evaluate(
                """() => {
                const out = [];
                const seen = new Set();
                const cards = document.querySelectorAll(
                  'grid-row entity-search-result, search-result, a[href*="/organization/"]'
                );
                const links = document.querySelectorAll('a[href*="/organization/"]');
                for (const a of links) {
                  const href = a.href || '';
                  if (!href.includes('/organization/') || href.includes('/organization/people')) continue;
                  const name = (a.querySelector('span') || a).innerText?.trim();
                  if (!name || name.length < 2 || seen.has(name)) continue;
                  seen.add(name);
                  const card = a.closest('grid-row, search-result, row-card, div[class*="result"]') || a.parentElement;
                  const text = card ? card.innerText : '';
                  const lines = text.split('\\n').map(s => s.trim()).filter(Boolean);
                  let funding = '';
                  let employees = '';
                  let location = '';
                  for (const line of lines) {
                    if (/\\$|funding|raised|series/i.test(line)) funding = line;
                    if (/employees?|\\d+-\\d+ employees/i.test(line)) employees = line;
                    if (/,/.test(line) && line.length < 60 && !line.includes('$')) location = line;
                  }
                  out.push({ name, href, funding, employees, location, snippet: lines.slice(0, 4).join(' | ') });
                  if (out.length >= 25) break;
                }
                return out;
            }"""
            )

            for item in extracted or []:
                href = item.get("href") or ""
                website = ""
                if href.startswith("http"):
                    website = href
                row = normalize_row(
                    item.get("name", ""),
                    "crunchbase",
                    website=website,
                    industry=str(parsed.get("industry", ""))[:255] if isinstance(parsed.get("industry"), str) else "",
                    headcount=item.get("employees", ""),
                    location=item.get("location", ""),
                    signals=["crunchbase"] + (["funding"] if item.get("funding") else []),
                    raw_url=href,
                    raw_data={
                        "funding": item.get("funding", ""),
                        "snippet": item.get("snippet", ""),
                    },
                )
                if row:
                    rows.append(row)

            print(f"[scraper:crunchbase] extracted {len(rows)} orgs", flush=True)
        except Exception as e:
            print(f"[scraper:crunchbase] error: {e}", flush=True)
        finally:
            browser.close()

    return rows


async def scrape_crunchbase(parsed: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        return await run_playwright(lambda: _scrape_crunchbase_sync(parsed))
    except Exception as e:
        print(f"[scraper:crunchbase] failed: {e}", flush=True)
        return []
