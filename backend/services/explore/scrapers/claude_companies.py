"""Claude-generated company list fallback / augment for a source label."""
import json
from typing import Any, Dict, List

from services.claude_service import client, MODEL
from services.explore.scrapers.base import normalize_row


async def generate_companies_for_source(
    parsed: Dict[str, Any],
    source: str,
    count: int = 12,
) -> List[Dict[str, Any]]:
    message = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": f"""Generate {count} real or realistic B2B companies matching this ICP. Source context: {source}.

ICP parameters: {json.dumps(parsed)}

Return JSON array of objects with:
- company_name (required)
- website (domain URL if known, else plausible guess like https://company.com)
- industry
- headcount (e.g. "25" or "10-50")
- location
- note (one line why they match)

Use real public companies when possible. For crunchbase source prefer funded startups. For jobs source prefer companies hiring sales. For news source prefer recently in press.

Return ONLY a JSON array.""",
            }
        ],
    )
    text = message.content[0].text
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("["), text.rfind("]") + 1
        data = json.loads(text[start:end]) if start >= 0 else []

    rows = []
    for item in data if isinstance(data, list) else []:
        r = normalize_row(
            item.get("company_name", ""),
            source,
            website=item.get("website", ""),
            industry=item.get("industry", ""),
            headcount=str(item.get("headcount", "")),
            location=item.get("location", ""),
            raw_data={"note": item.get("note", "")},
        )
        if r:
            rows.append(r)
    return rows
