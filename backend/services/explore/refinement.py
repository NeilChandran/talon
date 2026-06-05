"""Parse follow-up prompts and mutate table."""
import json
from typing import Any, Dict, List, Tuple

from services.claude_service import client, MODEL


async def parse_refinement(
    message: str,
    icp_prompt: str,
    column_keys: List[str],
    row_count: int,
) -> Dict[str, Any]:
    message_out = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": f"""User is refining a B2B lead table.

Original ICP: {icp_prompt}
Current columns: {column_keys}
Row count: {row_count}

Follow-up: {message}

Return JSON:
- action: one of filter | add_column | add_rows | rescore | update_icp | find_people
- filter_rules: optional list of {{field, op, value}} for filter action
- enrichment_column: optional {{key, type}} where type is work_email|phone|tech_stack|funding|decision_maker_linkedin
- icp_addendum: optional string to merge into ICP
- search_hint: optional string for new row discovery
- explanation: short string for the user

Return ONLY JSON.""",
            }
        ],
    )
    text = message_out.content[0].text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}") + 1
        if start >= 0:
            return json.loads(text[start:end])
    return {"action": "rescore", "explanation": "Updated scoring based on your request."}
