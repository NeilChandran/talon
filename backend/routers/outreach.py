import uuid
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import EmailSent, Lead, Sequence
from schemas import GenerateEmailRequest, GenerateLinkedInRequest, SendEmailRequest
from services.claude_service import (
    generate_email,
    generate_linkedin_connection_note,
    generate_linkedin_message,
)

router = APIRouter()


# ─── LinkedIn message generation ─────────────────────────────────────────────

@router.post("/generate-linkedin")
async def generate_linkedin_messages(
    request: GenerateLinkedInRequest, db: AsyncSession = Depends(get_db)
):
    """Generate personalized LinkedIn connection notes and messages for selected leads."""
    leads_result = await db.execute(
        select(Lead).where(Lead.id.in_(request.lead_ids))
    )
    leads = leads_result.scalars().all()

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


# ─── Legacy email generation (kept for backward compat) ──────────────────────

@router.post("/generate")
async def generate_emails(
    request: GenerateEmailRequest, db: AsyncSession = Depends(get_db)
):
    """Generate personalized emails (legacy — LinkedIn is preferred)."""
    seq_result = await db.execute(
        select(Sequence).where(Sequence.id == request.sequence_id)
    )
    sequence = seq_result.scalar_one_or_none()
    if not sequence:
        raise HTTPException(status_code=404, detail="Sequence not found")

    leads_result = await db.execute(
        select(Lead).where(Lead.id.in_(request.lead_ids))
    )
    leads = leads_result.scalars().all()
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
    request: SendEmailRequest, db: AsyncSession = Depends(get_db)
):
    """Send email via Resend (legacy)."""
    from services.resend_service import send_email as resend_send

    lead_result = await db.execute(select(Lead).where(Lead.id == request.lead_id))
    lead = lead_result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if not lead.email:
        raise HTTPException(status_code=400, detail="Lead has no email address")

    result = await resend_send(to=lead.email, subject=request.subject, body=request.body)
    if result["success"]:
        email_record = EmailSent(
            id=uuid.uuid4(),
            lead_id=lead.id,
            sequence_id=request.sequence_id,
            subject=request.subject,
            body=request.body,
            sent_at=datetime.utcnow(),
        )
        db.add(email_record)
        lead.status = "contacted"
        lead.updated_at = datetime.utcnow()
        await db.commit()
        return {"success": True, "message": f"Email sent to {lead.email}"}
    else:
        raise HTTPException(status_code=500, detail=f"Failed: {result.get('error')}")


@router.get("/sent")
async def get_sent_emails(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(EmailSent).order_by(EmailSent.sent_at.desc()).limit(100)
    )
    emails = result.scalars().all()
    return [
        {
            "id": str(e.id),
            "lead_id": str(e.lead_id),
            "subject": e.subject,
            "sent_at": e.sent_at.isoformat() if e.sent_at else None,
            "opened": e.opened,
            "replied": e.replied,
        }
        for e in emails
    ]
