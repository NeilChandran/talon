"""
Analytics router — funnel metrics, sequence performance, daily activity.
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends

from database import get_db
from services.send_cap import get_status as cap_status, get_history as cap_history
from user_store import UserStore
from store import get_store

router = APIRouter()


@router.get("/funnel")
async def get_funnel(db: UserStore = Depends(get_db)):
    """Lead funnel: prospected → contacted → replied → closed."""
    total = await db.count_table("leads")
    contacted = await db.count_leads_by_status("contacted")
    replied = await db.count_leads_by_status("replied")
    closed = await db.count_leads_by_status("closed")
    total_sent = await db.count_outreach_logs(status="sent")

    week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
    new_this_week = await db.count_leads_since(week_ago)

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
async def get_sequence_stats(db: UserStore = Depends(get_db)):
    """Per-sequence performance stats."""
    seqs = await db.list_sequences()

    results = []
    for seq in seqs:
        sent = await db.count_outreach_logs_for_sequence(seq.id, "sent")
        failed = await db.count_outreach_logs_for_sequence(seq.id, "failed")
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
async def get_daily_activity(db: UserStore = Depends(get_db)):
    """Outreach sent per day over the last 30 days."""
    since = (datetime.utcnow() - timedelta(days=30)).isoformat()
    logs = await db.list_outreach_logs_since(since, status="sent")

    by_date: dict = {}
    for log in logs:
        if log.sent_at:
            key = str(log.sent_at)[:10]
            by_date[key] = by_date.get(key, 0) + 1

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
async def get_lead_sources(db: UserStore = Depends(get_db)):
    """Breakdown of leads by status and score ranges."""
    total = await db.count_table("leads")
    high = await db.count_leads_icp_gte(8)
    mid = await db.count_leads_icp_range(5, 8)
    low = await db.count_leads_icp_lt(5)

    statuses = {}
    for status in ("new", "contacted", "replied", "closed"):
        statuses[status] = await db.count_leads_by_status(status)

    return {
        "total": total,
        "by_score": {
            "high": high,
            "mid": mid,
            "low": low,
        },
        "by_status": statuses,
    }
