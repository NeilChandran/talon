"""Search-centric API — Origami in, Instantly out."""
import asyncio
import csv
import io
import os
import re
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from database import get_db
from store import Record
from user_store import UserStore
from services.campaign_runner import campaign_jobs, run_campaign_job
from services.instantly_service import push_leads_batch
from services.linkedin_service import load_session
from services.outreach_templates import (
    build_outreach_kit,
    fit_connection_note,
    note_has_wrong_audience,
    personalize,
    personalize_connection,
)
from services.origami_service import parse_lead_count_from_prompt, user_facing_message
from services.origami_service import ensure_linkedin_drafts, parse_agent_run_ids
from services.search_runner import (
    run_origami_launch_job,
    run_search,
    search_jobs,
    sync_origami_drafts,
    sync_search_progress,
)

router = APIRouter()

# Throttle Origami sync on GET — frontend polls every few seconds while running.
_sync_on_read_at: Dict[str, float] = {}
SYNC_ON_READ_SEC = 5.0
SYNC_ON_READ_TIMEOUT_SEC = 12.0


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
    "drafted": "Drafted",
}

_OUTREACH_DRAFT_TRIGGERS = (
    "reach out",
    "send linkedin",
    "linkedin message",
    "connection note",
    "draft",
    "message them",
    "outreach",
    "send message",
    "connect on linkedin",
    "linkedin outreach",
)


def _effective_status(s: Record, lead_count: int) -> str:
    """Leads on disk = usable list even if background research errored."""
    if (s.status or "") == "failed" and lead_count > 0:
        return "completed"
    return s.status or "running"


def _is_outreach_draft_command(msg: str) -> bool:
    lower = msg.lower().strip()
    return any(t in lower for t in _OUTREACH_DRAFT_TRIGGERS)


def _extract_linkedin_template(msg: str) -> str:
    lower = msg.lower().strip()
    if lower.startswith("linkedin:") or lower.startswith("message:"):
        return msg.split(":", 1)[1].strip()
    if len(msg) > 90 or "{{" in msg or lower.startswith("hi "):
        return msg.strip()
    return ""


async def _draft_all_leads(db: UserStore, search_id: uuid.UUID) -> int:
    leads = await db.list_leads_by_search(search_id)
    for lead in leads:
        await db.update_lead(lead.id, sequence_status="drafted")
    return len(leads)


def _parse_dt(val: Any) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, str):
        return val
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


def _progress_payload(s: Record) -> dict:
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


def _enrollment_dict(enr: Record, lead: Optional[Record]) -> dict:
    return {
        "id": str(enr.id),
        "campaign_id": str(enr.campaign_id),
        "lead_id": str(enr.lead_id),
        "status": enr.status or "drafted",
        "connection_note": enr.connection_note or "",
        "follow_up_message": enr.follow_up_message or "",
        "connection_sent_at": _parse_dt(enr.connection_sent_at),
        "accepted_at": _parse_dt(enr.accepted_at),
        "dm_sent_at": _parse_dt(enr.dm_sent_at),
        "stopped_reason": enr.stopped_reason,
        "last_error": enr.last_error,
        "name": (
            f"{lead.first_name or ''} {lead.last_name or ''}".strip()
            if lead
            else None
        )
        or (lead.name if lead else None),
        "title": lead.title if lead else None,
        "company": lead.company if lead else None,
        "linkedin_url": lead.linkedin_url if lead else None,
        "lead_status": lead.status if lead else None,
        "scheduled_at": _parse_dt(getattr(enr, "scheduled_at", None)),
        "origami_send_status": getattr(enr, "origami_send_status", None) or None,
    }


async def _enrollment_status_map(db: UserStore, search_id: uuid.UUID) -> Dict[str, str]:
    camp = await db.latest_campaign_for_search(search_id)
    if not camp:
        return {}
    enrollments = await db.list_enrollments(camp.id)
    return {str(e.lead_id): e.status for e in enrollments}


def _outreach_kit_for_search(s: Record) -> dict:
    tpl = (s.linkedin_message_template or "").strip()
    return build_outreach_kit(s.prompt, linkedin_template=tpl)


