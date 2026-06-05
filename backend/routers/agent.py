import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends

from database import get_db
from schemas import AgentChatRequest, AgentChatResponse, SuggestedAction
from services.agent_context import build_agent_context
from services.claude_service import agent_chat
from services.linkedin_service import load_session
from user_store import UserStore
from store import get_store

router = APIRouter()


@router.get("/history")
async def get_chat_history(
    campaign_id: Optional[uuid.UUID] = None,
    limit: int = 50,
    db: UserStore = Depends(get_db),
):
    messages = await db.list_agent_messages(
        campaign_id=campaign_id,
        order="created_at",
        desc=False,
        limit=limit,
    )
    return [
        {
            "id": str(m.id),
            "role": m.role,
            "content": m.content,
            "suggested_actions": m.suggested_actions or [],
            "created_at": m.created_at,
        }
        for m in messages
    ]


@router.post("/chat", response_model=AgentChatResponse)
async def chat(body: AgentChatRequest, db: UserStore = Depends(get_db)):
    context = await build_agent_context(db, body.campaign_id)
    context["linkedin_connected"] = bool(load_session())

    hist = await db.list_agent_messages(
        campaign_id=body.campaign_id,
        order="created_at",
        desc=True,
        limit=12,
    )
    history = [{"role": m.role, "content": m.content} for m in reversed(hist)]

    now = datetime.utcnow().isoformat()
    await db.insert(
        "agent_chat_messages",
        {
            "id": str(uuid.uuid4()),
            "campaign_id": str(body.campaign_id) if body.campaign_id else None,
            "role": "user",
            "content": body.message,
            "created_at": now,
        },
    )

    result = await agent_chat(body.message, context, history)

    campaign_updated = False
    apply = result.get("apply_copy") or {}
    if apply and body.campaign_id:
        campaign = await db.select_one("campaigns", body.campaign_id)
        if campaign:
            camp_patch: dict = {}
            if apply.get("connection_note_template") is not None:
                camp_patch["connection_note_template"] = apply["connection_note_template"][:300]
                campaign_updated = True
            if apply.get("message_template") is not None:
                camp_patch["message_template"] = apply["message_template"]
                campaign_updated = True
            if apply.get("wait_days_after_accept") is not None:
                camp_patch["wait_days_after_accept"] = int(apply["wait_days_after_accept"])
                campaign_updated = True
            if campaign_updated:
                camp_patch["updated_at"] = now
                campaign = await db.update("campaigns", body.campaign_id, camp_patch) or campaign
                enrollments = await db.select_many(
                    "campaign_enrollments",
                    filters={"campaign_id": str(body.campaign_id)},
                    in_filters={"status": ["pending", "connection_sent", "accepted"]},
                )
                for enr in enrollments:
                    lead = await db.select_one("leads", enr.lead_id)
                    if not lead:
                        continue
                    first = (lead.name or "there").split()[0]
                    enr_patch: dict = {"updated_at": now}
                    if apply.get("connection_note_template") and enr.status == "pending":
                        enr_patch["connection_note"] = (
                            campaign.connection_note_template.replace("{{first_name}}", first)
                            .replace("{{company}}", lead.company or "your company")[:300]
                        )
                    if apply.get("message_template"):
                        enr_patch["follow_up_message"] = (
                            campaign.message_template.replace("{{first_name}}", first)
                            .replace("{{company}}", lead.company or "your company")
                        )
                    if len(enr_patch) > 1:
                        await db.update("campaign_enrollments", enr.id, enr_patch)

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

    await db.insert(
        "agent_chat_messages",
        {
            "id": str(uuid.uuid4()),
            "campaign_id": str(body.campaign_id) if body.campaign_id else None,
            "role": "assistant",
            "content": reply_text,
            "suggested_actions": [a.label for a in suggested],
            "created_at": now,
        },
    )

    return AgentChatResponse(
        reply=reply_text,
        suggested_actions=suggested,
        campaign_updated=campaign_updated,
    )
