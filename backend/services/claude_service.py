import anthropic
import json
from typing import Dict, Any, List
import os

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
MODEL = "claude-sonnet-4-20250514"

HEDWIG_CONTEXT = """Hedwig is an AI-powered email and calendar tool — "Email and Calendar, Supercharged."

What it does: Makes email and calendar dramatically faster and smarter using AI. Think Superhuman
but with real AI built in — AI that drafts replies, prioritizes your inbox, schedules meetings,
and handles calendar management automatically.

Who buys it: People who live in email and have calendar overload. Founders, sales leaders, and
operators at fast-growing startups who can't afford to let email and meetings slow them down."""

ICP_RUBRIC = """Lead Scoring Rubric for Hedwig (AI email + calendar tool):

10: Founder/CEO/Co-founder at 1-50 person VC-backed or bootstrapped startup. Lives in email,
    drives GTM, manages a calendar full of investor/customer calls.

9:  VP Sales, Head of GTM, Director of Sales at a startup with a growing sales team.
    Sends hundreds of emails a day, manages pipeline, books lots of meetings.

7-8: Chief of Staff, Head of Operations, Revenue Operations Manager at a growth-stage startup.
     Coordinates heavily across email + calendar.

5-6: Individual contributor (AE, SDR, Marketing Manager) at a 20-200 person company who sends
     high email volume daily.

1-4: Enterprise employee (1000+ co), non-tech role, or someone unlikely to pay for a premium
     email/calendar tool (student, academic, government)."""

# Keep backward-compat alias
TALON_CONTEXT = HEDWIG_CONTEXT


async def parse_prospecting_query(query: str) -> Dict[str, Any]:
    """Parse a natural language prospecting query into structured search parameters."""
    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": f"""You are extracting a SHORT LinkedIn people-search keyword string from a natural language query.

Query: {query}

Rules for linkedin_keywords:
- MAXIMUM 3 words total — LinkedIn search works best with short terms
- Use the most identifying words only (e.g. "YC founder", "startup CEO", "chief of staff")
- Do NOT include generic words like "technology", "early", "stage", "building", "company"
- If query mentions YC/Y Combinator → include "YC"
- If query mentions a specific batch (W24, S23) → include that
- Focus on job title + maybe 1 company/org qualifier

Examples:
- "YC W24 founders building B2B SaaS" → "YC founder"
- "startup founder" → "startup founder"
- "Chiefs of staff at VC-backed startups" → "chief of staff"
- "Seed-stage startup founders in SF" → "startup founder"
- "Co-founders of developer tools companies" → "developer tools founder"

