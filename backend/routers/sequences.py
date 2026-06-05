import asyncio
import uuid
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from database import get_db
from schemas import RunSequenceRequest, SequenceCreate, SequenceResponse, SequenceUpdate
from services.claude_service import (
    generate_linkedin_connection_note,
    generate_linkedin_message,
)
from services.linkedin_service import (
    human_delay,
    load_session,
    resolve_lead_ids,
    send_connection_request_from_session,
    send_message_from_session,
    validate_session,
)
from services.send_cap import get_remaining, increment_count, is_capped, get_status as cap_status
from services.reply_service import check_replies_for_leads
from store import Record
from user_store import UserStore, get_store

router = APIRouter()

automation_jobs: Dict[str, Any] = {}


def _sequence_response(r: Record) -> SequenceResponse:
    return SequenceResponse(
        id=uuid.UUID(str(r.id)),
        name=r.name,
        type=r.type,
        connection_note_template=r.connection_note_template,
        message_template=r.message_template,
        subject_template=r.subject_template,
        body_template=r.body_template,
        delay_days=r.delay_days or 0,
        created_at=r.created_at,
    )


@router.get("/", response_model=List[SequenceResponse])
async def get_sequences(db: UserStore = Depends(get_db)):
    rows = await db.list_sequences()
    return [_sequence_response(r) for r in rows]


@router.get("/send-cap")
async def get_send_cap_status_inline():
    """Today's LinkedIn daily send cap status (inline route, before /{sequence_id})."""
    return cap_status()


@router.post("/check-replies")
async def check_replies_inline(db: UserStore = Depends(get_db)):
    """Check LinkedIn inbox for replies from contacted leads (inline route, before /{sequence_id})."""
    sess = load_session()
    if not sess:
        raise HTTPException(
            status_code=400,
            detail="No LinkedIn session. Connect your account in Settings first.",
        )
    contacted_leads = await db.list_leads_by_status("contacted", require_member_id=True)
    if not contacted_leads:
        return {"checked": 0, "replied": 0, "replied_names": [], "message": "No contacted leads with LinkedIn IDs to check."}
    return await check_replies_for_leads(
        leads=contacted_leads,
        li_at=sess["li_at"],
        jsessionid=sess.get("jsessionid", "ajax:0"),
        bcookie=sess.get("bcookie", ""),
        bscookie=sess.get("bscookie", ""),
    )


@router.get("/{sequence_id}", response_model=SequenceResponse)
async def get_sequence(sequence_id: uuid.UUID, db: UserStore = Depends(get_db)):
    seq = await db.select_one("sequences", sequence_id)
    if not seq:
        raise HTTPException(status_code=404, detail="Sequence not found")
    return _sequence_response(seq)


@router.post("/", response_model=SequenceResponse)
async def create_sequence(sequence: SequenceCreate, db: UserStore = Depends(get_db)):
    row = await db.insert(
        "sequences",
        {
            "id": str(uuid.uuid4()),
            **sequence.model_dump(),
            "created_at": datetime.utcnow().isoformat(),
        },
    )
    return _sequence_response(row)


@router.put("/{sequence_id}", response_model=SequenceResponse)
async def update_sequence(
    sequence_id: uuid.UUID,
    sequence_update: SequenceUpdate,
    db: UserStore = Depends(get_db),
):
    seq = await db.select_one("sequences", sequence_id)
    if not seq:
        raise HTTPException(status_code=404, detail="Sequence not found")

    patch = sequence_update.model_dump(exclude_unset=True)
    row = await db.update("sequences", sequence_id, patch)
    if not row:
        raise HTTPException(status_code=404, detail="Sequence not found")
    return _sequence_response(row)


@router.delete("/{sequence_id}")
async def delete_sequence(sequence_id: uuid.UUID, db: UserStore = Depends(get_db)):
    seq = await db.select_one("sequences", sequence_id)
    if not seq:
        raise HTTPException(status_code=404, detail="Sequence not found")
    await db.delete_where("sequences", {"id": str(sequence_id)})
    return {"message": "Sequence deleted"}


