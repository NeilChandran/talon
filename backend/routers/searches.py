"""Search-centric API — Origami in, Instantly out."""
import csv
import io
import os
import re
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Campaign, CampaignEnrollment, Lead, Search
from services.campaign_runner import campaign_jobs, run_campaign_job
from services.instantly_service import push_leads_batch
from services.linkedin_service import load_session
from services.outreach_templates import build_outreach_kit, personalize
from services.origami_service import parse_lead_count_from_prompt
from services.search_runner import run_search, search_jobs, sync_search_progress

router = APIRouter()


class CreateSearchBody(BaseModel):
    prompt: str


class InstantlyPushBody(BaseModel):
    lead_ids: Optional[List[uuid.UUID]] = None
    subject: Optional[str] = ""
    step1_body: Optional[str] = ""
    step2_body: Optional[str] = ""
    step3_body: Optional[str] = ""


class SendLinkedInBody(BaseModel):
    lead_ids: Optional[List[uuid.UUID]] = None
    connection_note_template: Optional[str] = None
    message_template: Optional[str] = None
    wait_days_after_accept: int = 1
    campaign_name: Optional[str] = None


class LinkedInTemplateBody(BaseModel):
    template: str


class AgentMessageBody(BaseModel):
    message: str


OUTREACH_LABELS = {
    "pending": "Ready",
    "linkedin_queued": "Ready",
    "connection_sent": "Ongoing",
    "accepted": "Ongoing",
    "dm_sent": "Completed",
    "completed": "Completed",
    "replied": "Replied",
    "stopped": "Stopped",
    "failed": "Failed",
    "instantly_queued": "Email queued",
    "new": "Ready",
}


def _progress_payload(s: Search) -> dict:
    target = parse_lead_count_from_prompt(s.prompt)
    leads = s.lead_count or 0
    msg = s.status_message or ""
    percent = 0
    step, mx = None, None
    m = re.search(r"step\s+(\d+)/(\d+)", msg, re.I)
    if m:
        step, mx = int(m.group(1)), int(m.group(2))
    if s.status == "completed":
        percent = 100
    elif s.status == "failed" or s.status == "needs_input":
        percent = min(90, int(100 * leads / max(1, target))) if target else 0
    elif s.status == "running":
        if step and mx:
            percent = min(92, int(100 * step / max(1, mx)))
        elif target and leads:
            percent = min(85, int(100 * leads / target))
        elif step:
            percent = min(50, step * 3)
        else:
            percent = 8
    label = msg or ("Complete" if s.status == "completed" else "Working…")
    return {
        "percent": percent,
        "label": label,
        "step": step,
        "max_steps": mx,
        "leads_found": leads,
        "target_leads": target,
        "status": s.status,
    }


async def _enrollment_status_map(db: AsyncSession, search_id: uuid.UUID) -> Dict[str, str]:
    cr = await db.execute(
        select(Campaign)
        .where(Campaign.search_id == search_id)
        .order_by(Campaign.created_at.desc())
        .limit(1)
    )
    camp = cr.scalar_one_or_none()
    if not camp:
        return {}
    er = await db.execute(
        select(CampaignEnrollment).where(CampaignEnrollment.campaign_id == camp.id)
    )
    return {str(e.lead_id): e.status for e in er.scalars().all()}


def _outreach_kit_for_search(s: Search) -> dict:
    tpl = (s.linkedin_message_template or "").strip()
    return build_outreach_kit(s.prompt, linkedin_template=tpl)


def _search_dict(s: Search, leads: Optional[list] = None) -> dict:
    job = search_jobs.get(str(s.id), {})
    outreach = job.get("outreach") or _outreach_kit_for_search(s)
    return {
        "id": str(s.id),
        "prompt": s.prompt,
        "origami_job_id": s.origami_job_id or "",
        "status": s.status,
        "status_message": s.status_message or "",
        "lead_count": s.lead_count or 0,
        "origami_table_url": s.origami_table_url or "",
        "linkedin_message_template": s.linkedin_message_template or outreach.get("linkedin_connection", ""),
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "leads": leads,
        "job": job,
        "outreach": outreach,
        "progress": _progress_payload(s),
    }


