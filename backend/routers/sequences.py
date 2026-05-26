import asyncio
import uuid
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal, get_db
from models import Lead, LinkedInOutreachLog, Sequence
from schemas import RunSequenceRequest, SequenceCreate, SequenceResponse, SequenceUpdate
from services.claude_service import (
    generate_linkedin_connection_note,
    generate_linkedin_message,
)
from services.linkedin_service import (
    human_delay,
    load_session,
    resolve_lead_ids,
    send_connection_request,
    send_message,
)

router = APIRouter()

# In-memory automation jobs
automation_jobs: Dict[str, Any] = {}


# ─── Sequence CRUD ────────────────────────────────────────────────────────────

@router.get("/", response_model=List[SequenceResponse])
async def get_sequences(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Sequence).order_by(Sequence.delay_days))
    return result.scalars().all()


@router.get("/{sequence_id}", response_model=SequenceResponse)
async def get_sequence(sequence_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Sequence).where(Sequence.id == sequence_id))
    seq = result.scalar_one_or_none()
    if not seq:
        raise HTTPException(status_code=404, detail="Sequence not found")
    return seq


@router.post("/", response_model=SequenceResponse)
async def create_sequence(sequence: SequenceCreate, db: AsyncSession = Depends(get_db)):
    data = sequence.model_dump()
    db_seq = Sequence(id=uuid.uuid4(), **data)
    db.add(db_seq)
    await db.commit()
    await db.refresh(db_seq)
    return db_seq


@router.put("/{sequence_id}", response_model=SequenceResponse)
async def update_sequence(
    sequence_id: uuid.UUID,
    sequence_update: SequenceUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Sequence).where(Sequence.id == sequence_id))
    seq = result.scalar_one_or_none()
    if not seq:
        raise HTTPException(status_code=404, detail="Sequence not found")

    for field, value in sequence_update.model_dump(exclude_unset=True).items():
        setattr(seq, field, value)

    await db.commit()
    await db.refresh(seq)
    return seq


@router.delete("/{sequence_id}")
async def delete_sequence(sequence_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Sequence).where(Sequence.id == sequence_id))
    seq = result.scalar_one_or_none()
    if not seq:
        raise HTTPException(status_code=404, detail="Sequence not found")
    await db.delete(seq)
    await db.commit()
    return {"message": "Sequence deleted"}


# ─── Automation: Run sequence ─────────────────────────────────────────────────

async def _resolve_profile_ids(lead: Lead, sess: dict, job: dict) -> Lead:
    """
    If a lead has a linkedin_url but no profile/member IDs, look them up
    via the Voyager API and persist to the database.
    Modifies the lead object in-place and saves to DB.
    """
    if lead.linkedin_profile_id:
        return lead  # already have it

    if not lead.linkedin_url:
        return lead  # nothing to look up

    job["step"] = f"Looking up LinkedIn ID for {lead.name}..."
    print(f"[automation] resolving profile for {lead.name} ({lead.linkedin_url})", flush=True)

    ids = await resolve_lead_ids(
        linkedin_url=lead.linkedin_url,
        li_at=sess["li_at"],
        jsessionid=sess.get("jsessionid", "ajax:0"),
    )

    if ids:
        # Persist the IDs so we never need to look them up again
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Lead).where(Lead.id == lead.id))
            db_lead = result.scalar_one_or_none()
            if db_lead:
                db_lead.linkedin_profile_id = ids["linkedin_profile_id"]
                db_lead.linkedin_member_id = ids["linkedin_member_id"]
                db_lead.updated_at = datetime.utcnow()
                await db.commit()
        # Update the in-memory object too
        lead.linkedin_profile_id = ids["linkedin_profile_id"]
        lead.linkedin_member_id = ids["linkedin_member_id"]
        print(f"[automation] resolved {lead.name} → {ids['linkedin_profile_id']}", flush=True)
    else:
        print(f"[automation] could not resolve profile for {lead.name}", flush=True)

    return lead