async def _resolve_profile_ids(lead: Record, sess: dict, job: dict) -> Record:
    if lead.linkedin_profile_id:
        return lead

    if not lead.linkedin_url:
        return lead

    job["step"] = f"Looking up LinkedIn ID for {lead.name}..."
    print(f"[automation] resolving profile for {lead.name} ({lead.linkedin_url})", flush=True)

    ids = await resolve_lead_ids(
        linkedin_url=lead.linkedin_url,
        li_at=sess["li_at"],
        jsessionid=sess.get("jsessionid", "ajax:0"),
        bcookie=sess.get("bcookie", ""),
        bscookie=sess.get("bscookie", ""),
    )

    if ids:
        db = get_store()
        await db.update_lead(
            lead.id,
            linkedin_profile_id=ids["linkedin_profile_id"],
            linkedin_member_id=ids["linkedin_member_id"],
        )
        lead.linkedin_profile_id = ids["linkedin_profile_id"]
        lead.linkedin_member_id = ids["linkedin_member_id"]
        print(f"[automation] resolved {lead.name} → {ids['linkedin_profile_id']}", flush=True)
    else:
        print(f"[automation] could not resolve profile for {lead.name}", flush=True)

    return lead


async def _run_automation(job_id: str, lead_ids: List[str], sequence_id: str):
    job = automation_jobs[job_id]
    job["status"] = "running"
    job["started_at"] = datetime.utcnow().isoformat()

    sess = load_session()
    if not sess:
        job["status"] = "failed"
        job["error"] = "No LinkedIn session — connect your account in Settings first"
        return

    job["step"] = "Verifying LinkedIn session..."
    from services.linkedin_service import _extra_cookies_from_session, save_session

    check = await validate_session(
        sess["li_at"],
        sess.get("jsessionid", "ajax:0"),
        sess.get("bcookie", ""),
        sess.get("bscookie", ""),
        _extra_cookies_from_session(sess),
    )
    if not check.get("valid"):
        job["status"] = "failed"
        job["error"] = check.get("error", "LinkedIn session expired — go to Settings and sign in again")
        return
    if check.get("jsessionid") and check["jsessionid"] != sess.get("jsessionid"):
        save_session(
            sess["li_at"],
            check["jsessionid"],
            {"name": check.get("name", sess.get("name")), "headline": check.get("headline", "")},
            bcookie=sess.get("bcookie", ""),
            bscookie=sess.get("bscookie", ""),
            extra=_extra_cookies_from_session(sess),
        )
        sess = load_session() or sess

    db = get_store()
    sequence = await db.select_one("sequences", sequence_id)
    if not sequence:
        job["status"] = "failed"
        job["error"] = "Sequence not found"
        return

    leads = await db.get_leads_by_ids(lead_ids)

    job["total"] = len(leads)
    job["done"] = 0
    job["sent"] = 0
    job["failed"] = 0
    job["results"] = []

    for lead in leads:
        job["current"] = lead.name

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
                if is_capped():
                    remaining_leads = len(leads) - job["done"]
                    job["status"] = "paused"
                    job["step"] = f"Daily LinkedIn limit reached (20/day). {remaining_leads} lead(s) not sent — run again tomorrow."
                    job["error"] = f"Daily LinkedIn connection limit reached. {job['sent']} sent today. Remaining {remaining_leads} leads were skipped — run again tomorrow."
                    job["results"].append({
                        "lead_id": str(lead.id),
                        "name": lead.name,
                        "status": "skipped",
                        "error": "Daily cap reached",
                    })
                    for skip_lead in leads[leads.index(lead) + 1:]:
                        job["results"].append({
                            "lead_id": str(skip_lead.id),
                            "name": skip_lead.name,
                            "status": "skipped",
                            "error": "Daily cap reached",
                        })
                    job["done"] = len(leads)
                    return

                remaining = get_remaining()
                job["step"] = f"Sending to {lead.name}... ({remaining} sends left today)"

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
                    resp = await send_connection_request_from_session(sess, lead.linkedin_profile_id, note)
                    if resp["success"]:
                        result_entry["status"] = "sent"
                        result_entry["content"] = note
                        job["sent"] += 1
                        increment_count()
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
                    result_entry["error"] = "Could not resolve LinkedIn profile ID — profile may be deleted, private, or the URL is invalid"
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
                    resp = await send_message_from_session(sess, lead.linkedin_member_id, message_text)
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

        if job["done"] < len(leads):
            await human_delay(4.0, 9.0)

    job["status"] = "completed"
    job["current"] = None
    job["step"] = f"Done — {job['sent']} sent, {job['failed']} failed"


async def _log_outreach(lead_id: str, sequence_id: str, outreach_type: str, content: str, status: str, error: str = None):
    db = get_store()
    await db.insert_outreach_log({
        "lead_id": lead_id,
        "sequence_id": sequence_id,
        "outreach_type": outreach_type,
        "content": content,
        "status": status,
        "error": error,
        "sent_at": datetime.utcnow().isoformat() if status == "sent" else None,
    })


async def _update_lead_status(lead_id: str, status: str):
    db = get_store()
    await db.update_lead(lead_id, status=status)


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