def _lead_dict(
    l: Lead,
    prompt: str = "",
    *,
    linkedin_template: str = "",
    enrollment_status: str = "",
) -> dict:
    sc = l.score if l.score is not None else (l.icp_score or 0)
    kit = build_outreach_kit(prompt, linkedin_template=linkedin_template)
    fn = l.first_name or (l.name or "there").split()[0] if l.name else "there"
    st = enrollment_status or l.sequence_status or "new"
    return {
        "id": str(l.id),
        "search_id": str(l.search_id) if l.search_id else None,
        "first_name": l.first_name or "",
        "last_name": l.last_name or "",
        "title": l.title or "",
        "company": l.company or "",
        "email": l.email or "",
        "linkedin_url": l.linkedin_url or "",
        "score": sc,
        "sequence_status": st,
        "linkedin_outreach_status": st,
        "linkedin_outreach_label": OUTREACH_LABELS.get(st, "Ready"),
        "created_at": l.created_at.isoformat() if l.created_at else None,
        "linkedin_message": personalize(
            kit["linkedin_connection"],
            first_name=fn,
            company=l.company or "",
            title=l.title or "",
        ),
        "email_preview": personalize(
            kit["email_step1"],
            first_name=fn,
            company=l.company or "",
            title=l.title or "",
        ),
    }


def _redis_available() -> bool:
    url = os.getenv("REDIS_URL", "").strip()
    if not url:
        return False
    try:
        import redis

        return bool(redis.from_url(url, socket_connect_timeout=1).ping())
    except Exception:
        return False


def _dispatch(
    search_id: uuid.UUID,
    prompt: str,
    background_tasks: BackgroundTasks,
    *,
    resume: bool = False,
):
    if _redis_available():
        try:
            from tasks import build_search_task

            build_search_task.delay(str(search_id), prompt, resume)
            search_jobs[str(search_id)] = {"status": "running", "step": "Queued…", "count": 0}
            return
        except Exception as e:
            print(f"[searches] Celery fallback: {e}", flush=True)
    background_tasks.add_task(run_search, search_id, prompt, resume=resume)


@router.post("")
@router.post("/")
async def create_search(
    body: CreateSearchBody,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(400, "Prompt required")
    if not os.getenv("ORIGAMI_API_KEY"):
        raise HTTPException(400, "Set ORIGAMI_API_KEY in .env")

    # Origami free tier allows one concurrent agent — avoid starting a doomed run
    running = await db.execute(
        select(Search).where(Search.status == "running").limit(1)
    )
    if running.scalar_one_or_none():
        raise HTTPException(
            409,
            "Another search is still running. Wait for it to finish (Origami allows 1 agent at a time on your plan).",
        )

    s = Search(
        id=uuid.uuid4(),
        prompt=prompt,
        status="running",
        status_message="Finding leads...",
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)

    _dispatch(s.id, prompt, background_tasks)
    return _search_dict(s, leads=[])


@router.get("/recent")
async def recent_searches(limit: int = 12, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Search).order_by(Search.created_at.desc()).limit(limit))
    return [
        {
            "id": str(s.id),
            "prompt": s.prompt,
            "status": s.status,
            "status_message": s.status_message,
            "lead_count": s.lead_count or 0,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in result.scalars().all()
    ]


@router.get("/{search_id}")
async def get_search(search_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(Search).where(Search.id == search_id))
    s = r.scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Search not found")

    if s.status in ("running", "needs_input") and s.origami_job_id:
        try:
            await sync_search_progress(search_id)
            await db.refresh(s)
        except Exception as e:
            print(f"[searches] sync on read: {e}", flush=True)

    lr = await db.execute(
        select(Lead).where(Lead.search_id == search_id).order_by(Lead.created_at.asc())
    )
    enroll = await _enrollment_status_map(db, search_id)
    tpl = (s.linkedin_message_template or "").strip()
    leads = [
        _lead_dict(
            l,
            s.prompt,
            linkedin_template=tpl,
            enrollment_status=enroll.get(str(l.id), ""),
        )
        for l in lr.scalars().all()
    ]
    return _search_dict(s, leads=leads)


@router.get("/{search_id}/export.csv")
async def export_csv(search_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    lr = await db.execute(select(Lead).where(Lead.search_id == search_id))
    rows = list(lr.scalars().all())
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["#", "First Name", "Last Name", "Title", "Company", "Email", "LinkedIn", "Score"])
    for i, l in enumerate(rows, 1):
        sc = l.score if l.score is not None else (l.icp_score or 0)
        w.writerow([i, l.first_name, l.last_name, l.title, l.company, l.email, l.linkedin_url, sc])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="search-{search_id}.csv"'},
    )