Return a JSON object with:
- target_roles: list of job title keywords (e.g. ["founder", "CEO", "co-founder"])
- company_type: type of companies
- company_size: employee count range
- stage: funding stage if relevant
- industry: industry focus
- linkedin_keywords: SHORT 1-3 word string for LinkedIn people search (see rules above)

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
    """Score a lead 1-10 based on Hedwig ICP fit."""
    message = client.messages.create(
        model=MODEL,
        max_tokens=512,
        messages=[
            {
                "role": "user",
                "content": f"""Score this lead for Hedwig (AI email + calendar tool) based on ICP fit.

{ICP_RUBRIC}

Lead data:
- Name: {lead_data.get('name', 'Unknown')}
- Title: {lead_data.get('title', 'Unknown')}
- Company: {lead_data.get('company', 'Unknown')}
- Company size: {lead_data.get('company_size', 'Unknown')}
- Tech stack signals: {', '.join(lead_data.get('tech_stack', []))}
- Description: {lead_data.get('description', '')[:500]}
- Signal: {lead_data.get('signal', '')}

Return a JSON object with:
- score: integer 1-10
- reason: one specific sentence explaining WHY this person would benefit from Hedwig

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
    Generate a personalized LinkedIn connection request note for Hedwig outreach.
    Must be ≤300 characters.
    """
    signal = lead.get("signal", "")
    signal_line = f"\n- Signal context: {signal}" if signal else ""

    message = client.messages.create(
        model=MODEL,
        max_tokens=256,
        messages=[
            {
                "role": "user",
                "content": f"""Write a LinkedIn connection request note for this person on behalf of Hedwig.

About Hedwig: {HEDWIG_CONTEXT}

Lead:
- Name: {lead.get('name', 'there')} (use first name only)
- Title: {lead.get('title', '')}
- Company: {lead.get('company', '')}{signal_line}
- Why they fit: {lead.get('score_reason', '')}

Rules:
- Max 300 characters HARD LIMIT — count every character
- Sound human and specific to their role/company
- Reference Hedwig in one short phrase ("AI email tool", "smarter inbox", etc.)
- No "I hope this message finds you well" or "I came across your profile"
- No formal sign-off

Return ONLY the note text, nothing else.""",
            }
        ],
    )

    note = message.content[0].text.strip()
    return note[:300]


async def generate_linkedin_message(lead: Dict[str, Any], message_type: str = "follow_up_message") -> str:
    """
    Generate a personalized LinkedIn direct message for Hedwig outreach.
    """
    signal = lead.get("signal", "")
    signal_line = f"\n- Signal context: {signal}" if signal else ""

    instructions = {
        "follow_up_message": """Write a follow-up LinkedIn message (sent 3 days after connecting).
- 3-5 sentences max
- Reference their specific role/company and why email + calendar pain is real for them
- Mention one specific Hedwig benefit relevant to their situation
- Clear CTA: offer a quick demo or ask if it's worth 10 minutes
- Tone: warm, peer-to-peer, not salesy""",

        "final_message": """Write a final LinkedIn message (sent 7 days after connecting).
- 2-3 sentences max
- Light touch — leave door open without pressure
- One last reason Hedwig is worth a look given their situation
- Tone: friendly, no urgency""",
    }

    first_name = (lead.get("name", "there").split()[0]) if lead.get("name") else "there"

    message = client.messages.create(
        model=MODEL,
        max_tokens=512,
        messages=[
            {
                "role": "user",
                "content": f"""Generate a personalized LinkedIn message on behalf of Hedwig.

About Hedwig: {HEDWIG_CONTEXT}

Lead:
- Name: {lead.get('name', '')} (use first name: {first_name})
- Title: {lead.get('title', '')}
- Company: {lead.get('company', '')}
- Company size: {lead.get('company_size', '')}{signal_line}
- Why they fit: {lead.get('score_reason', '')}

Message type: {message_type}
Instructions:
{instructions.get(message_type, instructions['follow_up_message'])}

Sign off with "— [Your first name] from Hedwig". Use plain text, no markdown.
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


async def agent_chat(
    user_message: str,
    context: Dict[str, Any],
    history: List[Dict[str, str]],
) -> Dict[str, Any]:
    """
    Revenue agent chat — understands campaigns, suggests actions, can update copy.
    Returns {reply, suggested_actions[], apply_copy: {connection_note?, message?}}
    """
    campaign = context.get("campaign") or {}
    stats = context.get("enrollment_stats") or {}
    li_connected = context.get("linkedin_connected", False)

    system_context = f"""You are Talon AI, a LinkedIn revenue agent (like Origami/Hedwig AI on origami.chat).
You help the user run multi-step LinkedIn outreach campaigns: connection request + follow-up DM.

Product context: {HEDWIG_CONTEXT}

LinkedIn connected: {li_connected}
Active campaign: {campaign.get('name', 'none')}
Campaign ID: {campaign.get('id', '')}
Enrollment stats: {json.dumps(stats)}
Connection note template (current): {(campaign.get('connection_note_template') or '')[:400]}
Follow-up DM template (current): {(campaign.get('message_template') or '')[:600]}
Wait days after accept: {campaign.get('wait_days_after_accept', 1)}

When the user asks to update copy, draft the FULL new templates in apply_copy.
Use {{first_name}} and {{company}} placeholders.
Connection notes must be ≤300 characters.

Respond helpfully. After your message, the app will show suggested action buttons."""

    hist_text = ""
    for h in history[-8:]:
        hist_text += f"{h['role'].upper()}: {h['content']}\n"

    message = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": f"""{system_context}

Recent chat:
{hist_text}

USER: {user_message}

Return ONLY valid JSON with:
- reply: string (markdown ok, concise, actionable)
- suggested_actions: array of {{id, label, action}} where action is one of:
  launch_campaign, update_copy, check_replies, enroll_all, sync_campaign, open_settings
- apply_copy: optional {{connection_note_template, message_template, wait_days_after_accept}}
  only include fields you are intentionally changing based on user request""",
            }
        ],
    )

    text = message.content[0].text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
        return {
            "reply": text,
            "suggested_actions": [
                {"id": "1", "label": "Launch campaign sequences", "action": "launch_campaign"},
            ],
            "apply_copy": {},
        }


async def workspace_agent_chat(
    user_message: str,
    workspace: Dict[str, Any],
    active_list: Optional[Dict[str, Any]],
    rows_sample: List[Dict[str, Any]],
    history: List[Dict[str, str]],
    linkedin_connected: bool,
) -> Dict[str, Any]:
    """Origami workspace agent — draft lists, sequence copy, suggest launch."""
    list_ctx = json.dumps(active_list or {}, indent=0)[:800]
    rows_ctx = json.dumps(rows_sample[:6], indent=0)[:1200]

    system_context = f"""You are Talon AI on origami.chat-style workspaces.
The user describes ICPs, you help refine LinkedIn connection notes and follow-up DMs, and suggest launching sequences.

Product: {HEDWIG_CONTEXT}
LinkedIn connected: {linkedin_connected}
Workspace: {workspace.get('name', '')} (id {workspace.get('id', '')})
Active list: {list_ctx}
Sample leads: {rows_ctx}

When user asks to update messaging, put FULL templates in apply_copy with {{first_name}} and {{company}}.
Connection notes ≤300 chars.

Suggested actions: launch_sequences, update_copy, create_list, open_settings, check_replies."""

    hist_text = ""
    for h in history[-8:]:
        hist_text += f"{h['role'].upper()}: {h['content']}\n"

    message = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": f"""{system_context}

Recent chat:
{hist_text}

USER: {user_message}

Return ONLY valid JSON:
- reply: string (markdown ok)
- suggested_actions: array of {{id, label, action}}
- apply_copy: optional {{connection_note_template, message_template, wait_days_after_accept}}""",
            }
        ],
    )

    text = message.content[0].text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
        return {
            "reply": text,
            "suggested_actions": [
                {"id": "1", "label": "Launch LinkedIn sequences now", "action": "launch_sequences"},
            ],
            "apply_copy": {},
        }


async def workspace_agent_chat(
    user_message: str,
    workspace: Dict[str, Any],
    active_list: Optional[Dict[str, Any]],
    rows_sample: List[Dict[str, Any]],
    history: List[Dict[str, str]],
    linkedin_connected: bool,
) -> Dict[str, Any]:
    """Origami workspace agent — draft lists, sequence copy, suggest launch."""
    list_ctx = json.dumps(active_list or {}, indent=0)[:800]
    rows_ctx = json.dumps(rows_sample[:6], indent=0)[:1200]

    system_context = f"""You are Talon AI on origami.chat-style workspaces.
The user describes ICPs, you help refine LinkedIn connection notes and follow-up DMs, and suggest launching sequences.

Product: {HEDWIG_CONTEXT}
LinkedIn connected: {linkedin_connected}
Workspace: {workspace.get('name', '')} (id {workspace.get('id', '')})
Active list: {list_ctx}
Sample leads: {rows_ctx}

When user asks to update messaging, put FULL templates in apply_copy with {{first_name}} and {{company}}.
Connection notes ≤300 chars.

Suggested actions: launch_sequences, update_copy, create_list, open_settings, check_replies."""

    hist_text = ""
    for h in history[-8:]:
        hist_text += f"{h['role'].upper()}: {h['content']}\n"

    message = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": f"""{system_context}

Recent chat:
{hist_text}

USER: {user_message}

Return ONLY valid JSON:
- reply: string (markdown ok)
- suggested_actions: array of {{id, label, action}}
- apply_copy: optional {{connection_note_template, message_template, wait_days_after_accept}}""",
            }
        ],
    )

    text = message.content[0].text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
        return {
            "reply": text,
            "suggested_actions": [
                {"id": "1", "label": "Launch LinkedIn sequences now", "action": "launch_sequences"},
            ],
            "apply_copy": {},
        }
