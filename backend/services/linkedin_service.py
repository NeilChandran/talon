"""
LinkedIn Voyager API client.
Uses the same internal API that linkedin.com browser uses.
Only requires li_at — JSESSIONID is derived automatically.
"""
import asyncio
import json
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

SESSION_FILE = Path(__file__).parent.parent / ".linkedin_session.json"

BASE_URL = "https://www.linkedin.com"

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


# ──────────────────────────────────────────────────────────────────────────────
# Session helpers
# ──────────────────────────────────────────────────────────────────────────────

def load_session() -> Optional[Dict[str, str]]:
    if SESSION_FILE.exists():
        try:
            with open(SESSION_FILE) as f:
                return json.load(f)
        except Exception:
            return None
    return None


def save_session(li_at: str, jsessionid: str, meta: Optional[Dict] = None) -> None:
    data = {"li_at": li_at, "jsessionid": jsessionid}
    if meta:
        data.update(meta)
    with open(SESSION_FILE, "w") as f:
        json.dump(data, f, indent=2)


def clear_session() -> None:
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()


def session_exists() -> bool:
    return SESSION_FILE.exists()


# ──────────────────────────────────────────────────────────────────────────────
# HTTP helpers
# ──────────────────────────────────────────────────────────────────────────────

def _headers(jsessionid: str) -> Dict[str, str]:
    csrf = jsessionid.strip('"')
    return {
        "User-Agent": _UA,
        "Accept": "application/vnd.linkedin.normalized+json+2.1",
        "Accept-Language": "en-US,en;q=0.9",
        "x-li-lang": "en_US",
        "x-restli-protocol-version": "2.0.0",
        "x-li-track": json.dumps({
            "clientVersion": "1.13.2718",
            "mpVersion": "1.13.2718",
            "osName": "web",
            "timezoneOffset": -7,
            "timezone": "America/Los_Angeles",
            "deviceFormFactor": "DESKTOP",
            "mpName": "voyager-web",
        }),
        "csrf-token": csrf,
        "Referer": "https://www.linkedin.com/search/results/people/",
        "Origin": BASE_URL,
    }


def _cookies(li_at: str, jsessionid: str) -> Dict[str, str]:
    return {"li_at": li_at, "JSESSIONID": jsessionid}


