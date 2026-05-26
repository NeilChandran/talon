import anthropic
import json
from typing import Dict, Any, List
import os

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
MODEL = "claude-sonnet-4-20250514"

TALON_CONTEXT = """Talon is an AI-powered LinkedIn outreach platform that finds, scores, and connects with prospects automatically.

Key features:
- AI-powered lead discovery from LinkedIn and the web
- Automatic ICP scoring using Claude
- AI-personalized LinkedIn connection requests and messages
- Automated LinkedIn outreach sequences

Ideal customers: B2B sales teams, founders doing outbound, growth operators at startups."""

ICP_RUBRIC = """Lead Scoring Rubric for Talon:

10: Founder/CEO/Co-founder at 1-20 person YC/VC-backed startup, B2B SaaS or high-growth startup

7-9: Operator (COO, Chief of Staff, Head of Ops, VP Operations) at startup, fast-moving team

4-6: Knowledge worker at mid-size company (20-200 people), uses productivity tools

1-3: Enterprise employee, non-leadership role, or company over 500 people"""


async def parse_prospecting_query(query: str) -> Dict[str, Any]:
    """Parse a natural language prospecting query into structured search parameters."""
    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": f"""Parse this lead prospecting description into LinkedIn search keywords.

Query: {query}

Return a JSON object with:
- target_roles: list of job title keywords (e.g. ["founder", "CEO", "co-founder"])
- company_type: type of companies
- company_size: employee count range
- stage: funding stage if relevant
- industry: industry focus
- linkedin_keywords: a single optimized keyword string for LinkedIn people search (5-8 words max, e.g. "founder CEO SaaS startup seed stage")

Return ONLY valid JSON, no other text.""",
            }
        ],
    )

    try:
        return json.loads(message.content[0].text)
    except json.JSONDecodeError:
        text = message.content[0].text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
        return {
            "target_roles": ["founder", "CEO"],
            "company_type": "startup",
            "company_size": "1-50",
            "linkedin_keywords": query[:50],
        }


async def generate_leads_from_query(query: str, parsed: Dict[str, Any], count: int = 20) -> List[Dict[str, Any]]:
    """
    Use Claude's knowledge of real public figures to generate leads matching the query.
    Used as fallback when LinkedIn session is not available.
    """
    message = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": f"""You are a sales intelligence tool. Generate a list of real, publicly known people who match this prospecting query. Use your knowledge of actual founders, executives, and operators from YC, VC-backed startups, and the tech ecosystem.

Query: {query}

Criteria:
- Target roles: {parsed.get('target_roles', ['founder', 'CEO'])}
- Company type: {parsed.get('company_type', 'startup')}
- Company size: {parsed.get('company_size', '1-50')}
- Stage: {parsed.get('stage', 'seed/series A')}

