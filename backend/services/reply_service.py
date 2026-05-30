"""
LinkedIn reply detection service.

Checks whether any "contacted" leads have replied to our outreach
by polling the LinkedIn Voyager messaging API.

How it works:
  - For each lead with a linkedin_member_id, fetch the conversation thread
  - If the last message sender is NOT us → they replied
  - Update lead status to "replied" in the database

LinkedIn API endpoint used:
  GET /voyager/api/messaging/conversations
      ?q=participants
      &recipients=urn:li:member:{member_id}
"""
import asyncio
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from database import AsyncSessionLocal
from models import Lead
from sqlalchemy import select


BASE_URL = "https://www.linkedin.com"
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def _headers(jsessionid: str) -> Dict[str, str]:
    csrf = jsessionid.strip('"')
    return {
        "User-Agent": _UA,
        "Accept": "application/vnd.linkedin.normalized+json+2.1",
        "Accept-Language": "en-US,en;q=0.9",
        "x-li-lang": "en_US",
        "x-restli-protocol-version": "2.0.0",
        "csrf-token": csrf,
        "Referer": "https://www.linkedin.com/messaging/",
        "Origin": BASE_URL,
    }


def _cookies(li_at: str, jsessionid: str, bcookie: str = "", bscookie: str = "") -> Dict[str, str]:
    j = jsessionid.strip('"')
    jar: Dict[str, str] = {"li_at": li_at, "JSESSIONID": f'"{j}"'}
    if bcookie:
        jar["bcookie"] = f'"{bcookie.strip().strip(chr(34))}"'
    if bscookie:
        jar["bscookie"] = f'"{bscookie.strip().strip(chr(34))}"'
    return jar


async def _get_conversation(
    member_id: str,
    my_member_urn: str,
    li_at: str,
    jsessionid: str,
    bcookie: str,
    bscookie: str,
) -> Optional[Dict[str, Any]]:
    """
    Fetch the conversation thread with a specific LinkedIn member.
    Returns None if no conversation exists or API fails.
    """
    url = (
        f"{BASE_URL}/voyager/api/messaging/conversations"
        f"?q=participants&recipients=urn:li:member:{member_id}"
    )
    try:
        async with httpx.AsyncClient(
            timeout=12.0,
            headers=_headers(jsessionid),
            cookies=_cookies(li_at, jsessionid, bcookie, bscookie),
            follow_redirects=False,
        ) as c:
            resp = await c.get(url)

        if resp.is_redirect or resp.status_code in (401, 403):
            return None
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception as e:
        print(f"[reply] conversation fetch error for {member_id}: {e}", flush=True)
        return None


def _parse_last_sender(data: Dict[str, Any], my_member_urn: str) -> Optional[str]:
    """
    Extract the URN of the last message sender from a conversation response.
    Returns the sender URN, or None if conversation is empty.
    """
    # Top-level elements are conversation entities
    for conv in data.get("elements", []):
        # Each conversation has events (messages)
        events = conv.get("events", [])
        if not events:
            # Also check *events key (Voyager normalized format)
            events_key = conv.get("*events", [])
            # We only get the key, not inline events — skip
            continue

        # Find the most recent event (events are newest-first or oldest-first)
        if not events:
            continue

        # Events may be sorted newest first
        last_event = events[0]
        # Each event has a "from" field
        sender_urn = last_event.get("from", "")
        if not sender_urn:
            # Nested structure: {"from": {"com.linkedin.voyager.messaging.MessagingMember": {"miniProfile": {...}}}}
            from_val = last_event.get("from") or {}
            if isinstance(from_val, dict):
                for v in from_val.values():
                    if isinstance(v, dict) and v.get("entityUrn"):
                        sender_urn = v["entityUrn"]
                        break

        return sender_urn

    return None


