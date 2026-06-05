"""Parse plain-English ICP into structured search parameters."""
import json
from typing import Any, Dict

from services.claude_service import client, MODEL


async def parse_icp_prompt(prompt: str) -> Dict[str, Any]:
    message = client.messages.create(
        model=MODEL,
        max_tokens=1200,
        messages=[
            {
                "role": "user",
                "content": f"""Parse this B2B lead generation ICP into structured search parameters.

ICP: {prompt}

Return ONLY valid JSON with:
- industry: string or list of industries
- company_size_min: integer or null
- company_size_max: integer or null
- location: string (country/region/city)
- tech_stack: list of tools/technologies mentioned (e.g. Stripe, HubSpot, Shopify)
- signals: list from hiring, funding, expansion, competitor_users, ecommerce
- target_roles: list if decision-maker roles mentioned
- keywords: short search string for company discovery
- linkedin_keywords: 1-3 words for LinkedIn people search if relevant
- google_queries: list of 2-4 Google search queries to find matching companies

Example input: "B2B SaaS companies in the US with 10-50 employees using Stripe, hiring sales roles"
Example google_queries: ["B2B SaaS companies United States 10-50 employees", "SaaS startups using Stripe hiring sales"]

Return ONLY JSON.""",
            }
        ],
    )
    text = message.content[0].text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
    return {
        "industry": "B2B SaaS",
        "company_size_min": 10,
        "company_size_max": 50,
        "location": "United States",
        "tech_stack": [],
        "signals": [],
        "keywords": prompt[:80],
        "linkedin_keywords": "founder",
        "google_queries": [prompt[:100]],
    }
