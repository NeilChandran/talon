import uuid
from typing import Any, Dict, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Campaign, CampaignEnrollment


async def build_agent_context(
    db: AsyncSession,
    campaign_id: Optional[uuid.UUID],
) -> Dict[str, Any]:
    if not campaign_id:
        return {"campaign": None, "enrollment_stats": {}}

    camp_r = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = camp_r.scalar_one_or_none()
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
        cnt_r = await db.execute(
            select(func.count())
            .select_from(CampaignEnrollment)
            .where(
                CampaignEnrollment.campaign_id == campaign_id,
                CampaignEnrollment.status == status,
            )
        )
        stats[status] = cnt_r.scalar() or 0

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
