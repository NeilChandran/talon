"""
SCRAPER 5 — Shopify detector
GET {website}/admin/auth/login — 302 to myshopify.com = Shopify.
Also checks page source for window.Shopify.
"""
import asyncio
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from services.explore.scrapers.base import domain_key, normalize_row


def _normalize_website(url: str) -> Optional[str]:
    if not url or not url.strip():
        return None
    u = url.strip()
    if "linkedin.com" in u:
        return None
    if not u.startswith("http"):
        u = "https://" + u.lstrip("/")
    try:
        parsed = urlparse(u)
        if not parsed.netloc:
            return None
        return f"{parsed.scheme}://{parsed.netloc}"
    except Exception:
        return None


async def _check_shopify(domain_url: str) -> Dict[str, Any]:
    """Return {is_shopify, method, detail}."""
    base = _normalize_website(domain_url)
    if not base:
        return {"is_shopify": False}

    admin_url = base.rstrip("/") + "/admin/auth/login"
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; TalonBot/1.0)",
        "Accept": "text/html",
    }

    try:
        async with httpx.AsyncClient(
            timeout=12,
            follow_redirects=False,
            headers=headers,
        ) as client:
            r = await client.get(admin_url)
            loc = (r.headers.get("location") or "").lower()
            if "myshopify.com" in loc or "shopify.com" in loc:
                return {"is_shopify": True, "method": "admin_redirect", "detail": loc[:200]}

            if r.status_code in (301, 302, 303, 307, 308) and "shopify" in loc:
                return {"is_shopify": True, "method": "redirect", "detail": loc[:200]}

            # Follow one hop for HTML check
            r2 = await client.get(base, follow_redirects=True)
            html = (r2.text or "")[:80_000].lower()
            if "window.shopify" in html or "cdn.shopify.com" in html or "shopify.theme" in html:
                return {"is_shopify": True, "method": "page_source", "detail": "shopify assets in HTML"}
    except Exception as e:
        return {"is_shopify": False, "error": str(e)[:80]}

    return {"is_shopify": False}


async def scrape_shopify_for_websites(
    websites: List[Dict[str, str]],
    parsed: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Check known company websites from other scrapers.
    websites: [{company_name, website, industry?, location?}]
    """
    tech = [t.lower() for t in (parsed.get("tech_stack") or [])]
    icp_wants_shopify = "shopify" in tech or any(
        w in str(parsed.get("keywords", "")).lower() for w in ("shopify", "ecommerce", "dtc")
    )

    rows: List[Dict[str, Any]] = []
    seen_domains: set = set()

    # Limit concurrent checks
    sem = asyncio.Semaphore(8)

    async def check_one(item: Dict[str, str]) -> Optional[Dict[str, Any]]:
        async with sem:
            site = item.get("website", "")
            dom = domain_key(site, item.get("company_name", ""))
            if not dom or dom in seen_domains:
                return None
            result = await _check_shopify(site)
            if not result.get("is_shopify"):
                if not icp_wants_shopify:
                    return None
                return None
            seen_domains.add(dom)
            return normalize_row(
                item.get("company_name", dom),
                "shopify",
                website=_normalize_website(site) or site,
                industry=item.get("industry", ""),
                location=item.get("location", ""),
                signals=["uses_shopify", f"detected_via:{result.get('method', 'unknown')}"],
                raw_url=site,
                raw_data=result,
            )

    tasks = [check_one(w) for w in websites if w.get("website") or w.get("company_name")]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in results:
        if isinstance(r, dict) and r:
            rows.append(r)

    print(f"[scraper:shopify] confirmed {len(rows)} Shopify stores", flush=True)
    return rows


async def scrape_shopify(parsed: Dict[str, Any], websites: Optional[List[Dict[str, str]]] = None) -> List[Dict[str, Any]]:
    """Called from orchestrator phase 2 with accumulated websites."""
    if not websites:
        return []
    try:
        return await scrape_shopify_for_websites(websites, parsed)
    except Exception as e:
        print(f"[scraper:shopify] failed: {e}", flush=True)
        return []
