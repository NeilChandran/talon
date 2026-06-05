"""Aggregate campaign enrollments into Origami-style inbox rows."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from store import Record


def _parse_dt(val: Any) -> Optional[datetime]:
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    try:
        return datetime.fromisoformat(str(val).replace("Z", "+00:00").replace("+00:00", ""))
    except ValueError:
        return None


def linkedin_handle(url: str) -> str:
    if not url or "/in/" not in url:
        return ""
    return url.split("/in/")[-1].strip("/").split("?")[0]


def format_scheduled_label(iso: Optional[str]) -> str:
    dt = _parse_dt(iso)
    if not dt:
        return "Scheduled"
    now = datetime.utcnow()
    same_day = dt.date() == now.date()
    time_s = dt.strftime("%I:%M %p").lstrip("0")
    if same_day:
        return f"Scheduled for {time_s}"
    day_s = dt.strftime("%a, %b %d").replace(" 0", " ")
    return f"Scheduled for {day_s} at {time_s}"


def _is_scheduled(enr: Record) -> bool:
    origami = (getattr(enr, "origami_send_status", None) or "").lower()
    scheduled_at = getattr(enr, "scheduled_at", None)
    return origami in ("scheduled", "queued", "pending") or bool(scheduled_at)


def inbox_bucket(enr: Record) -> str:
    st = (enr.status or "pending").lower()
    origami = (getattr(enr, "origami_send_status", None) or "").lower()

    if st == "replied":
        return "replied"
    if st == "failed":
        return "failed"
    if st == "stopped":
        return "stopped"
    if st in ("dm_sent", "completed"):
        return "sent"
    if origami in ("sent", "delivered", "complete", "completed"):
        return "sent"
    if _is_scheduled(enr):
        return "scheduled"
    if st in ("drafted", "pending"):
        return "draft"
    if st in ("connection_sent", "accepted"):
        return "in_progress"
    return "draft"


def inbox_label(enr: Record) -> str:
    bucket = inbox_bucket(enr)
    labels = {
        "draft": "Draft",
        "scheduled": format_scheduled_label(getattr(enr, "scheduled_at", None)),
        "sent": "Sent",
        "in_progress": "In progress",
        "replied": "Replied",
        "failed": "Failed",
        "stopped": "Stopped",
    }
    return labels.get(bucket, "Draft")


def activity_timestamp(enr: Record) -> Optional[str]:
    bucket = inbox_bucket(enr)
    if bucket == "scheduled":
        val = getattr(enr, "scheduled_at", None) or getattr(enr, "connection_sent_at", None)
        if val:
            dt = _parse_dt(val)
            if dt:
                return dt.isoformat()
    for field in ("dm_sent_at", "connection_sent_at", "accepted_at", "updated_at", "created_at"):
        val = getattr(enr, field, None)
        if val:
            dt = _parse_dt(val)
            if dt:
                return dt.isoformat()
    return None


def relative_time(iso: Optional[str]) -> str:
    dt = _parse_dt(iso)
    if not dt:
        return ""
    delta = datetime.utcnow() - dt
    secs = int(delta.total_seconds())
    if secs < 60:
        return "now"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h"
    days = secs // 86400
    if days < 14:
        return f"{days}d"
    return dt.strftime("%b %d").lstrip("0")


def build_inbox_row(
    enr: Record,
    lead: Optional[Record],
    campaign: Optional[Record],
    search: Optional[Record],
) -> Dict[str, Any]:
    url = (lead.linkedin_url if lead else "") or ""
    handle = linkedin_handle(url)
    name = ""
    if lead:
        name = (f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.name or "").strip()
    recipient = handle or name or "Lead"
    camp_name = (campaign.name if campaign else "") or ""
    if camp_name.endswith(" — Talon"):
        camp_name = camp_name[:-8].strip()
    search_prompt = (search.prompt if search else "") or camp_name
    ts = activity_timestamp(enr)
    bucket = inbox_bucket(enr)
    note = (enr.connection_note or "") if enr else ""
    if not note and lead:
        note = (getattr(lead, "linkedin_message", None) or "")[:500]
    return {
        "id": str(enr.id),
        "enrollment_id": str(enr.id),
        "lead_id": str(enr.lead_id),
        "campaign_id": str(enr.campaign_id),
        "search_id": str(getattr(campaign, "search_id", "") or getattr(lead, "search_id", "") or ""),
        "recipient": recipient,
        "name": name or recipient,
        "title": (lead.title if lead else "") or "",
        "company": (lead.company if lead else "") or "",
        "linkedin_url": url,
        "campaign_name": camp_name or search_prompt,
        "search_prompt": search_prompt,
        "status": bucket,
        "status_label": inbox_label(enr),
        "enrollment_status": enr.status or "pending",
        "origami_send_status": getattr(enr, "origami_send_status", None),
        "scheduled_at": getattr(enr, "scheduled_at", None),
        "connection_note": note[:500],
        "follow_up_message": (enr.follow_up_message or "")[:500],
        "activity_at": ts,
        "activity_label": relative_time(ts),
        "last_error": enr.last_error,
    }


def build_draft_row(
    lead: Record,
    campaign: Optional[Record],
    search: Optional[Record],
) -> Dict[str, Any]:
    url = (lead.linkedin_url or "") or ""
    handle = linkedin_handle(url)
    name = (f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.name or "").strip()
    recipient = handle or name or "Lead"
    camp_name = (campaign.name if campaign else "") or ""
    if camp_name.endswith(" — Talon"):
        camp_name = camp_name[:-8].strip()
    search_prompt = (search.prompt if search else "") or camp_name
    note = (getattr(lead, "linkedin_message", None) or "")[:500]
    ts = None
    for field in ("updated_at", "created_at"):
        val = getattr(lead, field, None)
        if val:
            dt = _parse_dt(val)
            if dt:
                ts = dt.isoformat()
                break
    return {
        "id": f"lead-{lead.id}",
        "enrollment_id": "",
        "lead_id": str(lead.id),
        "campaign_id": str(campaign.id) if campaign else "",
        "search_id": str(getattr(lead, "search_id", "") or getattr(campaign, "search_id", "") or ""),
        "recipient": recipient,
        "name": name or recipient,
        "title": (lead.title or "") or "",
        "company": (lead.company or "") or "",
        "linkedin_url": url,
        "campaign_name": camp_name or search_prompt,
        "search_prompt": search_prompt,
        "status": "draft",
        "status_label": "Draft",
        "enrollment_status": "drafted",
        "origami_send_status": None,
        "scheduled_at": None,
        "connection_note": note,
        "follow_up_message": "",
        "activity_at": ts,
        "activity_label": relative_time(ts),
        "last_error": None,
    }


async def _campaign_ids_for_user(db) -> Optional[Set[str]]:
    """When logged in, limit inbox to campaigns tied to the user's searches."""
    user_id = getattr(db, "user_id", None)
    if not user_id:
        return None
    searches = await db.list_recent_searches(100)
    ids: Set[str] = set()
    for s in searches:
        camp = await db.latest_campaign_for_search(s.id)
        if camp:
            ids.add(str(camp.id))
    return ids