@router.post("/{search_id}/refresh")
async def refresh_search_leads(
    search_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Re-pull rows from Origami (fixes names) and update Talon table."""
    from services.search_runner import sync_search_progress

    r = await db.execute(select(Search).where(Search.id == search_id))
    s = r.scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Search not found")
    if not s.origami_table_id and not s.origami_job_id:
        raise HTTPException(400, "No Origami table linked yet — wait for search to finish")

    n = await sync_search_progress(search_id)
    await db.refresh(s)
    return {"ok": True, "lead_count": s.lead_count or n or 0, "message": s.status_message}


@router.patch("/{search_id}/linkedin-template")
async def set_linkedin_template(
    search_id: uuid.UUID,
    body: LinkedInTemplateBody,
    db: AsyncSession = Depends(get_db),
):
    tpl = body.template.strip()
    if not tpl:
        raise HTTPException(400, "Template required")
    r = await db.execute(select(Search).where(Search.id == search_id))
    s = r.scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Search not found")
    s.linkedin_message_template = tpl[:2000]
    await db.commit()
    kit = _outreach_kit_for_search(s)
    search_jobs[str(s.id)] = {**search_jobs.get(str(s.id), {}), "outreach": kit}
    return {"ok": True, "outreach": kit}


@router.post("/{search_id}/agent-message")
async def search_agent_message(
    search_id: uuid.UUID,
    body: AgentMessageBody,
    db: AsyncSession = Depends(get_db),
):
    """Set LinkedIn connection copy from chat — e.g. paste the message you want for step 1."""
    msg = body.message.strip()
    if not msg:
        raise HTTPException(400, "Message required")
    r = await db.execute(select(Search).where(Search.id == search_id))
    s = r.scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Search not found")

    lower = msg.lower()
    if lower.startswith("linkedin:") or lower.startswith("message:"):
        tpl = msg.split(":", 1)[1].strip()
    elif "linkedin message" in lower or "connection note" in lower:
        tpl = msg
    else:
        tpl = msg

    s.linkedin_message_template = tpl[:2000]
    await db.commit()
    kit = _outreach_kit_for_search(s)
    return {
        "ok": True,
        "reply": "Updated your LinkedIn connection note for all founders in this list. Click a row under LinkedIn Outreach to preview step 1.",
        "outreach": kit,
    }


@router.post("/{search_id}/resume")
async def resume_search(
    search_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Continue a stuck or needs_input search (re-polls Origami or auto-answers questions)."""
    r = await db.execute(select(Search).where(Search.id == search_id))
    s = r.scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Search not found")
    if not os.getenv("ORIGAMI_API_KEY"):
        raise HTTPException(400, "Set ORIGAMI_API_KEY in .env")

    s.status = "running"
    s.status_message = "Resuming..."
    await db.commit()

    _dispatch(search_id, s.prompt, background_tasks, resume=True)
    return {"ok": True, "id": str(search_id), "status": "running"}


@router.post("/{search_id}/send/linkedin")
async def send_linkedin_from_search(
    search_id: uuid.UUID,
    body: SendLinkedInBody,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Launch LinkedIn outreach inside Talon (list from Origami, send via Talon)."""
    sess = load_session() or {}
    if not sess.get("connected"):
        raise HTTPException(400, "Connect LinkedIn in Settings before sending")

    r = await db.execute(select(Search).where(Search.id == search_id))
    s = r.scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Search not found")

    q = select(Lead).where(Lead.search_id == search_id)
    if body.lead_ids:
        q = q.where(Lead.id.in_(body.lead_ids))
    leads = list((await db.execute(q)).scalars().all())
    leads = [l for l in leads if (l.linkedin_url or "").strip()]
    if not leads:
        raise HTTPException(400, "No leads with LinkedIn URLs to message")

    kit = _outreach_kit_for_search(s)
    conn_tpl = (body.connection_note_template or s.linkedin_message_template or kit["linkedin_connection"])[:300]
    msg_tpl = body.message_template or kit.get("email_step1", "")[:2000]
    if not body.message_template:
        msg_tpl = (
            "Hey {{first_name}}, thanks for connecting!\n\n"
            "Would love to hear what you're building at {{company}} — open to a quick chat?"
        )

    camp = Campaign(
        id=uuid.uuid4(),
        search_id=search_id,
        name=(body.campaign_name or s.prompt[:80] + " — Talon")[:255],
        connection_note_template=conn_tpl,
        message_template=msg_tpl,
        wait_days_after_accept=body.wait_days_after_accept,
        is_active=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(camp)

    enrolled = 0
    for lead in leads:
        fn = lead.first_name or (lead.name or "there").split()[0]
        note = personalize(conn_tpl, first_name=fn, company=lead.company or "", title=lead.title or "")
        msg = personalize(msg_tpl, first_name=fn, company=lead.company or "", title=lead.title or "")
        db.add(
            CampaignEnrollment(
                id=uuid.uuid4(),
                campaign_id=camp.id,
                lead_id=lead.id,
                status="pending",
                connection_note=note[:300],
                follow_up_message=msg,
            )
        )
        lead.sequence_status = "linkedin_queued"
        enrolled += 1

    await db.commit()

    job_id = str(uuid.uuid4())
    campaign_jobs[job_id] = {
        "status": "pending",
        "campaign_id": str(camp.id),
        "total": enrolled,
        "done": 0,
        "sent": 0,
        "failed": 0,
        "current": None,
        "step": "Sending via Talon…",
    }
    background_tasks.add_task(run_campaign_job, job_id, str(camp.id), None)

    return {
        "campaign_id": str(camp.id),
        "job_id": job_id,
        "enrolled": enrolled,
        "status": "launching",
        "message": f"Sending {enrolled} LinkedIn sequences from Talon (list powered by Origami)",
    }


@router.post("/{search_id}/instantly")
async def push_instantly(
    search_id: uuid.UUID,
    body: InstantlyPushBody,
    db: AsyncSession = Depends(get_db),
):
    campaign_id = os.getenv("INSTANTLY_CAMPAIGN_ID", "").strip()
    if not campaign_id:
        from services.app_settings import get_settings

        campaign_id = (get_settings().get("instantly_campaign_id") or "").strip()
    if not campaign_id:
        raise HTTPException(400, "Set INSTANTLY_CAMPAIGN_ID in .env or Settings")

    q = select(Lead).where(Lead.search_id == search_id)
    if body.lead_ids:
        q = q.where(Lead.id.in_(body.lead_ids))
    lr = await db.execute(q)
    leads = lr.scalars().all()

    payload = [
        {
            "first_name": l.first_name or (l.name or "").split()[0] if l.name else "",
            "last_name": l.last_name or "",
            "company": l.company or "",
            "email": l.email or "",
        }
        for l in leads
    ]
    result = await push_leads_batch(payload, campaign_id)

    if result.get("pushed"):
        for l in leads:
            if l.email:
                l.sequence_status = "instantly_queued"
        await db.commit()

    return result
