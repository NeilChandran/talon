"""Origami-style workspaces: home prompt → lists → campaigns → LinkedIn."""
import os
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import (
    AgentChatMessage,
    Campaign,
    CampaignEnrollment,
    Lead,
    Workspace,
    WorkspaceList,
    WorkspaceListLead,
)
from services.campaign_runner import campaign_jobs, run_campaign_job
from services.claude_service import workspace_agent_chat
from services.linkedin_service import load_session
from services.list_builder import build_jobs, run_list_build

router = APIRouter()


def _dispatch_list_build(
    list_id: uuid.UUID,
    prompt: str,
    background_tasks: BackgroundTasks,
) -> None:
    """Prefer Celery+Redis when available; else FastAPI background task."""
    if os.getenv("REDIS_URL"):
        try:
            from tasks import build_workspace_list

            build_workspace_list.delay(str(list_id), prompt)
            build_jobs[str(list_id)] = {"status": "running", "step": "Running search agents…", "count": 0}
            return
        except Exception as e:
            print(f"[workspaces] Celery dispatch failed, using asyncio: {e}", flush=True)
    background_tasks.add_task(run_list_build, list_id, prompt)


DEFAULT_CONNECTION = (
    "Hey {{first_name}}! I'm building Talon — AI that finds your ideal customers on LinkedIn "
    "and runs personalised outreach. Would love to connect!"
)[:300]

DEFAULT_FOLLOWUP = (
    "Hey {{first_name}}, thanks for connecting!\n\n"
    "Talon helps you describe who you want to reach, builds the list with real LinkedIn data, "
    "and launches connection + follow-up sequences when you're ready.\n\n"
    "Happy to show you a quick demo if you're open to a short call this week?"
)


def _workspace_name_from_prompt(prompt: str) -> str:
    words = re.sub(r"\s+", " ", prompt.strip())[:60].split()
    if len(words) <= 6:
        return prompt.strip()[:60] or "New Workspace"
    return " ".join(words[:6]).title()


def _list_name_from_prompt(prompt: str) -> str:
    s = prompt.strip()[:50]
    return s if len(s) <= 50 else s[:47] + "..."


def _row_dict(r: WorkspaceListLead, lead: Lead | None = None) -> dict:
    extra = r.extra or {}
    email = (lead.email if lead else "") or extra.get("email", "")
    return {
        "id": str(r.id),
        "lead_id": str(r.lead_id) if r.lead_id else None,
        "first_name": r.first_name or "",
        "last_name": r.last_name or "",
        "title": r.title or "",
        "company": r.company or "",
        "email": email,
        "linkedin_url": r.linkedin_url or "",
        "icp_score": r.icp_score or 0,
        "score_reason": extra.get("score_reason", "") or (lead.score_reason if lead else ""),
    }


def _ws_dict(ws: Workspace, list_count: int = 0) -> dict:
    return {
        "id": str(ws.id),
        "name": ws.name,
        "icon_letter": ws.icon_letter or "T",
        "list_count": list_count,
        "created_at": ws.created_at.isoformat() if ws.created_at else None,
        "updated_at": ws.updated_at.isoformat() if ws.updated_at else None,
    }


class QuickStartBody(BaseModel):
    prompt: str


class CreateWorkspaceBody(BaseModel):
    name: str


class CreateListBody(BaseModel):
    prompt: str
    name: Optional[str] = None


class WorkspaceChatBody(BaseModel):
    message: str
    list_id: Optional[uuid.UUID] = None


class LaunchFromListBody(BaseModel):
    connection_note_template: Optional[str] = None
    message_template: Optional[str] = None
    wait_days_after_accept: int = 1
    campaign_name: Optional[str] = None