async def _run_automation(job_id: str, lead_ids: List[str], sequence_id: str):
    """Background task: send LinkedIn connection requests + messages to all leads."""
    job = automation_jobs[job_id]
    job["status"] = "running"
    job["started_at"] = datetime.utcnow().isoformat()

    sess = load_session()
    if not sess:
        job["status"] = "failed"
        job["error"] = "No LinkedIn session — connect your account in Settings first"
        return

    async with AsyncSessionLocal() as db:
        seq_result = await db.execute(
            select(Sequence).where(Sequence.id == uuid.UUID(sequence_id))
        )
        sequence = seq_result.scalar_one_or_none()
        if not sequence:
            job["status"] = "failed"
            job["error"] = "Sequence not found"
            return

        leads_result = await db.execute(
            select(Lead).where(Lead.id.in_([uuid.UUID(lid) for lid in lead_ids]))
        )
        leads = list(leads_result.scalars().all())

    job["total"] = len(leads)
    job["done"] = 0
    job["sent"] = 0
    job["failed"] = 0
    job["results"] = []

    for lead in leads:
        job["current"] = lead.name

        # ── Step 1: Auto-resolve LinkedIn IDs if missing ──────────────────────
        if not lead.linkedin_profile_id and lead.linkedin_url:
            lead = await _resolve_profile_ids(lead, sess, job)

        lead_data = {
            "id": str(lead.id),
            "name": lead.name,
            "title": lead.title,
            "company": lead.company,
            "company_size": lead.company_size,
            "tech_stack": lead.tech_stack or [],
            "score_reason": lead.score_reason,
        }

        result_entry = {"lead_id": str(lead.id), "name": lead.name}

        try:
            if sequence.type == "connection_request":
                # ── Generate connection note ───────────────────────────────────
                note_template = sequence.connection_note_template
                if note_template and len(note_template) > 10:
                    first_name = (lead.name or "there").split()[0]
                    note = (
                        note_template
                        .replace("{{first_name}}", first_name)
                        .replace("{{company}}", lead.company or "your company")
                        [:300]
                    )
                else:
                    note = await generate_linkedin_connection_note(lead_data)

                if lead.linkedin_profile_id:
                    job["step"] = f"Sending connection request to {lead.name}..."
                    resp = await send_connection_request(
                        profile_id=lead.linkedin_profile_id,
                        note=note,
                        li_at=sess["li_at"],
                        jsessionid=sess.get("jsessionid", "ajax:0"),
                    )
                    if resp["success"]:
                        result_entry["status"] = "sent"
                        result_entry["content"] = note
                        job["sent"] += 1
                        await _log_outreach(str(lead.id), sequence_id, "connection_request", note, "sent")
                        await _update_lead_status(str(lead.id), "contacted")
                    else:
                        result_entry["status"] = "failed"
                        result_entry["error"] = resp.get("error", "Unknown error")
                        job["failed"] += 1
                        await _log_outreach(str(lead.id), sequence_id, "connection_request", note, "failed", resp.get("error"))
                else:
                    result_entry["status"] = "failed"
                    result_entry["content"] = note
                    result_entry["error"] = "Could not find LinkedIn profile — profile may be private or URL is invalid"
                    job["failed"] += 1

            elif sequence.type in ("follow_up_message", "final_message"):
                msg_template = sequence.message_template
                if msg_template and len(msg_template) > 10:
                    first_name = (lead.name or "there").split()[0]
                    message_text = (
                        msg_template
                        .replace("{{first_name}}", first_name)
                        .replace("{{company}}", lead.company or "your company")
                    )
                else:
                    message_text = await generate_linkedin_message(lead_data, sequence.type)

                if lead.linkedin_member_id:
                    job["step"] = f"Sending message to {lead.name}..."
                    resp = await send_message(
                        member_id=lead.linkedin_member_id,
                        message=message_text,
                        li_at=sess["li_at"],
                        jsessionid=sess.get("jsessionid", "ajax:0"),
                    )
                    if resp["success"]:
                        result_entry["status"] = "sent"
                        result_entry["content"] = message_text
                        job["sent"] += 1
                        await _log_outreach(str(lead.id), sequence_id, "message", message_text, "sent")
                        await _update_lead_status(str(lead.id), "contacted")
                    else:
                        result_entry["status"] = "failed"
                        result_entry["error"] = resp.get("error", "Unknown")
                        job["failed"] += 1
                        await _log_outreach(str(lead.id), sequence_id, "message", message_text, "failed", resp.get("error"))
                else:
                    result_entry["status"] = "failed"
                    result_entry["content"] = message_text
                    result_entry["error"] = "Could not find LinkedIn member ID — profile may be private"
                    job["failed"] += 1

        except Exception as e:
            result_entry["status"] = "error"
            result_entry["error"] = str(e)
            job["failed"] += 1

        job["done"] += 1
        job["results"].append(result_entry)

        # Human-paced delay between actions
        if job["done"] < len(leads):
            await human_delay(4.0, 9.0)

    job["status"] = "completed"
    job["current"] = None
    job["step"] = f"Done — {job['sent']} sent, {job['failed']} failed"


async def _log_outreach(lead_id: str, sequence_id: str, outreach_type: str, content: str, status: str, error: str = None):
    async with AsyncSessionLocal() as db:
        log = LinkedInOutreachLog(
            id=uuid.uuid4(),
            lead_id=uuid.UUID(lead_id),
            sequence_id=uuid.UUID(sequence_id),
            outreach_type=outreach_type,
            content=content,
            status=status,
            error=error,
            sent_at=datetime.utcnow() if status == "sent" else None,
        )
        db.add(log)
        await db.commit()


async def _update_lead_status(lead_id: str, status: str):
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Lead).where(Lead.id == uuid.UUID(lead_id)))
        lead = result.scalar_one_or_none()
        if lead:
            lead.status = status
            lead.updated_at = datetime.utcnow()
            await db.commit()


@router.post("/{sequence_id}/run")
async def run_sequence(
    sequence_id: uuid.UUID,
    request: RunSequenceRequest,
    background_tasks: BackgroundTasks,
):
    """Start a LinkedIn automation job: send to all selected leads."""
    sess = load_session()
    if not sess:
        raise HTTPException(
            status_code=400,
            detail="No LinkedIn session. Connect your account in Settings first.",
        )

    job_id = str(uuid.uuid4())
    lead_ids = [str(lid) for lid in request.lead_ids]

    automation_jobs[job_id] = {
        "status": "pending",
        "step": "Starting...",
        "sequence_id": str(sequence_id),
        "total": len(lead_ids),
        "done": 0,
        "sent": 0,
        "failed": 0,
        "current": None,
        "results": [],
    }

    background_tasks.add_task(
        _run_automation, job_id, lead_ids, str(sequence_id)
    )

    return {"job_id": job_id, "status": "pending", "total": len(lead_ids)}


@router.get("/jobs/{job_id}")
async def get_automation_job(job_id: str):
    if job_id not in automation_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return automation_jobs[job_id]


@router.get("/jobs/list/all")
async def list_automation_jobs():
    return [
        {"job_id": k, **{kk: vv for kk, vv in v.items() if kk != "results"}}
        for k, v in automation_jobs.items()
    ]
