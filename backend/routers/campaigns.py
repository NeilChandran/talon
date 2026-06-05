import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from database import get_db
from schemas import (
    CampaignCreate,
    CampaignEnrollmentResponse,
    CampaignResponse,
    CampaignUpdate,
    EnrollLeadsRequest,
)
from services.campaign_runner import campaign_jobs, run_campaign_job, sync_campaign_enrollments
from services.outreach_templates import lead_first_name, personalize_connection
from store import Record
from user_store import UserStore

router = APIRouter()


def _campaign_response(c: Record, enrollment_count: int = 0) -> CampaignResponse:
    return CampaignResponse(
        id=uuid.UUID(str(c.id)),
        name=c.name,
        connection_note_template=c.connection_note_template or "",
        message_template=c.message_template or "",
        wait_days_after_accept=c.wait_days_after_accept or 1,
        is_active=c.is_active,
        enrollment_count=enrollment_count,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


def _enrollment_to_response(enr: Record, lead: Optional[Record]) -> dict:
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
        "scheduled_at": enr.scheduled_at if getattr(enr, "scheduled_at", None) else None,
        "origami_send_status": getattr(enr, "origami_send_status", None) or None,
    }


@router.get("/", response_model=List[CampaignResponse])
async def list_campaigns(db: UserStore = Depends(get_db)):
    campaigns = await db.list_campaigns()
    out = []
    for c in campaigns:
        count = await db.count_enrollments(c.id)
        out.append(_campaign_response(c, count))
    return out


@router.post("/", response_model=CampaignResponse)
async def create_campaign(body: CampaignCreate, db: UserStore = Depends(get_db)):
    now = datetime.utcnow().isoformat()
    c = await db.insert(
        "campaigns",
        {
            "id": str(uuid.uuid4()),
            "name": body.name,
            "connection_note_template": body.connection_note_template or "",
            "message_template": body.message_template or "",
            "wait_days_after_accept": body.wait_days_after_accept,
            "is_active": body.is_active,
            "created_at": now,
            "updated_at": now,
        },
    )
    return _campaign_response(c, 0)


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(campaign_id: uuid.UUID, db: UserStore = Depends(get_db)):
    c = await db.select_one("campaigns", campaign_id)
    if not c:
        raise HTTPException(404, "Campaign not found")
    count = await db.count_enrollments(c.id)
    return _campaign_response(c, count)


@router.put("/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    campaign_id: uuid.UUID,
    body: CampaignUpdate,
    db: UserStore = Depends(get_db),
):
    c = await db.select_one("campaigns", campaign_id)
    if not c:
        raise HTTPException(404, "Campaign not found")

    patch = body.model_dump(exclude_unset=True)
    patch["updated_at"] = datetime.utcnow().isoformat()
    c = await db.update("campaigns", campaign_id, patch) or c

    if body.connection_note_template is not None or body.message_template is not None:
        enrollments = await db.select_many(
            "campaign_enrollments",
            filters={"campaign_id": str(campaign_id)},
            in_filters={"status": ["pending", "connection_sent", "accepted"]},
        )
        for enr in enrollments:
            lead = await db.select_one("leads", enr.lead_id)
            if not lead:
                continue
            enr_patch: dict = {}
            if body.connection_note_template and enr.status == "pending":
                enr_patch["connection_note"] = personalize_connection(
                    body.connection_note_template,
                    first_name=lead_first_name(lead),
                    company=lead.company or "",
                    title=lead.title or "",
                )
            if body.message_template and enr.status in ("pending", "connection_sent", "accepted"):
                first = (lead.name or "there").split()[0]
                enr_patch["follow_up_message"] = (
                    body.message_template.replace("{{first_name}}", first)
                    .replace("{{company}}", lead.company or "your company")
                )
            if enr_patch:
                enr_patch["updated_at"] = datetime.utcnow().isoformat()
                await db.update("campaign_enrollments", enr.id, enr_patch)

    count = await db.count_enrollments(c.id)
    return _campaign_response(c, count)


@router.get("/{campaign_id}/enrollments", response_model=List[CampaignEnrollmentResponse])
async def list_enrollments(campaign_id: uuid.UUID, db: UserStore = Depends(get_db)):
    rows = await db.list_enrollments_with_leads(campaign_id)
    return [_enrollment_to_response(enr, lead) for enr, lead in rows]


@router.post("/{campaign_id}/enroll")
async def enroll_leads(
    campaign_id: uuid.UUID,
    body: EnrollLeadsRequest,
    db: UserStore = Depends(get_db),
):
    campaign = await db.select_one("campaigns", campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    if body.lead_ids:
        leads = await db.get_leads_by_ids(body.lead_ids)
    else:
        leads = await db.list_leads_with_linkedin()

    existing_ids = await db.enrollment_lead_ids(campaign_id)

    added = 0
    now = datetime.utcnow().isoformat()
    for lead in leads:
        if str(lead.id) in existing_ids:
            continue
        note = ""
        msg = ""
        if campaign.connection_note_template:
            note = personalize_connection(
                campaign.connection_note_template,
                first_name=lead_first_name(lead),
                company=lead.company or "",
                title=lead.title or "",
            )
        if campaign.message_template:
            first = (lead.name or "there").split()[0]
            msg = (
                campaign.message_template.replace("{{first_name}}", first)
                .replace("{{company}}", lead.company or "your company")
            )
        await db.insert(
            "campaign_enrollments",
            {
                "id": str(uuid.uuid4()),
                "campaign_id": str(campaign_id),
                "lead_id": str(lead.id),
                "status": "pending",
                "connection_note": note or None,
                "follow_up_message": msg or None,
                "created_at": now,
                "updated_at": now,
            },
        )
        added += 1

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
    db: UserStore = Depends(get_db),
):
    rows = await db.select_many(
        "campaign_enrollments",
        filters={"id": str(enrollment_id), "campaign_id": str(campaign_id)},
        limit=1,
    )
    enr = rows[0] if rows else None
    if not enr:
        raise HTTPException(404, "Enrollment not found")
    await db.update(
        "campaign_enrollments",
        enrollment_id,
        {
            "status": "stopped",
            "stopped_reason": "Stopped manually",
            "updated_at": datetime.utcnow().isoformat(),
        },
    )
    return {"status": "stopped"}
