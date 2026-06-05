import uuid
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query

from database import get_db
from schemas import GenerateEmailRequest, GenerateLinkedInRequest, SendEmailRequest
from services.claude_service import (
    generate_email,
    generate_linkedin_connection_note,
    generate_linkedin_message,
)
from user_store import UserStore
from store import get_store

router = APIRouter()


@router.get("/inbox")
async def get_inbox(
    sync: bool = Query(False, description="Refresh Origami schedule status before listing"),
    db: UserStore = Depends(get_db),
):
    """All sequencer messages — draft, scheduled, sent, in progress, replied."""
    from services.inbox_service import list_inbox_rows

    items, stats = await list_inbox_rows(db, sync_origami=sync)
    return {"items": items, "stats": stats}


@router.post("/inbox/sync")
async def sync_inbox(db: UserStore = Depends(get_db)):
    """Pull latest Origami outreach status into enrollments."""
    from services.inbox_service import list_inbox_rows

    items, stats = await list_inbox_rows(db, sync_origami=True)
    return {"ok": True, "items": len(items), "stats": stats}


@router.post("/generate-linkedin")
async def generate_linkedin_messages(
    request: GenerateLinkedInRequest, db: UserStore = Depends(get_db)
):
    """Generate personalized LinkedIn connection notes and messages for selected leads."""
    leads = await db.get_leads_by_ids(request.lead_ids)

    if not leads:
        raise HTTPException(status_code=404, detail="No leads found")

    results = []
    for lead in leads:
        lead_data = {
            "id": str(lead.id),
            "name": lead.name,
            "title": lead.title,
            "company": lead.company,
            "company_size": lead.company_size,
            "tech_stack": lead.tech_stack or [],
            "score_reason": lead.score_reason,
        }

        if request.sequence_type == "connection_request":
            content = await generate_linkedin_connection_note(lead_data)
            results.append({
                "lead_id": str(lead.id),
                "lead_name": lead.name,
                "company": lead.company,
                "linkedin_url": lead.linkedin_url,
                "type": "connection_request",
                "content": content,
                "char_count": len(content),
            })
        else:
            content = await generate_linkedin_message(lead_data, request.sequence_type)
            results.append({
                "lead_id": str(lead.id),
                "lead_name": lead.name,
                "company": lead.company,
                "linkedin_url": lead.linkedin_url,
                "type": request.sequence_type,
                "content": content,
            })

    return {"messages": results, "count": len(results)}


@router.post("/generate")
async def generate_emails(
    request: GenerateEmailRequest, db: UserStore = Depends(get_db)
):
    """Generate personalized emails (legacy — LinkedIn is preferred)."""
    sequence = await db.select_one("sequences", request.sequence_id)
    if not sequence:
        raise HTTPException(status_code=404, detail="Sequence not found")

    leads = await db.get_leads_by_ids(request.lead_ids)
    if not leads:
        raise HTTPException(status_code=404, detail="No leads found")

    results = []
    for lead in leads:
        lead_data = {
            "id": str(lead.id),
            "name": lead.name,
            "title": lead.title,
            "company": lead.company,
            "company_size": lead.company_size,
            "tech_stack": lead.tech_stack or [],
            "score_reason": lead.score_reason,
        }
        email_content = await generate_email(lead_data, sequence.type)
        results.append({
            "lead_id": str(lead.id),
            "lead_name": lead.name,
            "lead_email": lead.email,
            "company": lead.company,
            "subject": email_content["subject"],
            "body": email_content["body"],
        })

    return {"emails": results, "sequence": sequence.name}


@router.post("/send")
async def send_lead_email(
    request: SendEmailRequest, db: UserStore = Depends(get_db)
):
    """Send email via Resend (legacy)."""
    from services.resend_service import send_email as resend_send

    lead = await db.select_one("leads", request.lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if not lead.email:
        raise HTTPException(status_code=400, detail="Lead has no email address")

    result = await resend_send(to=lead.email, subject=request.subject, body=request.body)
    if result["success"]:
        now = datetime.utcnow().isoformat()
        await db.insert(
            "emails_sent",
            {
                "id": str(uuid.uuid4()),
                "lead_id": str(lead.id),
                "sequence_id": str(request.sequence_id),
                "subject": request.subject,
                "body": request.body,
                "sent_at": now,
            },
        )
        await db.update(
            "leads",
            lead.id,
            {"status": "contacted", "updated_at": now},
        )
        return {"success": True, "message": f"Email sent to {lead.email}"}
    raise HTTPException(status_code=500, detail=f"Failed: {result.get('error')}")


@router.get("/sent")
async def get_sent_emails(db: UserStore = Depends(get_db)):
    emails = await db.list_emails_sent(100)
    return [
        {
            "id": str(e.id),
            "lead_id": str(e.lead_id),
            "subject": e.subject,
            "sent_at": e.sent_at,
            "opened": e.opened,
            "replied": e.replied,
        }
        for e in emails
    ]