def _search_dict(s: Record, leads: Optional[list] = None) -> dict:
    job = search_jobs.get(str(s.id), {})
    outreach = job.get("outreach") or _outreach_kit_for_search(s)
    lead_count = len(leads) if leads is not None else (s.lead_count or 0)
    status = _effective_status(s, lead_count)
    msg = user_facing_message(s.status_message or "")
    if status == "completed" and lead_count > 0 and (s.status or "") == "failed":
        msg = f"{lead_count} leads ready — LinkedIn notes drafted and ready to go."
    return {
        "id": str(s.id),
        "prompt": s.prompt,
        "origami_job_id": s.origami_job_id or "",
        "status": status,
        "status_message": msg,
        "lead_count": s.lead_count or 0,
        "origami_table_url": s.origami_table_url or "",
        "linkedin_message_template": s.linkedin_message_template or outreach.get("linkedin_connection", ""),
        "created_at": _parse_dt(s.created_at),
        "leads": leads,
        "job": job,
        "outreach": outreach,
        "progress": _progress_payload(s),
    }


def _lead_dict(
    l: Record,
    prompt: str = "",
    *,
    linkedin_template: str = "",
    enrollment_status: str = "",
) -> dict:
    sc = l.score if l.score is not None else (l.icp_score or 0)
    kit = build_outreach_kit(prompt, linkedin_template=linkedin_template)
    fn = l.first_name or (l.name or "there").split()[0] if l.name else "there"
    origami_draft = (getattr(l, "linkedin_draft", None) or "").strip()
    if origami_draft and note_has_wrong_audience(origami_draft, prompt):
        origami_draft = ""
    li_url = (l.linkedin_url or "").strip()
    st = enrollment_status or l.sequence_status or "new"
    if st == "failed" and li_url:
        st = "drafted" if origami_draft else "new"
    elif origami_draft:
        st = enrollment_status or "drafted"
    elif st == "drafted":
        st = enrollment_status or "new"
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
        "created_at": _parse_dt(l.created_at),
        "linkedin_message": fit_connection_note(
            origami_draft
            or personalize(
                linkedin_template or kit["linkedin_connection"],
                first_name=fn,
                company=l.company or "",
                title=l.title or "",
            )
        ),
        "follow_up_message": (getattr(l, "follow_up_draft", None) or "").strip() or None,
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


def _celery_worker_available() -> bool:
    """Only queue to Celery when a worker is actually running (avoids stuck 'Queued…')."""
    if os.getenv("USE_CELERY", "").strip() not in ("1", "true", "yes"):
        return False
    if not _redis_available():
        return False
    try:
        from celery_app import celery_app

        ping = celery_app.control.inspect(timeout=1.0).ping()
        return bool(ping)
    except Exception:
        return False


async def _fail_stale_running(db: UserStore) -> None:
    """Mark abandoned runs failed so new prompts aren't blocked."""
    running = await db.get_running_search()
    if not running:
        return
    job = (running.origami_job_id or "").strip()
    if not job:
        created = running.created_at
        if not created:
            return
        try:
            from datetime import datetime, timezone

            if isinstance(created, str):
                ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
            else:
                ts = created
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60
            if age_min < 3:
                return
        except Exception:
            return
        await db.update_search(
            running.id,
            status="failed",
            status_message="Search didn't finish — start a new one",
        )
        return
    created = running.created_at
    if not created:
        return
    try:
        from datetime import datetime, timezone

        if isinstance(created, str):
            ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
        else:
            ts = created
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60
        leads = running.lead_count or 0
        if age_min > 5 and leads == 0:
            await db.update_search(
                running.id,
                status="failed",
                status_message="Search stalled — delete and try again",
            )
        elif age_min > 20:
            await db.update_search(
                running.id,
                status="failed",
                status_message="Search timed out — start a new one",
            )
    except Exception:
        pass


def _dispatch(
    search_id: uuid.UUID,
    prompt: str,
    *,
    resume: bool = False,
):
    """Start Origami immediately — never leave searches stuck in Celery queue."""
    if _celery_worker_available():
        try:
            from tasks import build_search_task

            build_search_task.delay(str(search_id), prompt, resume)
            search_jobs[str(search_id)] = {"status": "running", "step": "Queued…", "count": 0}
            return
        except Exception as e:
            print(f"[searches] Celery fallback: {e}", flush=True)
    asyncio.create_task(run_search(search_id, prompt, resume=resume))