Return a JSON array of {count} real people. For each person include:
- name: full name (real person)
- title: their actual job title
- company: their actual company name
- company_size: approximate employee count (e.g. "5-15", "10-30", "20-50")
- linkedin_url: their likely LinkedIn URL (https://linkedin.com/in/firstname-lastname format)
- tech_stack: array of tools/tech they likely use
- description: 1-2 sentence bio based on public info

Focus on founders and operators at YC-backed companies, VC-backed B2B SaaS startups, and high-growth tech companies.

Return ONLY a valid JSON array, no other text.""",
            }
        ],
    )

    try:
        text = message.content[0].text.strip()
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            leads = json.loads(text[start:end])
            return leads if isinstance(leads, list) else []
        return []
    except Exception as e:
        print(f"[claude] generate_leads_from_query error: {e}")
        return []


async def enrich_linkedin_leads(leads: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    """
    Enrich leads that came from LinkedIn search (may have limited data).
    Uses Claude to fill in company size, tech stack, description based on title/company.
    """
    if not leads:
        return []

    summaries = "\n".join(
        f"- {l.get('name', '?')}: {l.get('title', '')} at {l.get('company', '')} ({l.get('linkedin_url', '')})"
        for l in leads[:20]
    )

    message = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": f"""These are real LinkedIn profiles found for the query: "{query}"

{summaries}

For each person, using your knowledge of these public figures (if you know them) or reasonable inference from their title/company:
- company_size: estimate employee count range (e.g. "5-20", "50-200")
- tech_stack: likely tools they use (e.g. ["notion", "linear", "slack", "github"])
- description: 1-2 sentence bio

Return a JSON array where each object has:
{{ "name": "...", "company_size": "...", "tech_stack": [...], "description": "..." }}

Return ONLY valid JSON array, same order as input list.""",
            }
        ],
    )

    try:
        text = message.content[0].text.strip()
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            enriched = json.loads(text[start:end])
            if isinstance(enriched, list):
                for i, lead in enumerate(leads):
                    if i < len(enriched):
                        extra = enriched[i]
                        if not lead.get("company_size"):
                            lead["company_size"] = extra.get("company_size", "")
                        if not lead.get("tech_stack"):
                            lead["tech_stack"] = extra.get("tech_stack", [])
                        if not lead.get("description"):
                            lead["description"] = extra.get("description", "")
    except Exception as e:
        print(f"[claude] enrich_linkedin_leads error: {e}")

    return leads


async def score_lead(lead_data: Dict[str, Any]) -> Dict[str, Any]:
    """Score a lead 1-10 based on Talon ICP fit."""
    message = client.messages.create(
        model=MODEL,
        max_tokens=512,
        messages=[
            {
                "role": "user",
                "content": f"""Score this lead for Talon (LinkedIn outreach tool for B2B sales teams) based on ICP fit.

{ICP_RUBRIC}

Lead data:
- Name: {lead_data.get('name', 'Unknown')}
- Title: {lead_data.get('title', 'Unknown')}
- Company: {lead_data.get('company', 'Unknown')}
- Company size: {lead_data.get('company_size', 'Unknown')}
- Tech stack signals: {', '.join(lead_data.get('tech_stack', []))}
- Description: {lead_data.get('description', '')[:500]}

Return a JSON object with:
- score: integer 1-10
- reason: one specific sentence explaining the score

Return ONLY valid JSON.""",
            }
        ],
    )

    try:
        result = json.loads(message.content[0].text)
        return {
            "score": max(1, min(10, int(result.get("score", 5)))),
            "reason": result.get("reason", "No reason provided"),
        }
    except Exception:
        return {"score": 5, "reason": "Unable to score automatically"}


async def generate_linkedin_connection_note(lead: Dict[str, Any]) -> str:
    """
    Generate a personalized LinkedIn connection request note.
    Must be ≤300 characters.
    """
    message = client.messages.create(
        model=MODEL,
        max_tokens=256,
        messages=[
            {
                "role": "user",
                "content": f"""Write a LinkedIn connection request note for this person.

About Talon: {TALON_CONTEXT}

Lead:
- Name: {lead.get('name', 'there')} (use first name)
- Title: {lead.get('title', '')}
- Company: {lead.get('company', '')}
- Why they fit: {lead.get('score_reason', '')}

Rules:
- Max 300 characters (this is a HARD limit, count carefully)
- Sound human and specific — reference their role/company
- Mention what Talon does in one phrase
- No "I hope this message finds you well" clichés
- No formal sign-off needed

Return ONLY the note text, nothing else.""",
            }
        ],
    )

    note = message.content[0].text.strip()
    return note[:300]


async def generate_linkedin_message(lead: Dict[str, Any], message_type: str = "follow_up_message") -> str:
    """
    Generate a personalized LinkedIn direct message.
    """
    instructions = {
        "follow_up_message": """Write a follow-up LinkedIn message (3 days after connection).
- 3-5 sentences max
- Reference their specific role/company pain point
- Mention one specific Talon feature relevant to them
- Clear CTA (offer a quick call or demo)
- Warm, founder-to-founder tone""",

        "final_message": """Write a final LinkedIn message (7 days after connection).
- 2-3 sentences max
- Light touch, leave door open
- One last compelling reason to try Talon
- Friendly, not pushy""",
    }

    first_name = (lead.get("name", "there").split()[0]) if lead.get("name") else "there"

    message = client.messages.create(
        model=MODEL,
        max_tokens=512,
        messages=[
            {
                "role": "user",
                "content": f"""Generate a personalized LinkedIn message from Talon.

About Talon: {TALON_CONTEXT}

Lead:
- Name: {lead.get('name', '')} (use first name: {first_name})
- Title: {lead.get('title', '')}
- Company: {lead.get('company', '')}
- Company size: {lead.get('company_size', '')}
- Why they fit: {lead.get('score_reason', '')}

Message type: {message_type}
Instructions:
{instructions.get(message_type, instructions['follow_up_message'])}

Sign off as "— [Your name] at Talon". Use plain text, no markdown.
Return ONLY the message text.""",
            }
        ],
    )

    return message.content[0].text.strip()


# ── Legacy email generation (kept for backward compat) ──────────────────────

async def generate_email(lead: Dict[str, Any], sequence_type: str) -> Dict[str, str]:
    """Generate a personalized outreach email (legacy)."""
    first_name = lead.get("name", "there").split()[0] if lead.get("name") else "there"
    return {
        "subject": "your inbox, but smarter",
        "body": f"Hi {first_name},\n\nWanted to connect about Talon — AI-powered LinkedIn outreach.\n\nWorth 15 minutes?\n\nThe Talon team",
    }


async def batch_generate_emails(leads: List[Dict[str, Any]], sequence_type: str) -> List[Dict[str, Any]]:
    results = []
    for lead in leads:
        email = await generate_email(lead, sequence_type)
        results.append({"lead_id": str(lead.get("id", "")), **email})
    return results
