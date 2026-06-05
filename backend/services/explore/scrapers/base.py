"""Normalized company row from any scraper."""
from typing import Any, Dict, List, Optional
import re
from urllib.parse import urlparse


def domain_key(website: str, company_name: str) -> str:
    if website:
        try:
            host = urlparse(website if "://" in website else f"https://{website}").netloc.lower()
            host = host.removeprefix("www.")
            if host:
                return host
        except Exception:
            pass
    return re.sub(r"[^a-z0-9]", "", (company_name or "").lower())


def normalize_row(
    company_name: str,
    source: str,
    *,
    website: str = "",
    industry: str = "",
    headcount: str = "",
    location: str = "",
    signals: Optional[List[str]] = None,
    raw_url: str = "",
    raw_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    name = (company_name or "").strip()
    if not name or len(name) < 2:
        return {}
    sig = list(signals or [])
    rd = dict(raw_data or {})
    rd.setdefault("signals", sig)
    if raw_url:
        rd["raw_url"] = raw_url[:500]
    return {
        "company_name": name[:255],
        "website": (website or "").strip()[:500],
        "industry": (industry or "").strip()[:255],
        "headcount": str(headcount or "").strip()[:50],
        "location": (location or "").strip()[:255],
        "source": source,
        "signals": sig,
        "raw_url": (raw_url or "")[:500],
        "raw_data": rd,
    }


def merge_rows_by_domain(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate by domain; merge signals and prefer richer fields."""
    by_key: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        if not r.get("company_name"):
            continue
        key = domain_key(r.get("website", ""), r["company_name"])
        if not key:
            key = re.sub(r"[^a-z0-9]", "", r["company_name"].lower())
        if key in by_key:
            ex = by_key[key]
            ex_signals = set(ex.get("signals") or [])
            ex_signals.update(r.get("signals") or [])
            ex["signals"] = sorted(ex_signals)
            ex["raw_data"] = {
                **(ex.get("raw_data") or {}),
                "sources": sorted(
                    set((ex.get("raw_data") or {}).get("sources", [ex.get("source")]))
                    | {r.get("source")}
                    - {None}
                ),
            }
            for field in ("website", "industry", "headcount", "location", "raw_url"):
                if not ex.get(field) and r.get(field):
                    ex[field] = r[field]
            if (r.get("source") or "") != ex.get("source"):
                ex["source"] = f"{ex.get('source')}+{r.get('source')}"
        else:
            rd = dict(r.get("raw_data") or {})
            rd["sources"] = [r.get("source")]
            by_key[key] = {**r, "raw_data": rd}
    return list(by_key.values())


def dedupe_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return merge_rows_by_domain(rows)


def parse_headcount_number(headcount: str) -> Optional[int]:
    if not headcount:
        return None
    m = re.search(r"(\d+)", headcount.replace(",", ""))
    return int(m.group(1)) if m else None
