import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Campaign, CampaignEnrollment, Lead
from schemas import (
    CampaignCreate,
    CampaignEnrollmentResponse,
    CampaignResponse,
    CampaignUpdate,
    EnrollLeadsRequest,
)
from services.campaign_runner import campaign_jobs, run_campaign_job, sync_campaign_enrollments

router = APIRouter()


def _enrollment_to_response(enr: CampaignEnrollment, lead: Lead) -> dict:
    return {
        "id": enr.id,
        "campaign_id": enr.campaign_id,
        "lead_id": enr.lead_id,
        "status": enr.status,
        "connection_note": enr.connection_note,
        "follow_up_message": enr.follow_up_message,
        "connection_sent_at": enr.connection_sent_at,
        "accepted_at": enr.accepted_at,
        "dm_sent_at": enr.dm_sent_at,
        "stopped_reason": enr.stopped_reason,
        "last_error": enr.last_error,
        "name": lead.name if lead else None,
        "title": lead.title if lead else None,
        "company": lead.company if lead else None,
        "linkedin_url": lead.linkedin_url if lead else None,
        "lead_status": lead.status if lead else None,
    }


@router.get("/", response_model=List[CampaignResponse])
async def list_campaigns(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Campaign).order_by(Campaign.created_at.desc()))
    campaigns = list(result.scalars().all())
    out = []
    for c in campaigns:
        cnt_r = await db.execute(
            select(func.count()).select_from(CampaignEnrollment).where(
                CampaignEnrollment.campaign_id == c.id
            )
        )
        count = cnt_r.scalar() or 0
        out.append(
            CampaignResponse(
                id=c.id,
                name=c.name,
                connection_note_template=c.connection_note_template or "",
                message_template=c.message_template or "",
                wait_days_after_accept=c.wait_days_after_accept or 1,
                is_active=c.is_active,
                enrollment_count=count,
                created_at=c.created_at,
                updated_at=c.updated_at,
            )
        )
    return out


