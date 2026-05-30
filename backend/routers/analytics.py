"""
Analytics router — funnel metrics, sequence performance, daily activity.
"""
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Lead, LinkedInOutreachLog, Sequence
from services.send_cap import get_status as cap_status, get_history as cap_history

router = APIRouter()


@router.get("/funnel")
async def get_funnel(db: AsyncSession = Depends(get_db)):
    """Lead funnel: prospected → contacted → replied → closed."""
    total_r = await db.execute(select(func.count(Lead.id)))
    total = total_r.scalar() or 0

    contacted_r = await db.execute(
        select(func.count(Lead.id)).where(Lead.status == "contacted")
    )
    contacted = contacted_r.scalar() or 0

    replied_r = await db.execute(
        select(func.count(Lead.id)).where(Lead.status == "replied")
    )
    replied = replied_r.scalar() or 0

    closed_r = await db.execute(
        select(func.count(Lead.id)).where(Lead.status == "closed")
    )
    closed = closed_r.scalar() or 0

    # Sent outreach logs
    sent_r = await db.execute(
        select(func.count(LinkedInOutreachLog.id))
        .where(LinkedInOutreachLog.status == "sent")
    )
    total_sent = sent_r.scalar() or 0

    # Week-over-week new leads
    week_ago = datetime.utcnow() - timedelta(days=7)
    new_this_week_r = await db.execute(
        select(func.count(Lead.id)).where(Lead.created_at >= week_ago)
    )
    new_this_week = new_this_week_r.scalar() or 0

    return {
        "funnel": [
            {"stage": "Prospected", "count": total, "pct": 100},
            {"stage": "Contacted", "count": contacted, "pct": round(contacted / total * 100) if total else 0},
            {"stage": "Replied", "count": replied, "pct": round(replied / total * 100) if total else 0},
            {"stage": "Closed", "count": closed, "pct": round(closed / total * 100) if total else 0},
        ],
        "total_outreach_sent": total_sent,
        "new_this_week": new_this_week,
        "reply_rate": round(replied / contacted * 100, 1) if contacted else 0.0,
        "contact_rate": round(contacted / total * 100, 1) if total else 0.0,
    }


@router.get("/sequences")
async def get_sequence_stats(db: AsyncSession = Depends(get_db)):
    """Per-sequence performance stats."""
    seqs_r = await db.execute(select(Sequence).order_by(Sequence.created_at.desc()))
    seqs = seqs_r.scalars().all()

    results = []
    for seq in seqs:
        sent_r = await db.execute(
            select(func.count(LinkedInOutreachLog.id))
            .where(LinkedInOutreachLog.sequence_id == seq.id)
            .where(LinkedInOutreachLog.status == "sent")
        )
        sent = sent_r.scalar() or 0

        failed_r = await db.execute(
            select(func.count(LinkedInOutreachLog.id))
            .where(LinkedInOutreachLog.sequence_id == seq.id)
            .where(LinkedInOutreachLog.status == "failed")
        )
        failed = failed_r.scalar() or 0

        total = sent + failed
        success_rate = round(sent / total * 100) if total else 0

        results.append({
            "sequence_id": str(seq.id),
            "name": seq.name,
            "type": seq.type,
            "sent": sent,
            "failed": failed,
            "total": total,
            "success_rate": success_rate,
        })

    return results


@router.get("/daily-activity")
async def get_daily_activity(db: AsyncSession = Depends(get_db)):
    """Outreach sent per day over the last 30 days."""
    since = datetime.utcnow() - timedelta(days=30)

    logs_r = await db.execute(
        select(LinkedInOutreachLog)
        .where(LinkedInOutreachLog.sent_at >= since)
        .where(LinkedInOutreachLog.status == "sent")
    )
    logs = logs_r.scalars().all()

    by_date: Dict[str, int] = {}
    for log in logs:
        if log.sent_at:
            key = log.sent_at.strftime("%Y-%m-%d")
            by_date[key] = by_date.get(key, 0) + 1

    # Fill in every day (0 for days with no sends)
    result = []
    for i in range(29, -1, -1):
        d = (datetime.utcnow() - timedelta(days=i)).strftime("%Y-%m-%d")
        result.append({"date": d, "count": by_date.get(d, 0)})

    return result


@router.get("/send-cap")
async def get_send_cap():
    """Today's LinkedIn daily send cap status."""
    return cap_status()


@router.get("/send-cap/history")
async def get_send_cap_history():
    """Send cap history for the last 14 days."""
    return cap_history(14)


@router.get("/lead-sources")
async def get_lead_sources(db: AsyncSession = Depends(get_db)):
    """Breakdown of leads by status and score ranges."""
    total_r = await db.execute(select(func.count(Lead.id)))
    total = total_r.scalar() or 0

    high_r = await db.execute(
        select(func.count(Lead.id)).where(Lead.icp_score >= 8)
    )
    high = high_r.scalar() or 0

    mid_r = await db.execute(
        select(func.count(Lead.id)).where(Lead.icp_score >= 5).where(Lead.icp_score < 8)
    )
    mid = mid_r.scalar() or 0

    low_r = await db.execute(
        select(func.count(Lead.id)).where(Lead.icp_score < 5)
    )
    low = low_r.scalar() or 0

    # Leads by status
    statuses = {}
    for status in ("new", "contacted", "replied", "closed"):
        r = await db.execute(
            select(func.count(Lead.id)).where(Lead.status == status)
        )
        statuses[status] = r.scalar() or 0

    return {
        "total": total,
        "by_score": {
            "high": high,      # 8-10
            "mid": mid,        # 5-7
            "low": low,        # 1-4
        },
        "by_status": statuses,
    }
