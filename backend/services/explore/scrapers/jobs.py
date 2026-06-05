"""
SCRAPER 4 — Job boards (Playwright)
LinkedIn Jobs + Indeed — companies actively hiring for target roles.
"""
import json
import urllib.parse
import urllib.request
from typing import Any, Dict, List

from services.explore.playwright_browser import linkedin_cookies_for_playwright, pick_user_agent, run_playwright
from services.explore.scrapers.base import normalize_row


def _hiring_role(parsed: Dict[str, Any]) -> str:
    roles = parsed.get("target_roles") or []
    if roles:
        return str(roles[0])
    kw = str(parsed.get("keywords", "")).lower()
    for phrase in ("sales engineer", "account executive", "sdr", "sales", "cto", "marketing"):
        if phrase in kw:
            return phrase
    return "sales"


def _scrape_linkedin_jobs_sync(role: str, location: str) -> List[Dict[str, Any]]:
    q = urllib.parse.quote(role)
    loc = urllib.parse.quote(location or "United States")
    url = f"https://www.linkedin.com/jobs/search/?keywords={q}&location={loc}"
    print(f"[scraper:jobs] LinkedIn jobs: {role!r} @ {location!r}", flush=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return []

    rows: List[Dict[str, Any]] = []
    cookies = linkedin_cookies_for_playwright()

    with sync_playwright() as p:
        browser_owned = None
        used_cdp = False
        try:
            tabs = json.loads(urllib.request.urlopen("http://127.0.0.1:9223/json", timeout=2).read())
            if tabs:
                browser = p.chromium.connect_over_cdp("http://127.0.0.1:9223")
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                page = context.new_page()
                used_cdp = True
            else:
                raise OSError("no cdp")
        except Exception:
            browser_owned = p.chromium.launch(
                headless=True, args=["--disable-blink-features=AutomationControlled"]
            )
            context = browser_owned.new_context(user_agent=pick_user_agent(), locale="en-US")
            if cookies:
                context.add_cookies(cookies)
            page = context.new_page()

        page.set_default_timeout(50_000)
        try:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

            if "login" not in page.url and "authwall" not in page.url:
                for _ in range(5):
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(1000)

                extracted = page.evaluate(
                    """(role) => {
                    const out = [];
                    const seen = new Set();
                    const cards = document.querySelectorAll(
                      'li.jobs-search-results__list-item, div.job-card-container, div.base-card'
                    );
                    for (const card of cards) {
                      const companyEl = card.querySelector(
                        '.artdeco-entity-lockup__subtitle, .base-search-card__subtitle, h4'
                      );
                      const titleEl = card.querySelector('h3, .base-search-card__title');
                      const linkEl = card.querySelector('a[href*="/jobs/view/"]');
                      const company = companyEl?.innerText?.trim();
                      const title = titleEl?.innerText?.trim();
                      const jobUrl = linkEl?.href || '';
                      const date = card.querySelector('time')?.innerText?.trim() || '';
                      if (!company || seen.has(company)) continue;
                      seen.add(company);
                      out.push({ company, title, jobUrl, date });
                      if (out.length >= 25) break;
                    }
                    return out;
                }""",
                    role,
                )

                for item in extracted or []:
                    row = normalize_row(
                        item.get("company", ""),
                        "jobs",
                        signals=[f"hiring: {(item.get('title') or role)[:60]}", "linkedin_jobs"],
                        raw_url=item.get("jobUrl", ""),
                        raw_data={
                            "job_title": item.get("title", ""),
                            "posted": item.get("date", ""),
                            "board": "linkedin",
                        },
                    )
                    if row:
                        rows.append(row)
                print(f"[scraper:jobs] LinkedIn: {len(rows)} companies", flush=True)
            else:
                print("[scraper:jobs] LinkedIn jobs login wall", flush=True)
        except Exception as e:
            print(f"[scraper:jobs] LinkedIn error: {e}", flush=True)
        finally:
            page.close()
            if browser_owned:
                browser_owned.close()

    return rows


def _scrape_indeed_sync(role: str, location: str) -> List[Dict[str, Any]]:
    q = urllib.parse.quote(role)
    loc = urllib.parse.quote(location or "")
    url = f"https://www.indeed.com/jobs?q={q}&l={loc}" if loc else f"https://www.indeed.com/jobs?q={q}"
    print(f"[scraper:jobs] Indeed: {url[:90]}", flush=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return []

    rows: List[Dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(user_agent=pick_user_agent(), locale="en-US")
        page = context.new_page()
        page.set_default_timeout(45_000)

        try:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)

            extracted = page.evaluate(
                """(role) => {
                const out = [];
                const seen = new Set();
                const cards = document.querySelectorAll('div.job_seen_beacon, td.resultContent');
                for (const card of cards) {
                  const company = card.querySelector(
                    '[data-testid="company-name"], .companyName'
                  )?.innerText?.trim();
                  const title = card.querySelector('h2.jobTitle span, .jobTitle')?.innerText?.trim();
                  const link = card.querySelector('a[href*="/viewjob"], a[jk]')?.href || '';
                  const date = card.querySelector('.date')?.innerText?.trim() || '';
                  if (!company || seen.has(company)) continue;
                  seen.add(company);
                  out.push({ company, title, link, date });
                  if (out.length >= 20) break;
                }
                return out;
            }""",
                role,
            )

            for item in extracted or []:
                job_url = item.get("link", "")
                if job_url and not job_url.startswith("http"):
                    job_url = "https://www.indeed.com" + job_url
                row = normalize_row(
                    item.get("company", ""),
                    "jobs",
                    signals=[f"hiring: {(item.get('title') or role)[:60]}", "indeed"],
                    raw_url=job_url,
                    raw_data={
                        "job_title": item.get("title", ""),
                        "posted": item.get("date", ""),
                        "board": "indeed",
                    },
                )
                if row:
                    rows.append(row)
            print(f"[scraper:jobs] Indeed: {len(rows)} companies", flush=True)
        except Exception as e:
            print(f"[scraper:jobs] Indeed error: {e}", flush=True)
        finally:
            browser.close()

    return rows


def _scrape_jobs_sync(parsed: Dict[str, Any]) -> List[Dict[str, Any]]:
    role = _hiring_role(parsed)
    location = str(parsed.get("location", "United States"))
    by_company: Dict[str, Dict[str, Any]] = {}

    for batch in (_scrape_linkedin_jobs_sync(role, location), _scrape_indeed_sync(role, location)):
        for r in batch:
            key = r.get("company_name", "").lower()
            if not key:
                continue
            if key in by_company:
                ex = by_company[key]
                ex["signals"] = sorted(set(ex.get("signals", []) + r.get("signals", [])))
            else:
                by_company[key] = r

    return list(by_company.values())


async def scrape_jobs(parsed: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        return await run_playwright(lambda: _scrape_jobs_sync(parsed))
    except Exception as e:
        print(f"[scraper:jobs] failed: {e}", flush=True)
        return []
