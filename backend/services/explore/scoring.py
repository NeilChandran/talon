"""Score rows 0-100 against parsed ICP."""
from typing import Any, Dict, List, Optional

from services.explore.scrapers.base import parse_headcount_number


def score_row(row: Dict[str, Any], parsed: Dict[str, Any], icp_prompt: str) -> int:
    score = 50
    reasons: List[str] = []

    # Headcount fit
    min_h = parsed.get("company_size_min")
    max_h = parsed.get("company_size_max")
    hc = parse_headcount_number(row.get("headcount", ""))
    if min_h is not None or max_h is not None:
        if hc is not None:
            if min_h is not None and hc >= int(min_h):
                score += 12
                reasons.append("size_min")
            elif min_h is not None:
                score -= 15
            if max_h is not None and hc <= int(max_h):
                score += 12
                reasons.append("size_max")
            elif max_h is not None and hc > int(max_h) * 2:
                score -= 10
        else:
            score -= 5

    # Location
    loc_icp = (parsed.get("location") or "").lower()
    loc_row = (row.get("location") or "").lower()
    if loc_icp and loc_row:
        if loc_icp in loc_row or loc_row in loc_icp or any(
            w in loc_row for w in loc_icp.split() if len(w) > 3
        ):
            score += 10
            reasons.append("location")
    elif loc_icp and not loc_row:
        score -= 3

    # Industry
    ind_icp = parsed.get("industry", "")
    if isinstance(ind_icp, list):
        ind_icp = " ".join(ind_icp)
    ind_row = (row.get("industry") or row.get("company_name") or "").lower()
    if ind_icp and any(w in ind_row for w in str(ind_icp).lower().split() if len(w) > 3):
        score += 10
        reasons.append("industry")

    # Tech stack in raw / enrichment
    tech = [t.lower() for t in (parsed.get("tech_stack") or [])]
    signals = row.get("signals") or (row.get("raw_data") or {}).get("signals") or []
    blob = " ".join(
        str(row.get(k, "")) for k in ("website", "industry", "company_name")
    ).lower() + str(row.get("raw_data", "")).lower() + " ".join(signals).lower()
    enrich = row.get("enrichment") or {}
    if isinstance(enrich, dict):
        blob += " ".join(str(v.get("value", v) if isinstance(v, dict) else v) for v in enrich.values()).lower()
    for t in tech:
        if t in blob:
            score += 8
            reasons.append(f"tech:{t}")

    # Source quality weights
    source = row.get("source", "")
    if source in ("linkedin", "crunchbase"):
        score += 5
    if source == "jobs" and "hiring" in (parsed.get("signals") or []):
        score += 8

    # Prompt keyword overlap
    prompt_words = [w.lower() for w in icp_prompt.split() if len(w) > 4]
    name_blob = (row.get("company_name", "") + " " + blob).lower()
    hits = sum(1 for w in prompt_words[:8] if w in name_blob)
    score += min(15, hits * 3)

    return max(0, min(100, score))


def apply_filter_rules(
    row: Dict[str, Any],
    rules: List[Dict[str, Any]],
) -> bool:
    """Return True if row passes all rules (should be visible)."""
    if not rules:
        return True
    hc = parse_headcount_number(row.get("headcount", ""))
    enrich = row.get("enrichment") or {}

    for rule in rules:
        field = rule.get("field", "")
        op = rule.get("op", "contains")
        value = rule.get("value", "")

        if field == "headcount_min":
            if hc is None or hc < int(value):
                return False
        elif field == "headcount_max":
            if hc is not None and hc > int(value):
                return False
        elif field == "must_use":
            blob = " ".join(
                str(row.get("website", "")) + str(row.get("industry", ""))
            ).lower()
            if isinstance(enrich, dict):
                for v in enrich.values():
                    blob += " " + str(v.get("value", v) if isinstance(v, dict) else v).lower()
            if str(value).lower() not in blob:
                return False
        elif field == "fit_score_min":
            if (row.get("fit_score") or 0) < int(value):
                return False
        elif field == "source":
            if op == "eq" and row.get("source") != value:
                return False
        elif field == "contains":
            blob = (row.get("company_name", "") + " " + row.get("industry", "")).lower()
            if str(value).lower() not in blob:
                return False
    return True
