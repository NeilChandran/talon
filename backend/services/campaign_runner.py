"""
Multi-step LinkedIn campaign automation:
  1. Send connection request with note
  2. Wait for accept (+ configurable delay)
  3. Send follow-up DM if no reply
"""
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal
from models import Campaign, CampaignEnrollment, Lead, LinkedInOutreachLog
from services.claude_service import generate_linkedin_connection_note, generate_linkedin_message
from services.linkedin_service import (
    check_connection_accepted,
    human_delay,
    load_session,
    resolve_lead_ids,
    send_connection_request_from_session,
    send_message_from_session,
    validate_session,
    _extra_cookies_from_session,
    save_session,
)
from services.send_cap import increment_count, is_capped


def _personalize(template: str, lead: Lead) -> str:
    first_name = (lead.name or "there").split()[0]
    return (
        template.replace("{{first_name}}", first_name)
        .replace("{{company}}", lead.company or "your company")
    )


async def _resolve_lead(lead: Lead, sess: dict) -> Lead:
    if lead.linkedin_profile_id or not lead.linkedin_url:
        return lead
    ids = await resolve_lead_ids(
        linkedin_url=lead.linkedin_url,
        li_at=sess["li_at"],
        jsessionid=sess.get("jsessionid", "ajax:0"),
        bcookie=sess.get("bcookie", ""),
        bscookie=sess.get("bscookie", ""),
    )  # profile lookup uses core cookies; sends use full session via from_session helpers
    if ids:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Lead).where(Lead.id == lead.id))
            db_lead = result.scalar_one_or_none()
            if db_lead:
                db_lead.linkedin_profile_id = ids["linkedin_profile_id"]
                db_lead.linkedin_member_id = ids["linkedin_member_id"]
                db_lead.updated_at = datetime.utcnow()
                await db.commit()
        lead.linkedin_profile_id = ids["linkedin_profile_id"]
        lead.linkedin_member_id = ids["linkedin_member_id"]
    return lead


async def _log(lead_id: str, campaign_id: str, outreach_type: str, content: str, status: str, error: str = None):
    async with AsyncSessionLocal() as db:
        db.add(
            LinkedInOutreachLog(
                id=uuid.uuid4(),
                lead_id=uuid.UUID(lead_id),
                sequence_id=None,
                outreach_type=outreach_type,
                content=content,
                status=status,
                error=error,
                sent_at=datetime.utcnow() if status == "sent" else None,
            )
        )
        await db.commit()


