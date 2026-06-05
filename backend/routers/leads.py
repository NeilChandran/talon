import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from database import get_db
from schemas import LeadCreate, LeadResponse, LeadUpdate, StatsResponse
from user_store import UserStore

router = APIRouter()


def _to_response(r) -> LeadResponse:
    return LeadResponse(
        id=uuid.UUID(str(r.id)),
        name=r.name,
        title=r.title,
        company=r.company,
        company_size=r.company_size,
        email=r.email,
        linkedin_url=r.linkedin_url,
        linkedin_profile_id=r.linkedin_profile_id,
        linkedin_member_id=r.linkedin_member_id,
        icp_score=r.icp_score or r.score or 5,
        score_reason=r.score_reason,
        source_url=r.source_url or "",
        tech_stack=r.tech_stack or [],
        status=r.status or "new",
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


async def _count_replied_emails(store) -> int:
    """Supabase or SQLite — avoid calling Supabase client on local DB."""
    if hasattr(store, "_client"):
        def _replied_count():
            return (
                store._client.table("emails_sent")
                .select("*", count="exact", head=True)
                .eq("replied", True)
                .execute()
                .count
                or 0
            )

        return await store._run(_replied_count)
    try:
        return await store.count("emails_sent", filters={"replied": 1})
    except Exception:
        return 0


@router.get("/stats", response_model=StatsResponse)
async def get_stats(db: UserStore = Depends(get_db)):
    lead_filters = {"user_id": db.user_id} if db.user_id else None
    total_leads = await db.raw.count("leads", filters=lead_filters)
    emails_sent = await db.raw.count("emails_sent")
    replied = await _count_replied_emails(db.raw)
    reply_rate = round((replied / emails_sent * 100), 1) if emails_sent > 0 else 0.0
    week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
    leads_this_week = await db.count_leads_since(week_ago)

    return StatsResponse(
        total_leads=total_leads,
        emails_sent=emails_sent,
        reply_rate=reply_rate,
        leads_this_week=leads_this_week,
    )


@router.get("/recent", response_model=List[LeadResponse])
async def get_recent_leads(limit: int = 10, db: UserStore = Depends(get_db)):
    rows = await db.filter_leads(status="new", limit=limit)
    return [_to_response(r) for r in rows if r.linkedin_url]


@router.delete("/")
async def delete_all_leads(db: UserStore = Depends(get_db)):
    await db.purge_all_leads()
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
    db: UserStore = Depends(get_db),
):
    rows = await db.filter_leads(
        status=status,
        min_score=min_score,
        max_score=max_score,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        offset=offset,
    )
    return [_to_response(r) for r in rows]


@router.get("/{lead_id}", response_model=LeadResponse)
async def get_lead(lead_id: uuid.UUID, db: UserStore = Depends(get_db)):
    lead = await db.get_lead(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return _to_response(lead)


@router.post("/", response_model=LeadResponse)
async def create_lead(lead: LeadCreate, db: UserStore = Depends(get_db)):
    row = await db.insert_lead({"id": str(uuid.uuid4()), **lead.model_dump()})
    return _to_response(row)


@router.put("/{lead_id}", response_model=LeadResponse)
async def update_lead(
    lead_id: uuid.UUID,
    lead_update: LeadUpdate,
    db: UserStore = Depends(get_db),
):
    patch = lead_update.model_dump(exclude_unset=True)
    patch["updated_at"] = datetime.utcnow().isoformat()
    row = await db.update("leads", lead_id, patch)
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")
    return _to_response(row)


@router.delete("/{lead_id}")
async def delete_lead(lead_id: uuid.UUID, db: UserStore = Depends(get_db)):
    if not await db.delete_lead(lead_id):
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"message": "Lead deleted"}