@router.post("/", response_model=CampaignResponse)
async def create_campaign(body: CampaignCreate, db: AsyncSession = Depends(get_db)):
    c = Campaign(
        id=uuid.uuid4(),
        name=body.name,
        connection_note_template=body.connection_note_template or "",
        message_template=body.message_template or "",
        wait_days_after_accept=body.wait_days_after_accept,
        is_active=body.is_active,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return CampaignResponse(
        id=c.id,
        name=c.name,
        connection_note_template=c.connection_note_template or "",
        message_template=c.message_template or "",
        wait_days_after_accept=c.wait_days_after_accept or 1,
        is_active=c.is_active,
        enrollment_count=0,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(campaign_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(404, "Campaign not found")
    cnt_r = await db.execute(
        select(func.count()).select_from(CampaignEnrollment).where(
            CampaignEnrollment.campaign_id == c.id
        )
    )
    return CampaignResponse(
        id=c.id,
        name=c.name,
        connection_note_template=c.connection_note_template or "",
        message_template=c.message_template or "",
        wait_days_after_accept=c.wait_days_after_accept or 1,
        is_active=c.is_active,
        enrollment_count=cnt_r.scalar() or 0,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


@router.put("/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    campaign_id: uuid.UUID,
    body: CampaignUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(404, "Campaign not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(c, field, value)
    c.updated_at = datetime.utcnow()

    # Propagate template updates to pending enrollments
    if body.connection_note_template is not None or body.message_template is not None:
        enr_r = await db.execute(
            select(CampaignEnrollment).where(
                CampaignEnrollment.campaign_id == c.id,
                CampaignEnrollment.status.in_(["pending", "connection_sent", "accepted"]),
            )
        )
        for enr in enr_r.scalars().all():
            if body.connection_note_template and enr.status == "pending":
                lead_r = await db.execute(select(Lead).where(Lead.id == enr.lead_id))
                lead = lead_r.scalar_one_or_none()
                if lead:
                    first = (lead.name or "there").split()[0]
                    enr.connection_note = (
                        body.connection_note_template.replace("{{first_name}}", first)
                        .replace("{{company}}", lead.company or "your company")[:300]
                    )
            if body.message_template and enr.status in ("pending", "connection_sent", "accepted"):
                lead_r = await db.execute(select(Lead).where(Lead.id == enr.lead_id))
                lead = lead_r.scalar_one_or_none()
                if lead:
                    first = (lead.name or "there").split()[0]
                    enr.follow_up_message = (
                        body.message_template.replace("{{first_name}}", first)
                        .replace("{{company}}", lead.company or "your company")
                    )

    await db.commit()
    await db.refresh(c)
    cnt_r = await db.execute(
        select(func.count()).select_from(CampaignEnrollment).where(
            CampaignEnrollment.campaign_id == c.id
        )
    )
    return CampaignResponse(
        id=c.id,
        name=c.name,
        connection_note_template=c.connection_note_template or "",
        message_template=c.message_template or "",
        wait_days_after_accept=c.wait_days_after_accept or 1,
        is_active=c.is_active,
        enrollment_count=cnt_r.scalar() or 0,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


@router.get("/{campaign_id}/enrollments", response_model=List[CampaignEnrollmentResponse])
async def list_enrollments(campaign_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(CampaignEnrollment, Lead)
        .join(Lead, Lead.id == CampaignEnrollment.lead_id)
        .where(CampaignEnrollment.campaign_id == campaign_id)
        .order_by(CampaignEnrollment.updated_at.desc())
    )
    rows = result.all()
    return [_enrollment_to_response(enr, lead) for enr, lead in rows]


@router.post("/{campaign_id}/enroll")
async def enroll_leads(
    campaign_id: uuid.UUID,
    body: EnrollLeadsRequest,
    db: AsyncSession = Depends(get_db),
):
    camp_r = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = camp_r.scalar_one_or_none()
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    if body.lead_ids:
        leads_r = await db.execute(
            select(Lead).where(Lead.id.in_(body.lead_ids))
        )
    else:
        leads_r = await db.execute(
            select(Lead).where(Lead.linkedin_url.isnot(None))
        )
    leads = list(leads_r.scalars().all())

    existing_r = await db.execute(
        select(CampaignEnrollment.lead_id).where(
            CampaignEnrollment.campaign_id == campaign_id
        )
    )
    existing_ids = {row[0] for row in existing_r.all()}

    added = 0
    for lead in leads:
        if lead.id in existing_ids:
            continue
        note = ""
        msg = ""
        if campaign.connection_note_template:
            first = (lead.name or "there").split()[0]
            note = (
                campaign.connection_note_template.replace("{{first_name}}", first)
                .replace("{{company}}", lead.company or "your company")[:300]
            )
        if campaign.message_template:
            first = (lead.name or "there").split()[0]
            msg = (
                campaign.message_template.replace("{{first_name}}", first)
                .replace("{{company}}", lead.company or "your company")
            )
        db.add(
            CampaignEnrollment(
                id=uuid.uuid4(),
                campaign_id=campaign_id,
                lead_id=lead.id,
                status="pending",
                connection_note=note or None,
                follow_up_message=msg or None,
            )
        )
        added += 1

    await db.commit()
    return {"enrolled": added, "total_leads": len(leads)}


@router.post("/{campaign_id}/launch")
async def launch_campaign(
    campaign_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    enrollment_ids: Optional[List[uuid.UUID]] = None,
):
    job_id = str(uuid.uuid4())
    campaign_jobs[job_id] = {
        "status": "pending",
        "campaign_id": str(campaign_id),
        "total": 0,
        "done": 0,
        "sent": 0,
        "failed": 0,
        "current": None,
        "step": "Starting...",
    }
    ids = [str(e) for e in enrollment_ids] if enrollment_ids else None
    background_tasks.add_task(run_campaign_job, job_id, str(campaign_id), ids)
    return {"job_id": job_id, "status": "pending"}


@router.get("/jobs/{job_id}")
async def get_campaign_job(job_id: str):
    if job_id not in campaign_jobs:
        raise HTTPException(404, "Job not found")
    return campaign_jobs[job_id]


@router.post("/{campaign_id}/sync")
async def sync_campaign(campaign_id: uuid.UUID, background_tasks: BackgroundTasks):
    """Check accepts and send follow-up DMs for ready enrollments."""
    background_tasks.add_task(sync_campaign_enrollments, str(campaign_id))
    return {"status": "syncing"}


@router.post("/{campaign_id}/enrollments/{enrollment_id}/stop")
async def stop_enrollment(
    campaign_id: uuid.UUID,
    enrollment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CampaignEnrollment).where(
            CampaignEnrollment.id == enrollment_id,
            CampaignEnrollment.campaign_id == campaign_id,
        )
    )
    enr = result.scalar_one_or_none()
    if not enr:
        raise HTTPException(404, "Enrollment not found")
    enr.status = "stopped"
    enr.stopped_reason = "Stopped manually"
    enr.updated_at = datetime.utcnow()
    await db.commit()
    return {"status": "stopped"}