@router.post("")
@router.post("/")
async def create_search(
    body: CreateSearchBody,
    background_tasks: BackgroundTasks,
    db: UserStore = Depends(get_db),
):
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(400, "Prompt required")
    if not os.getenv("ORIGAMI_API_KEY"):
        raise HTTPException(400, "Set ORIGAMI_API_KEY in .env")

    from services.origami_service import release_research_capacity

    await release_research_capacity()
    await _fail_stale_running(db)
    running = await db.get_running_search()
    if running and (running.origami_job_id or "").strip():
        raise HTTPException(
            409,
            "Another search is still running. Wait for it to finish or delete it from Workspaces.",
        )
    if running:
        _dispatch(uuid.UUID(str(running.id)), running.prompt, resume=True)

    s = await db.create_search(prompt)
    _dispatch(uuid.UUID(str(s.id)), prompt)
    return _search_dict(s, leads=[])


@router.delete("/{search_id}")
async def delete_search(search_id: uuid.UUID, db: UserStore = Depends(get_db)):
    sid = str(search_id)
    if not await db.delete_search(search_id):
        raise HTTPException(404, "Search not found")
    search_jobs.pop(sid, None)
    return {"ok": True, "id": sid, "deleted": True}


@router.get("/recent")
async def recent_searches(limit: int = 50, db: UserStore = Depends(get_db)):
    rows = await db.list_recent_searches(limit)
    return [
        {
            "id": str(s.id),
            "prompt": s.prompt,
            "status": s.status,
            "status_message": user_facing_message(s.status_message or ""),
            "lead_count": s.lead_count or 0,
            "created_at": _parse_dt(s.created_at),
        }
        for s in rows
    ]


@router.get("/{search_id}")
async def get_search(search_id: uuid.UUID, db: UserStore = Depends(get_db)):
    s = await db.get_search(search_id)
    if not s:
        raise HTTPException(404, "Search not found")

    if s.status in ("running", "needs_input") and s.origami_job_id:
        sid = str(search_id)
        now = time.time()
        if now - _sync_on_read_at.get(sid, 0) >= SYNC_ON_READ_SEC:
            _sync_on_read_at[sid] = now
            try:
                await asyncio.wait_for(
                    sync_search_progress(search_id),
                    timeout=SYNC_ON_READ_TIMEOUT_SEC,
                )
                s = await db.get_search(search_id) or s
            except asyncio.TimeoutError:
                print(f"[searches] sync on read timeout: {search_id}", flush=True)
            except Exception as e:
                print(f"[searches] sync on read: {e}", flush=True)

    lead_rows = await db.list_leads_by_search(search_id)
    needs_profile_sync = lead_rows and s.origami_table_id and any(
        not (l.linkedin_url or "").strip()
        or (l.sequence_status or "") == "failed"
        for l in lead_rows
    )
    if lead_rows and s.origami_table_id and (
        _effective_status(s, len(lead_rows)) == "completed" or needs_profile_sync
    ):
        try:
            await sync_origami_drafts(search_id)
            lead_rows = await db.list_leads_by_search(search_id)
        except Exception as e:
            print(f"[searches] origami draft sync: {e}", flush=True)
    try:
        enroll = await _enrollment_status_map(db, search_id)
    except Exception as e:
        print(f"[searches] enrollment map: {e}", flush=True)
        enroll = {}
    tpl = (s.linkedin_message_template or "").strip()
    leads = [
        _lead_dict(
            l,
            s.prompt,
            linkedin_template=tpl,
            enrollment_status=enroll.get(str(l.id), ""),
        )
        for l in lead_rows
    ]
    return _search_dict(s, leads=leads)


@router.get("/{search_id}/export.csv")
async def export_csv(search_id: uuid.UUID, db: UserStore = Depends(get_db)):
    rows = await db.list_leads_by_search(search_id)
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
async def refresh_search_leads(search_id: uuid.UUID, db: UserStore = Depends(get_db)):
    s = await db.get_search(search_id)
    if not s:
        raise HTTPException(404, "Search not found")
    if not s.origami_table_id and not s.origami_job_id:
        raise HTTPException(400, "No Origami table linked yet — wait for search to finish")

    n = await sync_search_progress(search_id)
    s = await db.get_search(search_id) or s
    return {"ok": True, "lead_count": s.lead_count or n or 0, "message": s.status_message}


