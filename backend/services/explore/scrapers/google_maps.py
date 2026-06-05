"""
SCRAPER 2 — Google Maps (Playwright)
https://www.google.com/maps/search/{query}
Extracts sidebar feed results (not map pins).
"""
import urllib.parse
from typing import Any, Dict, List

from services.explore.playwright_browser import run_playwright
from services.explore.scrapers.base import normalize_row


def _build_maps_query(parsed: Dict[str, Any]) -> str:
    industry = parsed.get("industry", "business")
    if isinstance(industry, list):
        industry = industry[0] if industry else "business"
    location = parsed.get("location", "")
    kw = parsed.get("keywords", "")
    parts = [str(industry), "companies"]
    if location:
        parts.append(str(location))
    if kw and kw not in " ".join(parts):
        parts.insert(0, str(kw)[:60])
    return " ".join(parts).strip()[:120]


def _scrape_google_maps_sync(parsed: Dict[str, Any]) -> List[Dict[str, Any]]:
    query = _build_maps_query(parsed)
    url = "https://www.google.com/maps/search/" + urllib.parse.quote(query)
    print(f"[scraper:google_maps] Playwright Maps search: {query!r}", flush=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[scraper:google_maps] playwright not installed", flush=True)
        return []

    rows: List[Dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            viewport={"width": 1400, "height": 900},
        )
        page = context.new_page()
        page.set_default_timeout(50_000)

        try:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

            # Consent dialog (EU)
            for sel in [
                'button:has-text("Accept all")',
                'button:has-text("Reject all")',
                'button[aria-label="Accept all"]',
            ]:
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible(timeout=2000):
                        btn.click()
                        page.wait_for_timeout(1000)
                        break
                except Exception:
                    pass

            feed = page.locator('div[role="feed"]')
            try:
                feed.wait_for(state="visible", timeout=15_000)
            except Exception:
                print("[scraper:google_maps] feed not found — selectors may have changed", flush=True)
                browser.close()
                return []

            # Scroll sidebar feed
            for _ in range(8):
                page.evaluate(
                    """() => {
                    const feed = document.querySelector('div[role="feed"]');
                    if (feed) feed.scrollTop = feed.scrollHeight;
                }"""
                )
                page.wait_for_timeout(1000)

            extracted = page.evaluate(
                """() => {
                const feed = document.querySelector('div[role="feed"]');
                if (!feed) return [];
                const articles = feed.querySelectorAll('div[role="article"]');
                const out = [];
                const seen = new Set();
                for (const art of articles) {
                  const nameEl = art.querySelector('.fontHeadlineSmall, [class*="fontHeadlineSmall"]');
                  const name = nameEl?.textContent?.trim();
                  if (!name || seen.has(name)) continue;
                  seen.add(name);
                  const link = art.querySelector('a[href*="/maps/place"]')?.href || '';
                  const ratingEl = art.querySelector('span[role="img"][aria-label*="stars"]');
                  const rating = ratingEl?.getAttribute('aria-label') || '';
                  const lines = Array.from(art.querySelectorAll('.fontBodyMedium, [class*="fontBodyMedium"]'))
                    .map(e => e.textContent?.trim()).filter(Boolean);
                  let category = lines[0] || '';
                  let address = '';
                  let phone = '';
                  for (const line of lines) {
                    if (/\\d{3}/.test(line) && (line.includes('(') || line.includes('-'))) phone = line;
                    else if (!address && /\\d/.test(line)) address = line;
                  }
                  const websiteBtn = art.querySelector('a[data-value="Website"], a[aria-label*="Website"]');
                  let website = websiteBtn?.href || '';
                  out.push({ name, link, rating, category, address, phone, website });
                  if (out.length >= 30) break;
                }
                return out;
            }"""
            )

            for item in extracted or []:
                name = (item.get("name") or "").strip()
                if not name:
                    continue
                website = (item.get("website") or "").strip()
                if website and "google.com" in website:
                    website = ""
                location = item.get("address") or ""
                signals = ["google_maps_listing"]
                if item.get("rating"):
                    signals.append(f"rating: {item.get('rating')[:30]}")
                if item.get("phone"):
                    signals.append("has_phone")

                row = normalize_row(
                    name,
                    "google_maps",
                    website=website,
                    industry=item.get("category", ""),
                    headcount="",
                    location=location,
                    signals=signals,
                    raw_url=item.get("link") or "",
                    raw_data={
                        "phone": item.get("phone", ""),
                        "rating": item.get("rating", ""),
                        "query": query,
                    },
                )
                if row:
                    rows.append(row)

            print(f"[scraper:google_maps] extracted {len(rows)} businesses", flush=True)
        except Exception as e:
            print(f"[scraper:google_maps] Playwright error: {e}", flush=True)
        finally:
            browser.close()

    return rows


async def scrape_google_maps(parsed: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        return await run_playwright(lambda: _scrape_google_maps_sync(parsed))
    except Exception as e:
        print(f"[scraper:google_maps] failed: {e}", flush=True)
        return []
