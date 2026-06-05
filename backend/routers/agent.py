import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import AgentChatMessage, Campaign, CampaignEnrollment
from schemas import AgentChatRequest, AgentChatResponse, SuggestedAction
from services.agent_context import build_agent_context
from services.claude_service import agent_chat
from services.linkedin_service import load_session

router = APIRouter()


@router.get("/history")
async def get_chat_history(
    campaign_id: Optional[uuid.UUID] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    q = select(AgentChatMessage).order_by(AgentChatMessage.created_at.asc()).limit(limit)
    if campaign_id:
        q = q.where(AgentChatMessage.campaign_id == campaign_id)
    result = await db.execute(q)
    messages = list(result.scalars().all())
    return [
        {
            "id": str(m.id),
            "role": m.role,
            "content": m.content,
            "suggested_actions": m.suggested_actions or [],
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in messages
    ]


@router.post("/chat", response_model=AgentChatResponse)
async def chat(body: AgentChatRequest, db: AsyncSession = Depends(get_db)):
    context = await build_agent_context(db, body.campaign_id)
    context["linkedin_connected"] = bool(load_session())

    hist_q = select(AgentChatMessage).order_by(AgentChatMessage.created_at.desc()).limit(12)
    if body.campaign_id:
        hist_q = hist_q.where(AgentChatMessage.campaign_id == body.campaign_id)
    hist_r = await db.execute(hist_q)
    history = [
        {"role": m.role, "content": m.content}
        for m in reversed(list(hist_r.scalars().all()))
    ]

    db.add(
        AgentChatMessage(
            id=uuid.uuid4(),
            campaign_id=body.campaign_id,
            role="user",
            content=body.message,
            created_at=datetime.utcnow(),
        )
    )
    await db.commit()

    result = await agent_chat(body.message, context, history)

    campaign_updated = False
    apply = result.get("apply_copy") or {}
    if apply and body.campaign_id:
        camp_r = await db.execute(select(Campaign).where(Campaign.id == body.campaign_id))
        campaign = camp_r.scalar_one_or_none()
        if campaign:
            if apply.get("connection_note_template") is not None:
                campaign.connection_note_template = apply["connection_note_template"][:300]
                campaign_updated = True
            if apply.get("message_template") is not None:
                campaign.message_template = apply["message_template"]
                campaign_updated = True
            if apply.get("wait_days_after_accept") is not None:
                campaign.wait_days_after_accept = int(apply["wait_days_after_accept"])
                campaign_updated = True
            if campaign_updated:
                campaign.updated_at = datetime.utcnow()
                # Refresh enrollment previews
                enr_r = await db.execute(
                    select(CampaignEnrollment).where(
                        CampaignEnrollment.campaign_id == campaign.id,
                        CampaignEnrollment.status.in_(["pending", "connection_sent", "accepted"]),
                    )
                )
                from models import Lead

                for enr in enr_r.scalars().all():
                    lead_r = await db.execute(select(Lead).where(Lead.id == enr.lead_id))
                    lead = lead_r.scalar_one_or_none()
                    if not lead:
                        continue
                    first = (lead.name or "there").split()[0]
                    if apply.get("connection_note_template") and enr.status == "pending":
                        enr.connection_note = (
                            campaign.connection_note_template.replace("{{first_name}}", first)
                            .replace("{{company}}", lead.company or "your company")[:300]
                        )
                    if apply.get("message_template"):
                        enr.follow_up_message = (
                            campaign.message_template.replace("{{first_name}}", first)
                            .replace("{{company}}", lead.company or "your company")
                        )

    actions_raw = result.get("suggested_actions") or []
    suggested: List[SuggestedAction] = []
    for i, a in enumerate(actions_raw):
        if isinstance(a, dict):
            suggested.append(
                SuggestedAction(
                    id=a.get("id", str(i)),
                    label=a.get("label", "Continue"),
                    action=a.get("action", "launch_campaign"),
                )
            )

    reply_text = result.get("reply", "I'm here to help with your LinkedIn outreach.")

    db.add(
        AgentChatMessage(
            id=uuid.uuid4(),
            campaign_id=body.campaign_id,
            role="assistant",
            content=reply_text,
            suggested_actions=[a.label for a in suggested],
            created_at=datetime.utcnow(),
        )
    )
    await db.commit()

    return AgentChatResponse(
        reply=reply_text,
        suggested_actions=suggested,
        campaign_updated=campaign_updated,
    )