@router.get("/")
async def list_workspaces(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Workspace).order_by(Workspace.updated_at.desc()))
    workspaces = list(result.scalars().all())
    out = []
    for ws in workspaces:
        cnt = await db.execute(
            select(func.count()).select_from(WorkspaceList).where(WorkspaceList.workspace_id == ws.id)
        )
        out.append(_ws_dict(ws, cnt.scalar() or 0))
    return out


@router.post("/")
async def create_workspace(body: CreateWorkspaceBody, db: AsyncSession = Depends(get_db)):
    letter = (body.name.strip()[:1] or "T").upper()
    ws = Workspace(
        id=uuid.uuid4(),
        name=body.name.strip(),
        icon_letter=letter,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(ws)
    await db.commit()
    await db.refresh(ws)
    return _ws_dict(ws, 0)


@router.post("/quick-start")
async def quick_start(body: QuickStartBody, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """Origami home: one prompt → workspace + list + background build."""
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(400, "Prompt required")

    name = _workspace_name_from_prompt(prompt)
    letter = name[0].upper() if name else "T"
    ws = Workspace(
        id=uuid.uuid4(),
        name=name,
        icon_letter=letter,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(ws)

    lst = WorkspaceList(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        name=_list_name_from_prompt(prompt),
        icp_prompt=prompt,
        status="building",
        build_step="Starting...",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(lst)
    await db.commit()

    _dispatch_list_build(lst.id, prompt, background_tasks)

    return {
        "workspace": _ws_dict(ws, 1),
        "list": {
            "id": str(lst.id),
            "workspace_id": str(ws.id),
            "name": lst.name,
            "status": lst.status,
            "build_step": lst.build_step,
            "row_count": 0,
            "icp_prompt": prompt,
        },
    }


@router.get("/{workspace_id}")
async def get_workspace(workspace_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    wr = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    ws = wr.scalar_one_or_none()
    if not ws:
        raise HTTPException(404, "Workspace not found")

    lr = await db.execute(
        select(WorkspaceList).where(WorkspaceList.workspace_id == workspace_id).order_by(
            WorkspaceList.updated_at.desc()
        )
    )
    lists = []
    for lst in lr.scalars().all():
        lists.append(
            {
                "id": str(lst.id),
                "name": lst.name,
                "status": lst.status,
                "build_step": lst.build_step,
                "row_count": lst.row_count or 0,
                "icp_prompt": lst.icp_prompt or "",
                "updated_at": lst.updated_at.isoformat() if lst.updated_at else None,
            }
        )

    return {**_ws_dict(ws, len(lists)), "lists": lists}


@router.get("/{workspace_id}/lists/{list_id}")
async def get_list(
    workspace_id: uuid.UUID,
    list_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    lr = await db.execute(
        select(WorkspaceList).where(
            WorkspaceList.id == list_id,
            WorkspaceList.workspace_id == workspace_id,
        )
    )
    lst = lr.scalar_one_or_none()
    if not lst:
        raise HTTPException(404, "List not found")

    rr = await db.execute(
        select(WorkspaceListLead, Lead)
        .outerjoin(Lead, Lead.id == WorkspaceListLead.lead_id)
        .where(WorkspaceListLead.list_id == list_id)
        .order_by(WorkspaceListLead.sort_order.asc())
    )
    rows = [_row_dict(wl, lead) for wl, lead in rr.all()]

    job = build_jobs.get(str(list_id), {})

    return {
        "id": str(lst.id),
        "workspace_id": str(workspace_id),
        "name": lst.name,
        "status": lst.status,
        "build_step": lst.build_step,
        "row_count": lst.row_count or len(rows),
        "icp_prompt": lst.icp_prompt or "",
        "rows": rows,
        "build_job": job,
        "origami_meta": lst.origami_meta or {},
    }


@router.post("/{workspace_id}/lists")
async def create_list(
    workspace_id: uuid.UUID,
    body: CreateListBody,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    wr = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    if not wr.scalar_one_or_none():
        raise HTTPException(404, "Workspace not found")

    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(400, "Prompt required")

    lst = WorkspaceList(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        name=body.name or _list_name_from_prompt(prompt),
        icp_prompt=prompt,
        status="building",
        build_step="Starting...",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(lst)
    ws = await db.get(Workspace, workspace_id)
    if ws:
        ws.updated_at = datetime.utcnow()
    await db.commit()

    _dispatch_list_build(lst.id, prompt, background_tasks)

    return {
        "id": str(lst.id),
        "name": lst.name,
        "status": "building",
    }


@router.get("/{workspace_id}/lists/{list_id}/build-status")
async def list_build_status(workspace_id: uuid.UUID, list_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    lr = await db.execute(
        select(WorkspaceList).where(
            WorkspaceList.id == list_id,
            WorkspaceList.workspace_id == workspace_id,
        )
    )
    lst = lr.scalar_one_or_none()
    if not lst:
        raise HTTPException(404, "List not found")
    job = build_jobs.get(str(list_id), {})
    return {
        "status": lst.status,
        "build_step": lst.build_step,
        "row_count": lst.row_count or 0,
        "job": job,
    }


@router.post("/{workspace_id}/agent/chat")
async def workspace_chat(
    workspace_id: uuid.UUID,
    body: WorkspaceChatBody,
    db: AsyncSession = Depends(get_db),
):
    wr = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    ws = wr.scalar_one_or_none()
    if not ws:
        raise HTTPException(404, "Workspace not found")

    active_list = None
    rows_sample: List[dict] = []
    if body.list_id:
        lr = await db.execute(
            select(WorkspaceList).where(
                WorkspaceList.id == body.list_id,
                WorkspaceList.workspace_id == workspace_id,
            )
        )
        active_list = lr.scalar_one_or_none()
        if active_list:
            rr = await db.execute(
                select(WorkspaceListLead, Lead)
                .outerjoin(Lead, Lead.id == WorkspaceListLead.lead_id)
                .where(WorkspaceListLead.list_id == body.list_id)
                .order_by(WorkspaceListLead.sort_order.asc())
                .limit(8)
            )
            rows_sample = [_row_dict(wl, lead) for wl, lead in rr.all()]

    hist_q = (
        select(AgentChatMessage)
        .where(AgentChatMessage.workspace_id == workspace_id)
        .order_by(AgentChatMessage.created_at.desc())
        .limit(12)
    )
    if body.list_id:
        hist_q = hist_q.where(AgentChatMessage.list_id == body.list_id)
    hist_r = await db.execute(hist_q)
    history = [{"role": m.role, "content": m.content} for m in reversed(list(hist_r.scalars().all()))]

    db.add(
        AgentChatMessage(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            list_id=body.list_id,
            role="user",
            content=body.message,
            created_at=datetime.utcnow(),
        )
    )
    await db.commit()

    result = await workspace_agent_chat(
        body.message,
        workspace={"id": str(ws.id), "name": ws.name},
        active_list={
            "id": str(active_list.id),
            "name": active_list.name,
            "row_count": active_list.row_count,
            "icp_prompt": active_list.icp_prompt,
        }
        if active_list
        else None,
        rows_sample=rows_sample,
        history=history,
        linkedin_connected=bool(load_session()),
    )

    apply = result.get("apply_copy") or {}
    campaign_id = result.get("campaign_id")

    reply_text = result.get("reply", "")
    actions_raw = result.get("suggested_actions") or []
    suggested = [
        {
            "id": a.get("id", str(i)),
            "label": a.get("label", "Continue"),
            "action": a.get("action", "launch_sequences"),
        }
        for i, a in enumerate(actions_raw)
        if isinstance(a, dict)
    ]

    db.add(
        AgentChatMessage(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            list_id=body.list_id,
            role="assistant",
            content=reply_text,
            suggested_actions=[a["label"] for a in suggested],
            created_at=datetime.utcnow(),
        )
    )
    await db.commit()

    return {
        "reply": reply_text,
        "suggested_actions": suggested,
        "apply_copy": apply,
        "campaign_id": campaign_id,
    }


@router.get("/{workspace_id}/agent/history")
async def workspace_agent_history(
    workspace_id: uuid.UUID,
    list_id: Optional[uuid.UUID] = None,
    db: AsyncSession = Depends(get_db),
):
    q = (
        select(AgentChatMessage)
        .where(AgentChatMessage.workspace_id == workspace_id)
        .order_by(AgentChatMessage.created_at.asc())
    )
    if list_id:
        q = q.where(AgentChatMessage.list_id == list_id)
    result = await db.execute(q)
    return [
        {
            "id": str(m.id),
            "role": m.role,
            "content": m.content,
            "suggested_actions": m.suggested_actions or [],
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in result.scalars().all()
    ]


@router.post("/{workspace_id}/lists/{list_id}/launch")
async def launch_from_list(
    workspace_id: uuid.UUID,
    list_id: uuid.UUID,
    body: LaunchFromListBody,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Create campaign from list, enroll all leads, start LinkedIn sequences."""
    lr = await db.execute(
        select(WorkspaceList).where(
            WorkspaceList.id == list_id,
            WorkspaceList.workspace_id == workspace_id,
        )
    )
    lst = lr.scalar_one_or_none()
    if not lst:
        raise HTTPException(404, "List not found")

    wr = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    ws = wr.scalar_one_or_none()

    rr = await db.execute(select(WorkspaceListLead).where(WorkspaceListLead.list_id == list_id))
    list_rows = list(rr.scalars().all())
    if not list_rows:
        raise HTTPException(400, "List has no leads yet")

    conn_tpl = body.connection_note_template or DEFAULT_CONNECTION
    msg_tpl = body.message_template or DEFAULT_FOLLOWUP
    camp_name = body.campaign_name or f"{lst.name} — LinkedIn Outreach"

    campaign = Campaign(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        list_id=list_id,
        name=camp_name,
        connection_note_template=conn_tpl[:300],
        message_template=msg_tpl,
        wait_days_after_accept=body.wait_days_after_accept,
        is_active=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(campaign)

    enrolled = 0
    for row in list_rows:
        lead_id = row.lead_id
        if not lead_id:
            lead = Lead(
                id=uuid.uuid4(),
                name=f"{row.first_name} {row.last_name}".strip(),
                title=row.title,
                company=row.company,
                linkedin_url=row.linkedin_url,
                icp_score=row.icp_score,
            )
            db.add(lead)
            row.lead_id = lead.id
            lead_id = lead.id
        else:
            lead_r = await db.execute(select(Lead).where(Lead.id == lead_id))
            lead = lead_r.scalar_one_or_none()
            if not lead:
                continue

        first = row.first_name or (lead.name or "there").split()[0]
        note = (
            conn_tpl.replace("{{first_name}}", first).replace("{{company}}", row.company or "your company")[:300]
        )
        msg = msg_tpl.replace("{{first_name}}", first).replace("{{company}}", row.company or "your company")

        db.add(
            CampaignEnrollment(
                id=uuid.uuid4(),
                campaign_id=campaign.id,
                lead_id=lead_id,
                status="pending",
                connection_note=note,
                follow_up_message=msg,
            )
        )
        enrolled += 1

    if ws:
        ws.updated_at = datetime.utcnow()
    await db.commit()

    job_id = str(uuid.uuid4())
    campaign_jobs[job_id] = {
        "status": "pending",
        "campaign_id": str(campaign.id),
        "total": enrolled,
        "done": 0,
        "sent": 0,
        "failed": 0,
        "current": None,
        "step": "Starting...",
    }
    background_tasks.add_task(run_campaign_job, job_id, str(campaign.id), None)

    return {
        "campaign_id": str(campaign.id),
        "job_id": job_id,
        "enrolled": enrolled,
        "status": "launching",
    }