async def process_enrollment(
    enrollment: CampaignEnrollment,
    campaign: Campaign,
    lead: Lead,
    sess: dict,
) -> Dict[str, Any]:
    """Advance one enrollment by at most one step. Returns {action, success, error}."""
    li_at = sess["li_at"]
    jsessionid = sess.get("jsessionid", "ajax:0")
    bcookie = sess.get("bcookie", "")
    bscookie = sess.get("bscookie", "")

    lead = await _resolve_lead(lead, sess)
    lead_data = {
        "id": str(lead.id),
        "name": lead.name,
        "title": lead.title,
        "company": lead.company,
        "company_size": lead.company_size,
        "tech_stack": lead.tech_stack or [],
        "score_reason": lead.score_reason,
    }

    status = enrollment.status

    # Already replied via lead table
    if lead.status == "replied":
        enrollment.status = "replied"
        return {"action": "skip", "success": True}

    if status in ("replied", "completed", "stopped"):
        return {"action": "skip", "success": True}

    if status == "pending":
        if is_capped():
            return {"action": "cap", "success": False, "error": "Daily LinkedIn send cap reached"}

        note_tpl = campaign.connection_note_template or ""
        if note_tpl.strip():
            note = _personalize(note_tpl, lead)[:300]
        elif enrollment.connection_note:
            note = enrollment.connection_note[:300]
        else:
            note = await generate_linkedin_connection_note(lead_data)

        if not lead.linkedin_profile_id:
            enrollment.status = "failed"
            enrollment.last_error = "Could not resolve LinkedIn profile"
            return {"action": "connection", "success": False, "error": enrollment.last_error}

        resp = await send_connection_request_from_session(sess, lead.linkedin_profile_id, note)
        enrollment.connection_note = note
        if resp["success"]:
            enrollment.status = "connection_sent"
            enrollment.connection_sent_at = datetime.utcnow()
            enrollment.last_error = None
            increment_count()
            await _log(str(lead.id), str(campaign.id), "connection_request", note, "sent")
            async with AsyncSessionLocal() as db:
                r = await db.execute(select(Lead).where(Lead.id == lead.id))
                l = r.scalar_one_or_none()
                if l and l.status == "new":
                    l.status = "contacted"
                    l.updated_at = datetime.utcnow()
                    await db.commit()
            return {"action": "connection", "success": True}
        enrollment.status = "failed"
        enrollment.last_error = resp.get("error", "Connection failed")
        await _log(str(lead.id), str(campaign.id), "connection_request", note, "failed", enrollment.last_error)
        return {"action": "connection", "success": False, "error": enrollment.last_error}

    if status == "connection_sent":
        accepted = await check_connection_accepted(
            lead.linkedin_member_id or "",
            li_at,
            jsessionid,
            bcookie,
            bscookie,
        )
        if not accepted:
            return {"action": "wait_accept", "success": True}

        enrollment.accepted_at = datetime.utcnow()
        enrollment.status = "accepted"

        if lead.status == "replied":
            enrollment.status = "replied"
            return {"action": "replied", "success": True}

        wait_days = campaign.wait_days_after_accept or 1
        if enrollment.accepted_at and datetime.utcnow() < enrollment.accepted_at + timedelta(days=wait_days):
            return {"action": "wait_delay", "success": True}

        status = "accepted"  # fall through to send DM

    if status == "accepted":
        msg_tpl = campaign.message_template or ""
        if msg_tpl.strip():
            message = _personalize(msg_tpl, lead)
        elif enrollment.follow_up_message:
            message = enrollment.follow_up_message
        else:
            message = await generate_linkedin_message(lead_data, "follow_up_message")

        if not lead.linkedin_member_id:
            enrollment.last_error = "No member ID for messaging"
            return {"action": "message", "success": False, "error": enrollment.last_error}

        resp = await send_message_from_session(sess, lead.linkedin_member_id, message)
        enrollment.follow_up_message = message
        if resp["success"]:
            enrollment.status = "completed"
            enrollment.dm_sent_at = datetime.utcnow()
            enrollment.last_error = None
            await _log(str(lead.id), str(campaign.id), "message", message, "sent")
            return {"action": "message", "success": True}
        err = resp.get("error", "")
        if "not connected" in err.lower() or "403" in err:
            enrollment.status = "connection_sent"
            enrollment.accepted_at = None
            return {"action": "wait_accept", "success": True}
        enrollment.last_error = err
        return {"action": "message", "success": False, "error": err}

    return {"action": "none", "success": True}


# In-memory campaign jobs (like sequence automation)
campaign_jobs: Dict[str, Any] = {}


