"""LinkedIn profile enrichment via Proxycurl (Nubela)."""
import os
from typing import Any, Dict, Optional

import httpx

PROXYCURL_API_KEY = os.getenv("PROXYCURL_API_KEY", "")
PROXYCURL_URL = "https://nubela.co/proxycurl/api/v2/linkedin"


async def enrich_linkedin_profile(linkedin_url: str) -> Dict[str, Any]:
    """Fetch name, title, company, email from Proxycurl."""
    empty: Dict[str, Any] = {
        "linkedin_url": linkedin_url,
        "first_name": "",
        "last_name": "",
        "name": "",
        "title": "",
        "company": "",
        "email": "",
        "source_url": linkedin_url,
    }
    if not PROXYCURL_API_KEY:
        # Slug fallback when no Proxycurl key
        slug = linkedin_url.rstrip("/").split("/in/")[-1].replace("-", " ").title()
        empty["name"] = slug
        parts = slug.split()
        if parts:
            empty["first_name"] = parts[0]
            empty["last_name"] = " ".join(parts[1:])
        return empty

    async with httpx.AsyncClient(timeout=45.0) as client:
        try:
            resp = await client.get(
                PROXYCURL_URL,
                headers={"Authorization": f"Bearer {PROXYCURL_API_KEY}"},
                params={"url": linkedin_url},
            )
            if resp.status_code != 200:
                print(f"[proxycurl] {linkedin_url}: HTTP {resp.status_code}", flush=True)
                return empty
            data = resp.json()
            first = data.get("first_name") or ""
            last = data.get("last_name") or ""
            company = ""
            exp = data.get("experiences") or []
            if exp and isinstance(exp[0], dict):
                company = exp[0].get("company") or ""
            if not company:
                company = (data.get("company") or "") if isinstance(data.get("company"), str) else ""
            email = data.get("personal_email") or data.get("email") or ""
            if isinstance(email, list):
                email = email[0] if email else ""
            return {
                "linkedin_url": linkedin_url,
                "first_name": first,
                "last_name": last,
                "name": f"{first} {last}".strip(),
                "title": data.get("occupation") or data.get("headline") or "",
                "company": company,
                "email": email or "",
                "source_url": linkedin_url,
            }
        except Exception as e:
            print(f"[proxycurl] {e}", flush=True)
            return empty