@router.patch("/{search_id}/linkedin-template")
async def set_linkedin_template(
    search_id: uuid.UUID,
    body: LinkedInTemplateBody,
    db: UserStore = Depends(get_db),
):
    tpl = body.template.strip()
    if not tpl:
        raise HTTPException(400, "Template required")
    s = await db.get_search(search_id)
    if not s:
        raise HTTPException(404, "Search not found")
    s = await db.update_search(search_id, linkedin_message_template=tpl[:2000]) or s
    kit = _outreach_kit_for_search(s)
    search_jobs[str(s.id)] = {**search_jobs.get(str(s.id), {}), "outreach": kit}
    return {"ok": True, "outreach": kit}


@router.post("/{search_id}/agent-message")
async def search_agent_message(
    search_id: uuid.UUID,
    body: AgentMessageBody,
    db: UserStore = Depends(get_db),
):
    msg = body.message.strip()
    if not msg:
        raise HTTPException(400, "Message required")
    s = await db.get_search(search_id)
    if not s:
        raise HTTPException(404, "Search not found")

    leads = await db.list_leads_by_search(search_id)
    if not leads:
        return {
            "ok": True,
            "reply": "Your list is still building — check the table on the right in a moment.",
            "outreach": _outreach_kit_for_search(s),
        }

    custom_tpl = _extract_linkedin_template(msg)
    if custom_tpl:
        s = await db.update_search(search_id, linkedin_message_template=custom_tpl[:2000]) or s

    if _is_outreach_draft_command(msg) or custom_tpl:
        kit = _outreach_kit_for_search(s)
        tpl = (s.linkedin_message_template or custom_tpl or "").strip()
        agent_id, _ = parse_agent_run_ids(s.origami_job_id or "")
        table_id = s.origami_table_id or ""
        drafted = 0
        if agent_id and table_id:
            try:
                await ensure_linkedin_drafts(agent_id, table_id, template=tpl)
                drafted = await sync_origami_drafts(search_id)
            except Exception as e:
                print(f"[searches] origami draft request: {e}", flush=True)
        if drafted:
            reply = (
                f"Origami is drafting LinkedIn messages for {drafted} "
                f"{'founder' if drafted == 1 else 'leads'} — check the Origami table "
                "for LinkedIn Message Draft columns, then click any row here to preview."
            )
        elif agent_id and table_id:
            reply = (
                "Sent your message style to Origami — it will add LinkedIn Message Draft "
                "columns to the table. Refresh in a moment, then click a row to preview."
            )
        else:
            reply = (
                "Saved your LinkedIn message template. Re-run the search to draft messages in Origami."
            )
        return {
            "ok": True,
            "reply": reply,
            "outreach": kit,
            "drafted_count": drafted,
        }

    kit = _outreach_kit_for_search(s)
    return {
        "ok": True,
        "reply": (
            "Try: “reach out on LinkedIn” to draft connection notes for everyone in the table, "
            "or paste your note (use {{first_name}}, {{company}})."
        ),
        "outreach": kit,
    }


@router.post("/{search_id}/resume")
async def resume_search(
    search_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: UserStore = Depends(get_db),
):
    s = await db.get_search(search_id)
    if not s:
        raise HTTPException(404, "Search not found")
    if not os.getenv("ORIGAMI_API_KEY"):
        raise HTTPException(400, "Set ORIGAMI_API_KEY in .env")

    from services.origami_service import release_research_capacity, user_facing_message

    sid = str(search_id)
    if search_jobs.get(sid, {}).get("status") == "running":
        return {"ok": True, "id": sid, "status": "running", "already_running": True}

    await release_research_capacity()
    fresh = s.status in ("failed", "needs_input") or not (s.origami_job_id or "").strip()
    if fresh:
        await db.update_search(
            search_id,
            status="running",
            status_message="Starting search…",
            origami_job_id="",
        )
        _dispatch(search_id, s.prompt, resume=False)
    else:
        await db.update_search(search_id, status="running", status_message="Resuming…")
        _dispatch(search_id, s.prompt, resume=True)
    return {"ok": True, "id": str(search_id), "status": "running"}


