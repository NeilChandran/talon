"""Per-row enrichment lookups."""
import json
import re
from typing import Any, Dict, Optional

import httpx

from services.claude_service import client, MODEL

ENRICHMENT_TYPES = {
    "work_email": "Find a verified work email for a decision maker at this company",
    "phone": "Find a direct business phone number",
    "tech_stack": "List CRM, analytics, ecommerce, and marketing tools they likely use",
    "funding": "Recent funding round, amount, and date if any",
    "decision_maker_linkedin": "LinkedIn URL for CEO/founder/CTO",
}


async def enrich_cell(row: Dict[str, Any], column_type: str, icp_prompt: str) -> Dict[str, Any]:
    """Return {value, status, meta}."""
    company = row.get("company_name", "")
    website = row.get("website", "")
    hint = ENRICHMENT_TYPES.get(column_type, column_type)

    if column_type == "tech_stack" and website:
        detected = await _detect_tech_from_website(website)
        if detected:
            return {"value": ", ".join(detected), "status": "done", "meta": {"method": "http"}}

    message = client.messages.create(
        model=MODEL,
        max_tokens=512,
        messages=[
            {
                "role": "user",
                "content": f"""{hint}

Company: {company}
Website: {website}
Industry: {row.get('industry', '')}
Location: {row.get('location', '')}
ICP context: {icp_prompt[:300]}

Return JSON: {{"value": "...", "confidence": "high|medium|low"}}
For work_email use format name@domain.com or "Not found".
For phone use E.164 or US format or "Not found".
Return ONLY JSON.""",
            }
        ],
    )
    text = message.content[0].text
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}") + 1
        data = json.loads(text[start:end]) if start >= 0 else {"value": text[:200]}
    return {
        "value": str(data.get("value", "Not found")),
        "status": "done",
        "meta": {"confidence": data.get("confidence", "medium")},
    }


async def _detect_tech_from_website(url: str) -> list[str]:
    if not url.startswith("http"):
        url = "https://" + url.lstrip("/")
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as c:
            r = await c.get(url)
            html = r.text[:50000].lower()
    except Exception:
        return []
    tools = []
    patterns = {
        "Shopify": r"shopify|cdn\.shopify",
        "HubSpot": r"hubspot|hs-scripts",
        "Stripe": r"stripe\.com|js\.stripe",
        "Salesforce": r"salesforce|force\.com",
        "Google Analytics": r"google-analytics|gtag",
        "Segment": r"segment\.com|analytics\.js",
        "Intercom": r"intercom",
        "Klaviyo": r"klaviyo",
    }
    for name, pat in patterns.items():
        if re.search(pat, html):
            tools.append(name)
    return tools
