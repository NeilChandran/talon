"""Origami-style workspaces: home prompt → lists → campaigns → LinkedIn."""
import os
import re
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from database import get_db
from services.campaign_runner import campaign_jobs, run_campaign_job
from services.claude_service import workspace_agent_chat
from services.linkedin_service import load_session
from services.list_builder import build_jobs, run_list_build
from store import Record
from user_store import UserStore

router = APIRouter()


def _dispatch_list_build(
    list_id: uuid.UUID,
    prompt: str,
    background_tasks: BackgroundTasks,
) -> None:
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


def _row_dict(r: Record, lead: Optional[Record] = None) -> dict:
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


def _ws_dict(ws: Record, list_count: int = 0) -> dict:
    return {
        "id": str(ws.id),
        "name": ws.name,
        "icon_letter": ws.icon_letter or "T",
        "list_count": list_count,
        "created_at": ws.created_at,
        "updated_at": ws.updated_at,
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
async def list_workspaces(db: UserStore = Depends(get_db)):
    workspaces = await db.list_workspaces()
    out = []
    for ws in workspaces:
        cnt = await db.count_workspace_lists(ws.id)
        out.append(_ws_dict(ws, cnt))
    return out


@router.post("/")
async def create_workspace(body: CreateWorkspaceBody, db: UserStore = Depends(get_db)):
    letter = (body.name.strip()[:1] or "T").upper()
    now = datetime.utcnow().isoformat()
    ws = await db.insert(
        "workspaces",
        {
            "id": str(uuid.uuid4()),
            "name": body.name.strip(),
            "icon_letter": letter,
            "created_at": now,
            "updated_at": now,
        },
    )
    return _ws_dict(ws, 0)


@router.post("/quick-start")
async def quick_start(body: QuickStartBody, background_tasks: BackgroundTasks, db: UserStore = Depends(get_db)):
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(400, "Prompt required")

    name = _workspace_name_from_prompt(prompt)
    letter = name[0].upper() if name else "T"
    now = datetime.utcnow().isoformat()
    ws = await db.insert(
        "workspaces",
        {
            "id": str(uuid.uuid4()),
            "name": name,
            "icon_letter": letter,
            "created_at": now,
            "updated_at": now,
        },
    )

    lst = await db.insert(
        "workspace_lists",
        {
            "id": str(uuid.uuid4()),
            "workspace_id": str(ws.id),
            "name": _list_name_from_prompt(prompt),
            "icp_prompt": prompt,
            "status": "building",
            "build_step": "Starting...",
            "created_at": now,
            "updated_at": now,
        },
    )

    _dispatch_list_build(uuid.UUID(str(lst.id)), prompt, background_tasks)

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
async def get_workspace(workspace_id: uuid.UUID, db: UserStore = Depends(get_db)):
    ws = await db.select_one("workspaces", workspace_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")

    lists = await db.list_workspace_lists(workspace_id)
    list_out = []
    for lst in lists:
        list_out.append(
            {
                "id": str(lst.id),
                "name": lst.name,
                "status": lst.status,
                "build_step": lst.build_step,
                "row_count": lst.row_count or 0,
                "icp_prompt": lst.icp_prompt or "",
                "updated_at": lst.updated_at,
            }
        )

    return {**_ws_dict(ws, len(list_out)), "lists": list_out}


@router.get("/{workspace_id}/lists/{list_id}")
async def get_list(
    workspace_id: uuid.UUID,
    list_id: uuid.UUID,
    db: UserStore = Depends(get_db),
):
    lst = await db.get_workspace_list(list_id, workspace_id)
    if not lst:
        raise HTTPException(404, "List not found")

    pairs = await db.list_workspace_list_leads_joined(list_id)
    rows = [_row_dict(wl, lead) for wl, lead in pairs]
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
    db: UserStore = Depends(get_db),
):
    ws = await db.select_one("workspaces", workspace_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")

    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(400, "Prompt required")

    now = datetime.utcnow().isoformat()
    lst = await db.insert(
        "workspace_lists",
        {
            "id": str(uuid.uuid4()),
            "workspace_id": str(workspace_id),
            "name": body.name or _list_name_from_prompt(prompt),
            "icp_prompt": prompt,
            "status": "building",
            "build_step": "Starting...",
            "created_at": now,
            "updated_at": now,
        },
    )
    await db.update("workspaces", workspace_id, {"updated_at": now})

    _dispatch_list_build(uuid.UUID(str(lst.id)), prompt, background_tasks)

    return {
        "id": str(lst.id),
        "name": lst.name,
        "status": "building",
    }


@router.get("/{workspace_id}/lists/{list_id}/build-status")
async def list_build_status(workspace_id: uuid.UUID, list_id: uuid.UUID, db: UserStore = Depends(get_db)):
    lst = await db.get_workspace_list(list_id, workspace_id)
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
    db: UserStore = Depends(get_db),
):
    ws = await db.select_one("workspaces", workspace_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")

    active_list = None
    rows_sample: List[dict] = []
    if body.list_id:
        active_list = await db.get_workspace_list(body.list_id, workspace_id)
        if active_list:
            pairs = await db.list_workspace_list_leads_joined(body.list_id)
            rows_sample = [_row_dict(wl, lead) for wl, lead in pairs[:8]]

    hist = await db.list_agent_messages(
        workspace_id=workspace_id,
        list_id=body.list_id,
        order="created_at",
        desc=True,
        limit=12,
    )
    history = [{"role": m.role, "content": m.content} for m in reversed(hist)]

    now = datetime.utcnow().isoformat()
    await db.insert(
        "agent_chat_messages",
        {
            "id": str(uuid.uuid4()),
            "workspace_id": str(workspace_id),
            "list_id": str(body.list_id) if body.list_id else None,
            "role": "user",
            "content": body.message,
            "created_at": now,
        },
    )

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

    await db.insert(
        "agent_chat_messages",
        {
            "id": str(uuid.uuid4()),
            "workspace_id": str(workspace_id),
            "list_id": str(body.list_id) if body.list_id else None,
            "role": "assistant",
            "content": reply_text,
            "suggested_actions": [a["label"] for a in suggested],
            "created_at": now,
        },
    )

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
    db: UserStore = Depends(get_db),
):
    messages = await db.list_agent_messages(
        workspace_id=workspace_id,
        list_id=list_id,
        order="created_at",
        desc=False,
    )
    return [
        {
            "id": str(m.id),
            "role": m.role,
            "content": m.content,
            "suggested_actions": m.suggested_actions or [],
            "created_at": m.created_at,
        }
        for m in messages
    ]


@router.post("/{workspace_id}/lists/{list_id}/launch")
async def launch_from_list(
    workspace_id: uuid.UUID,
    list_id: uuid.UUID,
    body: LaunchFromListBody,
    background_tasks: BackgroundTasks,
    db: UserStore = Depends(get_db),
):
    lst = await db.get_workspace_list(list_id, workspace_id)
    if not lst:
        raise HTTPException(404, "List not found")

    ws = await db.select_one("workspaces", workspace_id)
    list_rows = await db.list_workspace_list_leads(list_id)
    if not list_rows:
        raise HTTPException(400, "List has no leads yet")

    conn_tpl = body.connection_note_template or DEFAULT_CONNECTION
    msg_tpl = body.message_template or DEFAULT_FOLLOWUP
    camp_name = body.campaign_name or f"{lst.name} — LinkedIn Outreach"
    now = datetime.utcnow().isoformat()

    campaign = await db.insert(
        "campaigns",
        {
            "id": str(uuid.uuid4()),
            "workspace_id": str(workspace_id),
            "list_id": str(list_id),
            "name": camp_name,
            "connection_note_template": conn_tpl[:300],
            "message_template": msg_tpl,
            "wait_days_after_accept": body.wait_days_after_accept,
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        },
    )

    enrolled = 0
    for row in list_rows:
        lead_id = row.lead_id
        if not lead_id:
            lead_id = str(uuid.uuid4())
            name = f"{row.first_name} {row.last_name}".strip()
            await db.insert(
                "leads",
                {
                    "id": lead_id,
                    "name": name,
                    "title": row.title,
                    "company": row.company,
                    "linkedin_url": row.linkedin_url,
                    "icp_score": row.icp_score,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            await db.update(
                "workspace_list_leads",
                row.id,
                {"lead_id": lead_id},
            )
        else:
            lead = await db.select_one("leads", lead_id)
            if not lead:
                continue

        first = row.first_name or "there"
        if lead_id:
            lead = await db.select_one("leads", lead_id)
            if lead and lead.name:
                first = row.first_name or (lead.name or "there").split()[0]

        note = conn_tpl.replace("{{first_name}}", first).replace("{{company}}", row.company or "your company")[:300]
        msg = msg_tpl.replace("{{first_name}}", first).replace("{{company}}", row.company or "your company")

        await db.insert(
            "campaign_enrollments",
            {
                "id": str(uuid.uuid4()),
                "campaign_id": str(campaign.id),
                "lead_id": str(lead_id),
                "status": "pending",
                "connection_note": note,
                "follow_up_message": msg,
                "created_at": now,
                "updated_at": now,
            },
        )
        enrolled += 1

    if ws:
        await db.update("workspaces", workspace_id, {"updated_at": now})

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