@router.post("/{search_id}/campaign/prepare")
async def prepare_search_campaign(
    search_id: uuid.UUID,
    db: UserStore = Depends(get_db),
):
    """Create or refresh a draft campaign — every lead gets personalized step 1 + 2."""
    s = await db.get_search(search_id)
    if not s:
        raise HTTPException(404, "Search not found")

    if s.origami_table_id:
        try:
            await sync_origami_drafts(search_id)
        except Exception as e:
            print(f"[searches] prepare origami sync: {e}", flush=True)

    leads = [
        l
        for l in await db.list_leads_by_search(search_id)
        if (l.linkedin_url or "").strip()
    ]
    if not leads:
        raise HTTPException(400, "No leads with LinkedIn URLs in this list")

    kit = _outreach_kit_for_search(s)
    conn_tpl = s.linkedin_message_template or kit["linkedin_connection"]
    msg_tpl = kit.get("linkedin_follow_up") or kit.get("email_step1", "")
    now = datetime.utcnow().isoformat()

    camp = await db.latest_campaign_for_search(search_id)
    if not camp:
        camp = await db.raw.insert(
            "campaigns",
            {
                "id": str(uuid.uuid4()),
                "search_id": str(search_id),
                "name": (s.prompt[:80] + " — Talon")[:255],
                "connection_note_template": conn_tpl,
                "message_template": msg_tpl,
                "wait_days_after_accept": 1,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
        )
    else:
        await db.raw.update(
            "campaigns",
            camp.id,
            {
                "connection_note_template": conn_tpl,
                "message_template": msg_tpl,
                "updated_at": now,
            },
        )

    def _lid(val: Any) -> str:
        return str(val).replace("-", "").lower()

    existing = await db.list_enrollments(camp.id)
    # Drop stale duplicate enrollments (same lead enrolled multiple times).
    seen: Dict[str, Record] = {}
    for enr in sorted(existing, key=lambda e: str(e.updated_at or e.created_at or ""), reverse=True):
        key = _lid(enr.lead_id)
        if key in seen:
            await db.delete_where("campaign_enrollments", {"id": str(enr.id)})
        else:
            seen[key] = enr
    existing = list(seen.values())

    by_lead = {_lid(e.lead_id): e for e in existing}
    lead_by_id = {_lid(l.id): l for l in leads}

    for lead in leads:
        fn = lead.first_name or (lead.name or "there").split()[0]
        note = fit_connection_note(
            personalize_connection(
                conn_tpl, first_name=fn, company=lead.company or "", title=lead.title or ""
            )
        )
        msg = personalize(
            msg_tpl, first_name=fn, company=lead.company or "", title=lead.title or ""
        )
        lid = _lid(lead.id)
        enr = by_lead.get(lid)
        launch_status = "drafted" if note else "pending"
        if enr:
            prior = enr.status or "drafted"
            reset_failed = prior == "failed" and (lead.linkedin_url or "").strip() and note
            stale_yc = note_has_wrong_audience(enr.connection_note or "", s.prompt)
            await db.update(
                "campaign_enrollments",
                enr.id,
                {
                    "connection_note": note if stale_yc or prior in ("drafted", "pending", "failed") else enr.connection_note,
                    "follow_up_message": msg,
                    "status": launch_status
                    if prior in ("drafted", "pending", "new") or reset_failed
                    else prior,
                    "last_error": None if reset_failed else enr.last_error,
                    "updated_at": now,
                },
            )
        else:
            await db.raw.insert(
                "campaign_enrollments",
                {
                    "id": str(uuid.uuid4()),
                    "campaign_id": str(camp.id),
                    "lead_id": lid,
                    "status": launch_status,
                    "connection_note": note,
                    "follow_up_message": msg,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        if note:
            await db.update_lead(lead.id, sequence_status="drafted")

    refreshed = await db.list_enrollments(camp.id)
    out_enrollments = []
    seen_leads: set[str] = set()
    for enr in sorted(refreshed, key=lambda e: str(e.updated_at or e.created_at or ""), reverse=True):
        lid = _lid(enr.lead_id)
        if lid in seen_leads:
            continue
        lead = lead_by_id.get(lid)
        if lead:
            seen_leads.add(lid)
            out_enrollments.append(_enrollment_dict(enr, lead))

    return {
        "ok": True,
        "campaign_id": str(camp.id),
        "campaign": {
            "id": str(camp.id),
            "name": camp.name,
            "connection_note_template": camp.connection_note_template or conn_tpl,
            "message_template": camp.message_template or msg_tpl,
            "wait_days_after_accept": camp.wait_days_after_accept or 1,
        },
        "enrollments": out_enrollments,
        "count": len(out_enrollments),
    }


@router.post("/{search_id}/campaign/launch-origami")
async def launch_search_campaign_via_origami(
    search_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: UserStore = Depends(get_db),
):
    """Launch all sequences through Origami's sequencer (not Talon LinkedIn)."""
    s = await db.get_search(search_id)
    if not s:
        raise HTTPException(404, "Search not found")
    if not s.origami_job_id or not s.origami_table_id:
        raise HTTPException(400, "No Origami table linked — wait for search to finish")

    camp = await db.latest_campaign_for_search(search_id)
    if not camp:
        raise HTTPException(400, "Prepare the campaign first")

    enrollments = await db.list_enrollments(camp.id)
    ready = sum(
        1
        for e in enrollments
        if (e.status or "") in ("drafted", "pending") and (e.connection_note or "").strip()
    )
    if not ready:
        raise HTTPException(400, "No drafted sequences to launch")

    job_id = str(uuid.uuid4())
    campaign_jobs[job_id] = {
        "status": "pending",
        "type": "origami_launch",
        "search_id": str(search_id),
        "campaign_id": str(camp.id),
        "total": ready,
        "done": 0,
        "sent": 0,
        "failed": 0,
        "current": None,
        "step": "Starting Origami launch…",
    }
    background_tasks.add_task(run_origami_launch_job, job_id, search_id)
    return {
        "job_id": job_id,
        "status": "pending",
        "campaign_id": str(camp.id),
        "ready_count": ready,
    }


@router.post("/{search_id}/send/linkedin")
async def send_linkedin_from_search(
    search_id: uuid.UUID,
    body: SendLinkedInBody,
    background_tasks: BackgroundTasks,
    db: UserStore = Depends(get_db),
):
    sess = load_session() or {}
    if not sess.get("connected"):
        raise HTTPException(400, "Connect LinkedIn in Settings before sending")

    s = await db.get_search(search_id)
    if not s:
        raise HTTPException(404, "Search not found")

    leads = await db.list_leads_by_search(search_id)
    if body.lead_ids:
        ids = {str(x) for x in body.lead_ids}
        leads = [l for l in leads if str(l.id) in ids]
    leads = [l for l in leads if (l.linkedin_url or "").strip()]
    if not leads:
        raise HTTPException(400, "No leads with LinkedIn URLs to message")

    kit = _outreach_kit_for_search(s)
    conn_tpl = body.connection_note_template or s.linkedin_message_template or kit["linkedin_connection"]
    msg_tpl = body.message_template or kit.get("linkedin_follow_up") or kit.get("email_step1", "")[:2000]

    camp = await db.raw.insert(
        "campaigns",
        {
            "id": str(uuid.uuid4()),
            "search_id": str(search_id),
            "name": (body.campaign_name or s.prompt[:80] + " — Talon")[:255],
            "connection_note_template": conn_tpl,
            "message_template": msg_tpl,
            "wait_days_after_accept": body.wait_days_after_accept,
            "is_active": True,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        },
    )

    enrolled = 0
    for lead in leads:
        fn = lead.first_name or (lead.name or "there").split()[0]
        note = personalize_connection(
            conn_tpl, first_name=fn, company=lead.company or "", title=lead.title or ""
        )
        msg = personalize(msg_tpl, first_name=fn, company=lead.company or "", title=lead.title or "")
        await db.raw.insert(
            "campaign_enrollments",
            {
                "id": str(uuid.uuid4()),
                "campaign_id": str(camp.id),
                "lead_id": str(lead.id),
                "status": "pending",
                "connection_note": note,
                "follow_up_message": msg,
            },
        )
        await db.update_lead(lead.id, sequence_status="linkedin_queued")
        enrolled += 1

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
    db: UserStore = Depends(get_db),
):
    campaign_id = os.getenv("INSTANTLY_CAMPAIGN_ID", "").strip()
    if not campaign_id:
        from services.app_settings import get_settings

        campaign_id = (get_settings().get("instantly_campaign_id") or "").strip()
    if not campaign_id:
        raise HTTPException(400, "Set INSTANTLY_CAMPAIGN_ID in .env or Settings")

    leads = await db.list_leads_by_search(search_id)
    if body.lead_ids:
        ids = {str(x) for x in body.lead_ids}
        leads = [l for l in leads if str(l.id) in ids]

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
                await db.update_lead(l.id, sequence_status="instantly_queued")

    return result