async def list_inbox_rows(db, *, sync_origami: bool = False) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    if sync_origami:
        from services.search_runner import sync_origami_drafts

        searches = await db.list_recent_searches(50)
        for s in searches:
            if getattr(s, "origami_table_id", None):
                try:
                    await sync_origami_drafts(s.id)
                except Exception:
                    pass

    allowed_campaigns = await _campaign_ids_for_user(db)
    enrollments = await db.raw.select_many(
        "campaign_enrollments",
        order="updated_at",
        desc=True,
        limit=5000,
    )
    if allowed_campaigns is not None:
        enrollments = [e for e in enrollments if str(e.campaign_id) in allowed_campaigns]

    campaigns = {str(c.id): c for c in await db.list_campaigns(500)}
    if allowed_campaigns is not None:
        campaigns = {k: v for k, v in campaigns.items() if k in allowed_campaigns}

    enrolled_lead_ids: Set[str] = set()
    lead_ids = list({e.lead_id for e in enrollments if e.lead_id})
    leads_map: Dict[str, Record] = {}
    if lead_ids:
        for lead in await db.raw.select_many("leads", in_filters={"id": lead_ids}):
            leads_map[str(lead.id).replace("-", "").lower()] = lead
            leads_map[str(lead.id)] = lead
            enrolled_lead_ids.add(str(lead.id).replace("-", "").lower())
            enrolled_lead_ids.add(str(lead.id))

    search_ids = list(
        {
            str(getattr(campaigns.get(str(e.campaign_id)), "search_id", ""))
            for e in enrollments
            if campaigns.get(str(e.campaign_id)) and getattr(campaigns[str(e.campaign_id)], "search_id", None)
        }
    )
    for camp in campaigns.values():
        sid = str(getattr(camp, "search_id", "") or "")
        if sid:
            search_ids.append(sid)
    searches_map: Dict[str, Record] = {}
    for sid in set(search_ids):
        if sid:
            s = await db.get_search(sid)
            if s:
                searches_map[sid] = s

    rows: List[Dict[str, Any]] = []
    week_ago = datetime.utcnow() - timedelta(days=7)
    sent_week = 0
    replies = 0

    for enr in enrollments:
        lid = str(enr.lead_id).replace("-", "").lower()
        lead = leads_map.get(lid) or leads_map.get(str(enr.lead_id))
        camp = campaigns.get(str(enr.campaign_id))
        search = None
        if camp and getattr(camp, "search_id", None):
            search = searches_map.get(str(camp.search_id))
        row = build_inbox_row(enr, lead, camp, search)
        rows.append(row)
        if row["status"] == "replied":
            replies += 1
        sent_at = _parse_dt(enr.connection_sent_at or enr.dm_sent_at)
        if sent_at and sent_at >= week_ago and row["status"] in ("sent", "in_progress", "scheduled"):
            sent_week += 1

    # Leads with a campaign but no enrollment yet — show as drafts.
    for camp in campaigns.values():
        sid = str(getattr(camp, "search_id", "") or "")
        if not sid:
            continue
        search = searches_map.get(sid)
        if not search:
            continue
        for lead in await db.list_leads_by_search(sid):
            lid = str(lead.id).replace("-", "").lower()
            if lid in enrolled_lead_ids or str(lead.id) in enrolled_lead_ids:
                continue
            seq_st = (getattr(lead, "sequence_status", None) or "").lower()
            has_note = bool((getattr(lead, "linkedin_message", None) or "").strip())
            if has_note or seq_st in ("drafted", "new", "pending", ""):
                rows.append(build_draft_row(lead, camp, search))

    rows.sort(
        key=lambda r: _parse_dt(r.get("activity_at")) or datetime.min,
        reverse=True,
    )

    stats = {
        "all": len(rows),
        "replies": replies,
        "sent_week": sent_week,
        "draft": sum(1 for r in rows if r["status"] == "draft"),
        "scheduled": sum(1 for r in rows if r["status"] == "scheduled"),
        "sent": sum(1 for r in rows if r["status"] == "sent"),
        "in_progress": sum(1 for r in rows if r["status"] == "in_progress"),
    }
    return rows, stats