def _client(li_at: str, jsessionid: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=20.0,
        headers=_headers(jsessionid),
        cookies=_cookies(li_at, jsessionid),
        follow_redirects=True,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Auto-derive JSESSIONID from li_at (user only needs to paste one cookie)
# ──────────────────────────────────────────────────────────────────────────────

async def _fetch_jsessionid(li_at: str) -> Optional[str]:
    """
    Visit linkedin.com with li_at to get the JSESSIONID session cookie.
    LinkedIn always issues JSESSIONID on an authenticated page load.
    Limit redirects to 3 to avoid infinite loops on invalid cookies.
    """
    try:
        async with httpx.AsyncClient(
            timeout=12.0,
            max_redirects=3,
            follow_redirects=True,
            cookies={"li_at": li_at},
            headers={
                "User-Agent": _UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        ) as c:
            resp = await c.get(f"{BASE_URL}/feed/")

        # If we ended up on the login page, the cookie is invalid
        if "/login" in str(resp.url) or "/authwall" in str(resp.url):
            print(f"[linkedin] li_at appears invalid — redirected to {resp.url}", flush=True)
            return None

        jsessionid = resp.cookies.get("JSESSIONID")
        if jsessionid:
            print(f"[linkedin] derived JSESSIONID automatically", flush=True)
            return jsessionid
        print(f"[linkedin] JSESSIONID not in response cookies (status {resp.status_code})", flush=True)
        return None
    except httpx.TooManyRedirects:
        print(f"[linkedin] too many redirects — li_at cookie is likely invalid", flush=True)
        return None
    except Exception as e:
        print(f"[linkedin] could not fetch JSESSIONID: {e}", flush=True)
        return None


async def setup_session(li_at: str) -> Dict[str, Any]:
    """
    Given only li_at, derive JSESSIONID automatically and validate the session.
    Returns: {"valid": bool, "jsessionid": str, "name": str, ...}
    """
    jsessionid = await _fetch_jsessionid(li_at)
    if not jsessionid:
        # Cookie is invalid (LinkedIn redirected us to login page)
        return {
            "valid": False,
            "error": "Cookie appears invalid — LinkedIn redirected to login. Copy a fresh li_at value.",
            "jsessionid": "ajax:0",
        }

    result = await validate_session(li_at, jsessionid)
    result["jsessionid"] = jsessionid
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Session validation
# ──────────────────────────────────────────────────────────────────────────────

async def validate_session(li_at: str, jsessionid: str) -> Dict[str, Any]:
    """Check if the LinkedIn session is valid. Returns profile info on success."""
    try:
        async with _client(li_at, jsessionid) as c:
            resp = await c.get(f"{BASE_URL}/voyager/api/me")

        if resp.status_code == 401:
            return {"valid": False, "error": "Session expired — please paste a fresh li_at cookie"}
        if resp.status_code == 403:
            return {"valid": False, "error": "Access denied — CSRF mismatch or cookie blocked"}
        if resp.status_code != 200:
            return {"valid": False, "error": f"LinkedIn returned HTTP {resp.status_code}"}

        data = resp.json()
        mini = data.get("miniProfile") or {}
        name = f"{mini.get('firstName', '')} {mini.get('lastName', '')}".strip()
        pub = mini.get("publicIdentifier", "")
        return {
            "valid": True,
            "name": name or "LinkedIn User",
            "headline": mini.get("occupation", ""),
            "linkedin_url": f"https://linkedin.com/in/{pub}" if pub else "",
        }
    except Exception as e:
        return {"valid": False, "error": str(e)}


# ──────────────────────────────────────────────────────────────────────────────
# People search
# ──────────────────────────────────────────────────────────────────────────────

async def search_people(
    keywords: str,
    li_at: str,
    jsessionid: str,
    count: int = 20,
) -> List[Dict[str, Any]]:
    """
    Search LinkedIn for people matching keywords.
    Returns real profile data (name, title, LinkedIn URL, profile IDs).
    """
    params = {
        "count": str(min(count, 49)),
        "q": "blended",
        "filters": "List(resultType->PEOPLE)",
        "keywords": keywords,
        "start": "0",
        "origin": "GLOBAL_SEARCH_HEADER",
    }

    try:
        async with _client(li_at, jsessionid) as c:
            resp = await c.get(
                f"{BASE_URL}/voyager/api/search/blended",
                params=params,
            )

        if resp.status_code != 200:
            print(f"[linkedin] search returned HTTP {resp.status_code}: {resp.text[:200]}", flush=True)
            return []

        data = resp.json()
        people: List[Dict[str, Any]] = []

        # Navigate nested elements
        for section in data.get("elements", []):
            for item in section.get("elements", []):
                mini = item.get("miniProfile")
                if not mini:
                    continue

                public_id = mini.get("publicIdentifier", "")
                first = mini.get("firstName", "")
                last = mini.get("lastName", "")
                name = f"{first} {last}".strip()

                if not name or not public_id:
                    continue

                entity_urn = mini.get("entityUrn", "")
                profile_id = entity_urn.split(":")[-1] if entity_urn else ""
                object_urn = mini.get("objectUrn", "")
                member_id = object_urn.split(":")[-1] if object_urn else ""

                occupation = mini.get("occupation", "")
                title, company = "", ""
                if " at " in occupation:
                    parts = occupation.split(" at ", 1)
                    title = parts[0].strip()
                    company = parts[1].strip()
                else:
                    title = occupation

                people.append({
                    "name": name,
                    "title": title,
                    "company": company,
                    "company_size": "",
                    "linkedin_url": f"https://linkedin.com/in/{public_id}",
                    "linkedin_public_id": public_id,
                    "linkedin_profile_id": profile_id,
                    "linkedin_member_id": member_id,
                    "tech_stack": [],
                    "description": occupation,
                })

        return people

    except Exception as e:
        print(f"[linkedin] search_people error: {e}", flush=True)
        return []


# ──────────────────────────────────────────────────────────────────────────────
# Profile lookup (resolve public URL → internal profile/member IDs)
# ──────────────────────────────────────────────────────────────────────────────

def _extract_public_id(linkedin_url: str) -> Optional[str]:
    """
    Extract the public identifier from a LinkedIn profile URL.
    e.g. 'https://linkedin.com/in/john-smith' → 'john-smith'
    """
    if not linkedin_url:
        return None
    # Strip trailing slashes and query params
    url = linkedin_url.strip().split("?")[0].rstrip("/")
    if "/in/" in url:
        return url.split("/in/")[-1].strip("/")
    return None


async def lookup_profile(
    public_id: str,
    li_at: str,
    jsessionid: str,
) -> Optional[Dict[str, str]]:
    """
    Look up a LinkedIn profile by public identifier.
    Returns {"linkedin_profile_id": "ACoAAA...", "linkedin_member_id": "12345"}
    or None if not found.
    """
    try:
        async with _client(li_at, jsessionid) as c:
            resp = await c.get(
                f"{BASE_URL}/voyager/api/identity/profiles/{public_id}",
                params={"memberIdentifier": public_id},
            )

        if resp.status_code != 200:
            print(f"[linkedin] profile lookup {public_id!r} → HTTP {resp.status_code}", flush=True)
            return None

        data = resp.json()

        # entityUrn: "urn:li:fs_profile:ACoAA..."
        entity_urn = data.get("entityUrn", "")
        profile_id = entity_urn.split(":")[-1] if entity_urn else ""

        # objectUrn: "urn:li:member:12345"
        object_urn = data.get("objectUrn", "")
        member_id = object_urn.split(":")[-1] if object_urn else ""

        if not profile_id:
            # Try miniProfile nested format
            mini = data.get("miniProfile") or {}
            entity_urn = mini.get("entityUrn", "")
            profile_id = entity_urn.split(":")[-1] if entity_urn else ""
            object_urn = mini.get("objectUrn", "")
            member_id = object_urn.split(":")[-1] if object_urn else ""

        if profile_id:
            print(f"[linkedin] resolved {public_id!r} → profile_id={profile_id}", flush=True)
            return {"linkedin_profile_id": profile_id, "linkedin_member_id": member_id}

        print(f"[linkedin] profile lookup {public_id!r} returned no IDs", flush=True)
        return None

    except Exception as e:
        print(f"[linkedin] lookup_profile error for {public_id!r}: {e}", flush=True)
        return None


async def resolve_lead_ids(
    linkedin_url: str,
    li_at: str,
    jsessionid: str,
) -> Optional[Dict[str, str]]:
    """
    Given a LinkedIn profile URL, resolve it to internal profile/member IDs.
    Returns None if resolution fails.
    """
    public_id = _extract_public_id(linkedin_url)
    if not public_id:
        return None
    return await lookup_profile(public_id, li_at, jsessionid)


# ──────────────────────────────────────────────────────────────────────────────
# Connection requests
# ──────────────────────────────────────────────────────────────────────────────

async def send_connection_request(
    profile_id: str,
    note: str,
    li_at: str,
    jsessionid: str,
) -> Dict[str, Any]:
    """
    Send a LinkedIn connection request with a personalised note.
    profile_id: the ACoAAA... part from the miniProfile entityUrn.
    note: ≤300 characters.
    """
    payload = {
        "invitee": {
            "com.linkedin.voyager.growth.invitation.InviteeProfile": {
                "profileId": profile_id
            }
        },
        "message": note[:300],
    }

    hdrs = _headers(jsessionid)
    hdrs["Content-Type"] = "application/json"

    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            headers=hdrs,
            cookies=_cookies(li_at, jsessionid),
        ) as c:
            resp = await c.post(
                f"{BASE_URL}/voyager/api/growth/normInvitations",
                json=payload,
            )

        if resp.status_code in (200, 201):
            return {"success": True}
        if resp.status_code == 429:
            return {"success": False, "error": "Rate limited by LinkedIn — slow down"}
        return {"success": False, "error": f"HTTP {resp.status_code}", "detail": resp.text[:300]}

    except Exception as e:
        return {"success": False, "error": str(e)}


# ──────────────────────────────────────────────────────────────────────────────
# Messaging
# ──────────────────────────────────────────────────────────────────────────────

async def send_message(
    member_id: str,
    message: str,
    li_at: str,
    jsessionid: str,
) -> Dict[str, Any]:
    """
    Send a LinkedIn direct message to an existing connection.
    member_id: the numeric ID from urn:li:member:<id>.
    """
    payload = {
        "keyVersion": "LEGACY_INBOX",
        "conversationCreate": {
            "eventCreate": {
                "value": {
                    "com.linkedin.voyager.messaging.create.MessageCreate": {
                        "attributedBody": {
                            "text": message,
                            "attributes": [],
                        },
                        "attachments": [],
                    }
                }
            },
            "recipients": [f"urn:li:member:{member_id}"],
            "subtype": "MEMBER_TO_MEMBER",
        },
    }

    hdrs = _headers(jsessionid)
    hdrs["Content-Type"] = "application/json"

    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            headers=hdrs,
            cookies=_cookies(li_at, jsessionid),
        ) as c:
            resp = await c.post(
                f"{BASE_URL}/voyager/api/messaging/conversations",
                params={"action": "create"},
                json=payload,
            )

        if resp.status_code in (200, 201):
            return {"success": True}
        if resp.status_code == 429:
            return {"success": False, "error": "Rate limited — slow down"}
        return {"success": False, "error": f"HTTP {resp.status_code}", "detail": resp.text[:300]}

    except Exception as e:
        return {"success": False, "error": str(e)}


# ──────────────────────────────────────────────────────────────────────────────
# Human-paced delay to avoid LinkedIn rate limiting
# ──────────────────────────────────────────────────────────────────────────────

async def human_delay(min_s: float = 3.0, max_s: float = 8.0) -> None:
    """Sleep a random human-paced interval to avoid rate limits."""
    await asyncio.sleep(random.uniform(min_s, max_s))
