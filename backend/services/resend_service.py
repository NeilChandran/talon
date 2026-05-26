import httpx
import os
from typing import Optional

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_BASE_URL = "https://api.resend.com"
FROM_EMAIL = os.getenv("FROM_EMAIL", "outreach@hedwig-ai.com")


async def send_email(
    to: str,
    subject: str,
    body: str,
    reply_to: Optional[str] = None,
) -> dict:
    """Send an email via Resend API."""
    if not RESEND_API_KEY:
        return {"success": False, "error": "Resend API key not configured"}

    payload = {
        "from": f"Hedwig Outreach <{FROM_EMAIL}>",
        "to": [to],
        "subject": subject,
        "text": body,
    }

    if reply_to:
        payload["reply_to"] = reply_to

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(
                f"{RESEND_BASE_URL}/emails",
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

            if resp.status_code in [200, 201]:
                data = resp.json()
                return {"success": True, "email_id": data.get("id")}
            else:
                return {"success": False, "error": resp.text, "status": resp.status_code}

        except Exception as e:
            return {"success": False, "error": str(e)}
