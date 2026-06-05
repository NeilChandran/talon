import uuid
from typing import Any, Dict, Optional

from user_store import UserStore


async def build_agent_context(
    db: UserStore,
    campaign_id: Optional[uuid.UUID],
) -> Dict[str, Any]:
    if not campaign_id:
        return {"campaign": None, "enrollment_stats": {}}

    campaign = await db.select_one("campaigns", campaign_id)
    if not campaign:
        return {"campaign": None, "enrollment_stats": {}}

    stats: Dict[str, int] = {}
    for status in (
        "pending",
        "connection_sent",
        "accepted",
        "dm_sent",
        "completed",
        "replied",
        "stopped",
        "failed",
    ):
        stats[status] = await db.count_enrollments_by_status(campaign_id, status)

    return {
        "campaign": {
            "id": str(campaign.id),
            "name": campaign.name,
            "connection_note_template": campaign.connection_note_template or "",
            "message_template": campaign.message_template or "",
            "wait_days_after_accept": campaign.wait_days_after_accept or 1,
        },
        "enrollment_stats": stats,
    }
