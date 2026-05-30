import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import EmailSent, Lead
from schemas import LeadCreate, LeadResponse, LeadUpdate, StatsResponse

router = APIRouter()


@router.get("/stats", response_model=StatsResponse)
async def get_stats(db: AsyncSession = Depends(get_db)):
    total_result = await db.execute(select(func.count(Lead.id)))
    total_leads = total_result.scalar() or 0

    emails_result = await db.execute(select(func.count(EmailSent.id)))
    emails_sent = emails_result.scalar() or 0

    replied_result = await db.execute(
        select(func.count(EmailSent.id)).where(EmailSent.replied == True)
    )
    replied = replied_result.scalar() or 0
    reply_rate = round((replied / emails_sent * 100), 1) if emails_sent > 0 else 0.0

    week_ago = datetime.utcnow() - timedelta(days=7)
    week_result = await db.execute(
        select(func.count(Lead.id)).where(Lead.created_at >= week_ago)
    )
    leads_this_week = week_result.scalar() or 0

    return StatsResponse(
        total_leads=total_leads,
        emails_sent=emails_sent,
        reply_rate=reply_rate,
        leads_this_week=leads_this_week,
    )


@router.get("/recent", response_model=List[LeadResponse])
async def get_recent_leads(limit: int = 10, db: AsyncSession = Depends(get_db)):
    """Return status='new' leads that have a LinkedIn URL (real prospects, not AI-generated)."""
    result = await db.execute(
        select(Lead)
        .where(Lead.status == "new")
        .where(Lead.linkedin_url.isnot(None))
        .order_by(desc(Lead.created_at))
        .limit(limit)
    )
    return result.scalars().all()


@router.delete("/")
async def delete_all_leads(db: AsyncSession = Depends(get_db)):
    """Delete every lead in the database — used to reset the pipeline."""
    from sqlalchemy import delete as sa_delete
    from models import LinkedInOutreachLog, EmailSent
    # Delete dependent rows first
    await db.execute(sa_delete(LinkedInOutreachLog))
    await db.execute(sa_delete(EmailSent))
    await db.execute(sa_delete(Lead))
    await db.commit()
    return {"message": "All leads deleted"}


@router.get("/", response_model=List[LeadResponse])
async def get_leads(
    status: Optional[str] = None,
    min_score: Optional[int] = None,
    max_score: Optional[int] = None,
    search: Optional[str] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    limit: int = Query(200, le=500),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    query = select(Lead)

    if status:
        query = query.where(Lead.status == status)
    if min_score is not None:
        query = query.where(Lead.icp_score >= min_score)
    if max_score is not None:
        query = query.where(Lead.icp_score <= max_score)
    if search:
        query = query.where(
            or_(
                Lead.name.ilike(f"%{search}%"),
                Lead.company.ilike(f"%{search}%"),
                Lead.email.ilike(f"%{search}%"),
            )
        )

    valid_columns = {"created_at", "name", "company", "icp_score", "status"}
    sort_col = sort_by if sort_by in valid_columns else "created_at"
    col = getattr(Lead, sort_col)
    query = query.order_by(desc(col) if sort_order == "desc" else col)
    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{lead_id}", response_model=LeadResponse)
async def get_lead(lead_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.post("/", response_model=LeadResponse)
async def create_lead(lead: LeadCreate, db: AsyncSession = Depends(get_db)):
    db_lead = Lead(**lead.model_dump())
    db.add(db_lead)
    await db.commit()
    await db.refresh(db_lead)
    return db_lead


@router.put("/{lead_id}", response_model=LeadResponse)
async def update_lead(
    lead_id: uuid.UUID,
    lead_update: LeadUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    for field, value in lead_update.model_dump(exclude_unset=True).items():
        setattr(lead, field, value)
    lead.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(lead)
    return lead


@router.delete("/{lead_id}")
async def delete_lead(lead_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    await db.delete(lead)
    await db.commit()
    return {"message": "Lead deleted"}
