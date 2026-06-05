"""CSV export and Instantly email push."""
import csv
import io
import os
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Lead, WorkspaceListLead
from services.app_settings import get_settings, save_settings
from services.instantly_service import DRY_RUN, push_leads_batch

router = APIRouter()


class AppSettingsBody(BaseModel):
    instantly_campaign_id: Optional[str] = None


class InstantlyPushBody(BaseModel):
    lead_ids: Optional[List[uuid.UUID]] = None
    subject: Optional[str] = ""
    step1_body: Optional[str] = ""
    step2_body: Optional[str] = ""
    step3_body: Optional[str] = ""


@router.get("/settings")
async def read_settings():
    s = get_settings()
    return {
        "instantly_campaign_id": s.get("instantly_campaign_id", ""),
        "dry_run": DRY_RUN,
        "has_serper": bool(__import__("os").getenv("SERPER_API_KEY")),
        "has_proxycurl": bool(__import__("os").getenv("PROXYCURL_API_KEY")),
        "has_instantly": bool(__import__("os").getenv("INSTANTLY_API_KEY")),
        "has_origami": bool(__import__("os").getenv("ORIGAMI_API_KEY")),
    }


@router.put("/settings")
async def update_settings(body: AppSettingsBody):
    s = get_settings()
    if body.instantly_campaign_id is not None:
        s["instantly_campaign_id"] = body.instantly_campaign_id.strip()
    save_settings(s)
    return await read_settings()


@router.get("/lists/{list_id}/export.csv")
async def export_list_csv(list_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    rr = await db.execute(
        select(WorkspaceListLead, Lead)
        .outerjoin(Lead, Lead.id == WorkspaceListLead.lead_id)
        .where(WorkspaceListLead.list_id == list_id)
        .order_by(WorkspaceListLead.sort_order.asc())
    )
    rows = rr.all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["#", "First Name", "Last Name", "Title", "Company", "Email", "LinkedIn", "Score"])
    for i, (wl, lead) in enumerate(rows, 1):
        email = (lead.email if lead else "") or (wl.extra or {}).get("email", "")
        w.writerow([
            i,
            wl.first_name,
            wl.last_name,
            wl.title,
            wl.company,
            email,
            wl.linkedin_url,
            wl.icp_score,
        ])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="leads-{list_id}.csv"'},
    )


@router.post("/lists/{list_id}/instantly")
async def push_to_instantly(
    list_id: uuid.UUID,
    body: InstantlyPushBody,
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    campaign_id = os.getenv("INSTANTLY_CAMPAIGN_ID", "").strip() or settings.get("instantly_campaign_id", "")
    if not campaign_id:
        raise HTTPException(400, "Set Instantly campaign ID in Settings")

    q = (
        select(WorkspaceListLead, Lead)
        .outerjoin(Lead, Lead.id == WorkspaceListLead.lead_id)
        .where(WorkspaceListLead.list_id == list_id)
    )
    if body.lead_ids:
        q = q.where(WorkspaceListLead.id.in_(body.lead_ids))
    pairs = list((await db.execute(q)).all())
    leads_payload = []
    for wl, lead in pairs:
        email = (lead.email if lead else "") or (wl.extra or {}).get("email", "")
        leads_payload.append({
            "first_name": wl.first_name,
            "last_name": wl.last_name,
            "company": wl.company,
            "email": email,
        })

    result = await push_leads_batch(leads_payload, campaign_id)

    if result.get("pushed"):
        for wl, lead in pairs:
            if lead:
                lead.sequence_status = "instantly_queued"
        await db.commit()

    return result
