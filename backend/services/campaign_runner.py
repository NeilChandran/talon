"""
Multi-step LinkedIn campaign automation:
  1. Send connection request with note
  2. Wait for accept (+ configurable delay)
  3. Send follow-up DM if no reply
"""
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from services.claude_service import generate_linkedin_connection_note, generate_linkedin_message
from services.outreach_templates import fit_connection_note, lead_first_name, personalize_connection
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
from store import Record, get_store


def _personalize(template: str, lead: Record) -> str:
    return personalize_connection(
        template,
        first_name=lead_first_name(lead),
        company=lead.company or "",
        title=lead.title or "",
    )


async def _resolve_lead(lead: Record, sess: dict) -> Record:
    if lead.linkedin_profile_id or not lead.linkedin_url:
        return lead
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
    return lead


async def _log(lead_id: str, campaign_id: str, outreach_type: str, content: str, status: str, error: str = None):
    db = get_store()
    await db.insert_outreach_log({
        "lead_id": lead_id,
        "outreach_type": outreach_type,
        "content": content,
        "status": status,
        "error": error,
        "sent_at": datetime.utcnow().isoformat() if status == "sent" else None,
    })


def _parse_dt(val) -> Optional[datetime]:
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    try:
        return datetime.fromisoformat(str(val).replace("Z", "+00:00").replace("+00:00", ""))
    except ValueError:
        return None


async def process_enrollment(
    enrollment: Record,
    campaign: Record,
    lead: Record,
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

    if lead.status == "replied":
        enrollment.status = "replied"
        return {"action": "skip", "success": True}

    if status in ("replied", "completed", "stopped"):
        return {"action": "skip", "success": True}

    if status in ("pending", "drafted"):
        if is_capped():
            return {"action": "cap", "success": False, "error": "Daily LinkedIn send cap reached"}

        if enrollment.connection_note and enrollment.connection_note.strip():
            note = fit_connection_note(enrollment.connection_note)
        elif (campaign.connection_note_template or "").strip():
            note = _personalize(campaign.connection_note_template, lead)
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
            enrollment.connection_sent_at = datetime.utcnow().isoformat()
            enrollment.last_error = None
            increment_count()
            await _log(str(lead.id), str(campaign.id), "connection_request", note, "sent")
            if lead.status == "new":
                db = get_store()
                await db.update_lead(lead.id, status="contacted")
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

        enrollment.accepted_at = datetime.utcnow().isoformat()
        enrollment.status = "accepted"

        if lead.status == "replied":
            enrollment.status = "replied"
            return {"action": "replied", "success": True}

        wait_days = campaign.wait_days_after_accept or 1
        accepted_dt = _parse_dt(enrollment.accepted_at)
        if accepted_dt and datetime.utcnow() < accepted_dt + timedelta(days=wait_days):
            return {"action": "wait_delay", "success": True}

        status = "accepted"

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
            enrollment.dm_sent_at = datetime.utcnow().isoformat()
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


campaign_jobs: Dict[str, Any] = {}


def _enrollment_patch(enrollment: Record) -> dict:
    return {
        "status": enrollment.status,
        "connection_note": enrollment.connection_note,
        "follow_up_message": enrollment.follow_up_message,
        "connection_sent_at": enrollment.connection_sent_at,
        "accepted_at": enrollment.accepted_at,
        "dm_sent_at": enrollment.dm_sent_at,
        "last_error": enrollment.last_error,
        "updated_at": datetime.utcnow().isoformat(),
    }


async def run_campaign_job(job_id: str, campaign_id: str, enrollment_ids: Optional[list] = None):
    job = campaign_jobs[job_id]
    job["status"] = "running"
    sess = load_session()
    if not sess:
        job["status"] = "failed"
        job["error"] = "No LinkedIn session — connect in Settings"
        return

    db = get_store()
    campaign = await db.select_one("campaigns", campaign_id)
    if not campaign:
        job["status"] = "failed"
        job["error"] = "Campaign not found"
        return

    filters = {"campaign_id": str(campaign_id)}
    enrollments = await db.select_many(
        "campaign_enrollments",
        filters=filters,
        in_filters={"status": ["drafted", "pending", "connection_sent", "accepted"]},
    )
    if enrollment_ids:
        allowed = {str(e) for e in enrollment_ids}
        enrollments = [e for e in enrollments if str(e.id) in allowed]

    launchable = []
    for enr in enrollments:
        if enr.status in ("connection_sent", "accepted"):
            launchable.append(enr)
            continue
        if enr.status not in ("drafted", "pending"):
            continue
        if not (enr.connection_note or "").strip():
            continue
        launchable.append(enr)
    enrollments = launchable

    job["total"] = len(enrollments)
    if not enrollments:
        job["status"] = "failed"
        job["error"] = "No drafted sequences with connection notes to launch"
        return

    job["step"] = "Verifying LinkedIn session..."
    check = await validate_session(
        sess["li_at"],
        sess.get("jsessionid", "ajax:0"),
        sess.get("bcookie", ""),
        sess.get("bscookie", ""),
        _extra_cookies_from_session(sess),
    )
    if check.get("valid"):
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
    else:
        job["step"] = "Session check failed — trying browser send..."
        print(
            f"[campaign] validate_session failed: {check.get('error')} — continuing",
            flush=True,
        )
    job["done"] = 0
    job["sent"] = 0
    job["failed"] = 0

    for enr in enrollments:
        enrollment = await db.select_one("campaign_enrollments", enr.id)
        campaign = await db.select_one("campaigns", campaign_id)
        lead = await db.select_one("leads", enrollment.lead_id) if enrollment else None

        if not enrollment or not lead or not campaign:
            job["done"] += 1
            continue

        job["current"] = lead.name
        job["step"] = f"Processing {lead.name} ({enrollment.status})..."

        try:
            outcome = await process_enrollment(enrollment, campaign, lead, sess)
            if outcome.get("action") == "cap":
                remaining = len(enrollments) - job["done"]
                job["status"] = "paused"
                job["error"] = (
                    f"{outcome.get('error')} — {job['sent']} sent, {remaining} remaining. "
                    "Run Launch all again tomorrow."
                )
                job["step"] = job["error"]
                break
            if outcome.get("success") and outcome.get("action") in ("connection", "message"):
                job["sent"] += 1
            elif not outcome.get("success") and outcome.get("action") not in ("wait_accept", "wait_delay", "skip"):
                job["failed"] += 1
        except Exception as e:
            enrollment.last_error = str(e)
            enrollment.status = "failed"
            job["failed"] += 1

        await db.update("campaign_enrollments", enrollment.id, _enrollment_patch(enrollment))

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

    db = get_store()
    campaign = await db.select_one("campaigns", campaign_id)
    if not campaign:
        return {"processed": 0}

    enrollments = await db.select_many(
        "campaign_enrollments",
        filters={"campaign_id": str(campaign_id)},
        in_filters={"status": ["connection_sent", "accepted"]},
    )

    updated = 0
    for enr in enrollments:
        enrollment = await db.select_one("campaign_enrollments", enr.id)
        lead = await db.select_one("leads", enrollment.lead_id) if enrollment else None
        campaign = await db.select_one("campaigns", campaign_id)

        if not enrollment or not lead or not campaign:
            continue

        before = enrollment.status
        await process_enrollment(enrollment, campaign, lead, sess)
        if enrollment.status != before:
            updated += 1

        await db.update("campaign_enrollments", enrollment.id, _enrollment_patch(enrollment))

    return {"processed": len(enrollments), "updated": updated}
