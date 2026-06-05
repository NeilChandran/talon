"""LinkedIn company search via Voyager API (httpx + session cookies)."""
import json
import urllib.parse
from typing import Any, Dict, List, Optional

import httpx

from services.linkedin_service import (
    BASE_URL,
    _cookies,
    _extra_cookies_from_session,
    _headers,
    load_session,
)
from services.explore.scrapers.base import normalize_row


def _parse_company_from_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract company fields from various Voyager search item shapes."""
    company = item.get("company") or item.get("companyV2") or {}
    if not company and "name" in item and "entityUrn" in str(item.get("entityUrn", "")):
        company = item

    name = (
        company.get("name")
        or company.get("universalName")
        or (company.get("localizedName") if isinstance(company.get("localizedName"), str) else None)
    )
    if not name and company.get("localizedName"):
        loc_name = company["localizedName"]
        if isinstance(loc_name, dict):
            name = loc_name.get("text") or loc_name.get("value")

    if not name or not str(name).strip():
        title = item.get("title", {})
        if isinstance(title, dict):
            name = title.get("text")
        elif isinstance(title, str):
            name = title

    if not name:
        return None

    name = str(name).strip()
    universal = company.get("universalName") or ""
    url = f"https://www.linkedin.com/company/{universal}/" if universal else ""

    industry = ""
    inds = company.get("industries") or company.get("companyIndustries") or []
    if inds:
        first = inds[0]
        industry = first.get("localizedName", first) if isinstance(first, dict) else str(first)

    headcount = ""
    rng = company.get("employeeCountRange") or company.get("staffCountRange") or {}
    if isinstance(rng, dict):
        start = rng.get("start")
        end = rng.get("end")
        if start and end:
            headcount = f"{start}-{end}"
        elif start:
            headcount = str(start)

    location = ""
    hq = company.get("headquarter") or company.get("headquarters") or {}
    if isinstance(hq, dict):
        parts = [hq.get("city"), hq.get("geographicArea"), hq.get("country")]
        location = ", ".join(p for p in parts if p)

    return normalize_row(
        name,
        "linkedin",
        website=url,
        industry=industry,
        headcount=headcount,
        location=location,
        signals=["linkedin_company_search"],
        raw_url=url,
        raw_data={"voyager": True},
    )


def _walk_for_companies(obj: Any, out: List[Dict[str, Any]], seen: set, limit: int) -> None:
    if len(out) >= limit:
        return
    if isinstance(obj, dict):
        urn = str(obj.get("entityUrn", obj.get("$type", "")))
        if "company" in urn.lower() or obj.get("company") or (
            "universalName" in obj and "name" in obj
        ):
            row = _parse_company_from_item(obj)
            if row and row["company_name"].lower() not in seen:
                seen.add(row["company_name"].lower())
                out.append(row)
        for v in obj.values():
            _walk_for_companies(v, out, seen, limit)
    elif isinstance(obj, list):
        for v in obj:
            _walk_for_companies(v, out, seen, limit)


async def search_companies_voyager(keywords: str, count: int = 25) -> List[Dict[str, Any]]:
    sess = load_session()
    if not sess or not sess.get("li_at"):
        return []

    encoded_kw = urllib.parse.quote(keywords)
    paths = [
        (
            f"/voyager/api/search/dash/clusters?count={count}&origin=GLOBAL_SEARCH_HEADER&q=all"
            f"&query=(keywords:{encoded_kw},flagshipSearchIntent:SEARCH_SRP,"
            f"queryParameters:List((key:resultType,value:List(COMPANIES))),"
            f"includeFiltersInResponse:false)&start=0"
        ),
        (
            f"/voyager/api/search/blended?count={count}"
            f"&filters=List(resultType-%3ECOMPANIES)"
            f"&keywords={encoded_kw}&origin=GLOBAL_SEARCH_HEADER"
        ),
    ]

    extra = _extra_cookies_from_session(sess)
    jsessionid = sess.get("jsessionid", "ajax:0")
    rows: List[Dict[str, Any]] = []
    seen: set = set()

    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        for path in paths:
            try:
                r = await client.get(
                    f"{BASE_URL}{path}",
                    headers=_headers(jsessionid),
                    cookies=_cookies(
                        sess["li_at"],
                        jsessionid,
                        sess.get("bcookie", ""),
                        sess.get("bscookie", ""),
                        extra,
                    ),
                )
                if r.status_code != 200:
                    print(f"[scraper:linkedin:voyager] HTTP {r.status_code} for {path[:60]}", flush=True)
                    continue
                data = r.json()
                _walk_for_companies(data, rows, seen, count)
                if rows:
                    print(f"[scraper:linkedin:voyager] {len(rows)} companies via API", flush=True)
                    return rows
            except Exception as e:
                print(f"[scraper:linkedin:voyager] error: {e}", flush=True)

    return rows