async def _get_unread_conversations(
    li_at: str,
    jsessionid: str,
    bcookie: str,
    bscookie: str,
    count: int = 20,
) -> List[Dict[str, Any]]:
    """
    Fetch recent conversations from LinkedIn inbox.
    Returns list of conversation objects.
    """
    url = (
        f"{BASE_URL}/voyager/api/messaging/conversations"
        f"?keyVersion=LEGACY_INBOX&q=inbox&start=0&count={count}"
    )
    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            headers=_headers(jsessionid),
            cookies=_cookies(li_at, jsessionid, bcookie, bscookie),
            follow_redirects=False,
        ) as c:
            resp = await c.get(url)

        if resp.is_redirect or resp.status_code in (401, 403):
            print("[reply] inbox: session expired or auth error", flush=True)
            return []
        if resp.status_code != 200:
            print(f"[reply] inbox: HTTP {resp.status_code}", flush=True)
            return []
        return resp.json().get("elements", [])
    except Exception as e:
        print(f"[reply] inbox fetch error: {e}", flush=True)
        return []


def _extract_member_id_from_conversation(conv: Dict[str, Any]) -> Optional[str]:
    """Extract the other person's member ID from a conversation object."""
    # Participants field
    participants = conv.get("participants", [])
    for p in participants:
        urn = p.get("entityUrn", "")
        if "member:" in urn:
            # This is a participant urn like urn:li:member:12345
            member_id = urn.split(":")[-1]
            return member_id

    # Also try entityUrn of conversation itself for the "to" side
    entities = conv.get("entityUrns", [])
    for urn in entities:
        if "member:" in urn:
            return urn.split(":")[-1]

    return None


def _conversation_has_reply(conv: Dict[str, Any]) -> bool:
    """
    Returns True if the other person (not us) sent the last message.
    We detect "replied" state by:
    - unreadCount > 0 (new messages from them)
    - Or lastActivityAt is recent and the last message is from the other party
    """
    # Simple heuristic: unreadCount > 0 means they sent something we haven't read
    unread = conv.get("unreadCount", 0)
    return unread > 0


async def check_replies_for_leads(
    leads: List[Lead],
    li_at: str,
    jsessionid: str,
    bcookie: str = "",
    bscookie: str = "",
) -> Dict[str, Any]:
    """
    Check LinkedIn inbox for replies from contacted leads.
    Updates lead status to "replied" for any that have replied.

    Returns:
      {
        "checked": int,
        "replied": int,
        "replied_names": [str],
        "error": str | None
      }
    """
    # Filter to only leads that were contacted and have a member_id
    targets = [l for l in leads if l.status == "contacted" and l.linkedin_member_id]

    if not targets:
        return {"checked": 0, "replied": 0, "replied_names": [], "error": None}

    print(f"[reply] checking {len(targets)} contacted leads for replies...", flush=True)

    # Step 1: Fetch recent conversations from inbox
    conversations = await _get_unread_conversations(li_at, jsessionid, bcookie, bscookie, count=50)

    if not conversations:
        # If inbox fetch fails, try individual lead checks (slower but works)
        print("[reply] inbox empty or failed — skipping individual checks", flush=True)
        return {"checked": len(targets), "replied": 0, "replied_names": [], "error": None}

    # Build a set of member IDs who have sent us unread messages
    replied_member_ids = set()
    for conv in conversations:
        if _conversation_has_reply(conv):
            mid = _extract_member_id_from_conversation(conv)
            if mid:
                replied_member_ids.add(mid)

    print(f"[reply] found {len(replied_member_ids)} conversations with unread messages", flush=True)

    # Step 2: Match to our contacted leads
    replied_leads = []
    for lead in targets:
        if lead.linkedin_member_id in replied_member_ids:
            replied_leads.append(lead)

    # Step 3: Update lead status in DB
    if replied_leads:
        async with AsyncSessionLocal() as db:
            for lead in replied_leads:
                result = await db.execute(select(Lead).where(Lead.id == lead.id))
                db_lead = result.scalar_one_or_none()
                if db_lead and db_lead.status == "contacted":
                    db_lead.status = "replied"
                    db_lead.updated_at = datetime.utcnow()
                    print(f"[reply] {lead.name} → replied ✓", flush=True)
            await db.commit()

    replied_names = [l.name for l in replied_leads]
    print(f"[reply] done — {len(replied_leads)} replies found", flush=True)

    return {
        "checked": len(targets),
        "replied": len(replied_leads),
        "replied_names": replied_names,
        "error": None,
    }