async def run_campaign_job(job_id: str, campaign_id: str, enrollment_ids: Optional[list] = None):
    job = campaign_jobs[job_id]
    job["status"] = "running"
    sess = load_session()
    if not sess:
        job["status"] = "failed"
        job["error"] = "No LinkedIn session — connect in Settings"
        return

    check = await validate_session(
        sess["li_at"],
        sess.get("jsessionid", "ajax:0"),
        sess.get("bcookie", ""),
        sess.get("bscookie", ""),
        _extra_cookies_from_session(sess),
    )
    if not check.get("valid"):
        job["status"] = "failed"
        job["error"] = check.get("error", "LinkedIn session invalid — reconnect in Settings")
        return
    if check.get("jsessionid"):
        save_session(
            sess["li_at"],
            check["jsessionid"],
            {"name": check.get("name", sess.get("name", "LinkedIn User"))},
            bcookie=sess.get("bcookie", ""),
            bscookie=sess.get("bscookie", ""),
            extra=_extra_cookies_from_session(sess),
        )
        sess = load_session() or sess

    async with AsyncSessionLocal() as db:
        camp_r = await db.execute(select(Campaign).where(Campaign.id == uuid.UUID(campaign_id)))
        campaign = camp_r.scalar_one_or_none()
        if not campaign:
            job["status"] = "failed"
            job["error"] = "Campaign not found"
            return

        q = select(CampaignEnrollment).where(
            CampaignEnrollment.campaign_id == campaign.id,
            CampaignEnrollment.status.in_(["pending", "connection_sent", "accepted"]),
        )
        if enrollment_ids:
            q = q.where(CampaignEnrollment.id.in_([uuid.UUID(e) for e in enrollment_ids]))
        result = await db.execute(q)
        enrollments = list(result.scalars().all())

    job["total"] = len(enrollments)
    job["done"] = 0
    job["sent"] = 0
    job["failed"] = 0

    for enr in enrollments:
        async with AsyncSessionLocal() as db:
            enr_r = await db.execute(
                select(CampaignEnrollment).where(CampaignEnrollment.id == enr.id)
            )
            enrollment = enr_r.scalar_one_or_none()
            camp_r = await db.execute(select(Campaign).where(Campaign.id == campaign.id))
            campaign = camp_r.scalar_one_or_none()
            lead_r = await db.execute(select(Lead).where(Lead.id == enrollment.lead_id))
            lead = lead_r.scalar_one_or_none()

        if not enrollment or not lead or not campaign:
            job["done"] += 1
            continue

        job["current"] = lead.name
        job["step"] = f"Processing {lead.name} ({enrollment.status})..."

        try:
            outcome = await process_enrollment(enrollment, campaign, lead, sess)
            if outcome.get("action") == "cap":
                job["status"] = "paused"
                job["error"] = outcome.get("error")
                break
            if outcome.get("success") and outcome.get("action") in ("connection", "message"):
                job["sent"] += 1
            elif not outcome.get("success") and outcome.get("action") not in ("wait_accept", "wait_delay", "skip"):
                job["failed"] += 1
        except Exception as e:
            enrollment.last_error = str(e)
            enrollment.status = "failed"
            job["failed"] += 1

        async with AsyncSessionLocal() as db:
            enr_r = await db.execute(
                select(CampaignEnrollment).where(CampaignEnrollment.id == enrollment.id)
            )
            db_enr = enr_r.scalar_one_or_none()
            if db_enr:
                db_enr.status = enrollment.status
                db_enr.connection_note = enrollment.connection_note
                db_enr.follow_up_message = enrollment.follow_up_message
                db_enr.connection_sent_at = enrollment.connection_sent_at
                db_enr.accepted_at = enrollment.accepted_at
                db_enr.dm_sent_at = enrollment.dm_sent_at
                db_enr.last_error = enrollment.last_error
                db_enr.updated_at = datetime.utcnow()
                await db.commit()

        job["done"] += 1
        if job["done"] < len(enrollments):
            await human_delay(4.0, 9.0)

    if job["status"] == "running":
        job["status"] = "completed"
        job["step"] = f"Done — {job['sent']} actions, {job['failed']} failed"
    job["current"] = None


async def sync_campaign_enrollments(campaign_id: str) -> Dict[str, int]:
    """Poll connection_sent enrollments for accepts and advance ready DMs."""
    sess = load_session()
    if not sess:
        return {"processed": 0, "error": "no session"}

    updated = 0
    async with AsyncSessionLocal() as db:
        camp_r = await db.execute(select(Campaign).where(Campaign.id == uuid.UUID(campaign_id)))
        campaign = camp_r.scalar_one_or_none()
        if not campaign:
            return {"processed": 0}

        result = await db.execute(
            select(CampaignEnrollment).where(
                CampaignEnrollment.campaign_id == campaign.id,
                CampaignEnrollment.status.in_(["connection_sent", "accepted"]),
            )
        )
        enrollments = list(result.scalars().all())

    for enr in enrollments:
        async with AsyncSessionLocal() as db:
            enr_r = await db.execute(select(CampaignEnrollment).where(CampaignEnrollment.id == enr.id))
            enrollment = enr_r.scalar_one_or_none()
            lead_r = await db.execute(select(Lead).where(Lead.id == enrollment.lead_id))
            lead = lead_r.scalar_one_or_none()
            camp_r = await db.execute(select(Campaign).where(Campaign.id == campaign.id))
            campaign = camp_r.scalar_one_or_none()

        before = enrollment.status
        await process_enrollment(enrollment, campaign, lead, sess)
        if enrollment.status != before:
            updated += 1

        async with AsyncSessionLocal() as db:
            enr_r = await db.execute(select(CampaignEnrollment).where(CampaignEnrollment.id == enrollment.id))
            db_enr = enr_r.scalar_one_or_none()
            if db_enr:
                db_enr.status = enrollment.status
                db_enr.accepted_at = enrollment.accepted_at
                db_enr.dm_sent_at = enrollment.dm_sent_at
                db_enr.follow_up_message = enrollment.follow_up_message
                db_enr.last_error = enrollment.last_error
                db_enr.updated_at = datetime.utcnow()
                await db.commit()

    return {"processed": len(enrollments), "updated": updated}
