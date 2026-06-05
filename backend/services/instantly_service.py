"""Push leads to Instantly.ai email campaigns."""
import os
from typing import Any, Dict, List, Optional

import httpx

INSTANTLY_API_KEY = os.getenv("INSTANTLY_API_KEY", "")
INSTANTLY_BASE = "https://api.instantly.ai/api/v1"
DRY_RUN = os.getenv("TALON_DRY_RUN", "").lower() in ("1", "true", "yes")


async def add_lead_to_campaign(
    email: str,
    first_name: str,
    last_name: str,
    campaign_id: str,
    company: str = "",
    custom_variables: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST lead to Instantly campaign."""
    if not email:
        return {"ok": False, "error": "No email"}
    if DRY_RUN:
        return {"ok": True, "dry_run": True, "email": email}
    if not INSTANTLY_API_KEY or not campaign_id:
        return {"ok": False, "error": "Instantly API key or campaign ID not configured"}

    payload: Dict[str, Any] = {
        "api_key": INSTANTLY_API_KEY,
        "campaign_id": campaign_id,
        "email": email,
        "first_name": first_name or "",
        "last_name": last_name or "",
        "company_name": company or "",
    }
    if custom_variables:
        payload["custom_variables"] = custom_variables

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(f"{INSTANTLY_BASE}/lead/add", json=payload)
            if resp.status_code in (200, 201):
                return {"ok": True, "data": resp.json()}
            return {"ok": False, "error": resp.text[:300], "status": resp.status_code}
        except Exception as e:
            return {"ok": False, "error": str(e)}


async def push_leads_batch(
    leads: List[Dict[str, Any]],
    campaign_id: str,
) -> Dict[str, Any]:
    """Push multiple leads; returns counts."""
    pushed = 0
    skipped = 0
    errors: List[str] = []
    for lead in leads:
        email = lead.get("email") or ""
        if not email:
            skipped += 1
            continue
        r = await add_lead_to_campaign(
            email=email,
            first_name=lead.get("first_name", ""),
            last_name=lead.get("last_name", ""),
            campaign_id=campaign_id,
            company=lead.get("company", ""),
        )
        if r.get("ok"):
            pushed += 1
        else:
            errors.append(r.get("error", "unknown")[:80])
    return {"pushed": pushed, "skipped": skipped, "errors": errors[:5], "dry_run": DRY_RUN}
