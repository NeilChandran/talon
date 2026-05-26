import httpx
import os
from typing import Optional

HUNTER_API_KEY = os.getenv("HUNTER_API_KEY", "")
HUNTER_BASE_URL = "https://api.hunter.io/v2"


async def find_email(
    first_name: str, last_name: str, company: str
) -> Optional[str]:
    """Find a professional email using Hunter.io domain search + email finder."""
    if not HUNTER_API_KEY:
        return None

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            # Step 1: find company domain
            domain_resp = await client.get(
                f"{HUNTER_BASE_URL}/domain-search",
                params={
                    "company": company,
                    "api_key": HUNTER_API_KEY,
                    "limit": 1,
                },
            )

            if domain_resp.status_code != 200:
                return None

            domain = domain_resp.json().get("data", {}).get("domain")
            if not domain:
                return None

            # Step 2: find specific email
            email_resp = await client.get(
                f"{HUNTER_BASE_URL}/email-finder",
                params={
                    "domain": domain,
                    "first_name": first_name,
                    "last_name": last_name,
                    "api_key": HUNTER_API_KEY,
                },
            )

            if email_resp.status_code != 200:
                return None

            data = email_resp.json().get("data", {})
            email = data.get("email")
            confidence = data.get("score", 0)

            if email and confidence > 50:
                return email

        except Exception as e:
            print(f"Hunter.io error: {e}")

    return None


async def verify_email(email: str) -> bool:
    """Verify an email address using Hunter.io."""
    if not HUNTER_API_KEY:
        return True

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(
                f"{HUNTER_BASE_URL}/email-verifier",
                params={"email": email, "api_key": HUNTER_API_KEY},
            )
            if resp.status_code == 200:
                status = resp.json().get("data", {}).get("status")
                return status in ["valid", "accept_all"]
        except Exception as e:
            print(f"Hunter.io verify error: {e}")

    return False
