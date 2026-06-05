"""Origami-style explore API: ICP prompt → parallel scrapers → table."""
import csv
import io
import uuid
from datetime import datetime
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse

from database import get_db
from schemas import (
    ExploreEnrichRequest,
    ExploreFilterRule,
    ExploreRefineRequest,
    ExploreRowResponse,
    ExploreRowUpdate,
    ExploreSessionCreate,
    ExploreSessionResponse,
)
from services.explore.enrichment import enrich_cell
from services.explore.icp_parser import parse_icp_prompt
from services.explore.orchestrator import get_job_state, run_explore_pipeline, _persist_rows
from services.explore.refinement import parse_refinement
from services.explore.scoring import apply_filter_rules, score_row
from services.explore.scrapers.claude_companies import generate_companies_for_source
from services.explore.scrapers.base import dedupe_rows
from store import Record
from user_store import UserStore, get_store

router = APIRouter()


def _row_dict(row: Record) -> dict:
    return {
        "company_name": row.company_name,
        "website": row.website,
        "industry": row.industry,
        "headcount": row.headcount,
        "location": row.location,
        "source": row.source,
        "enrichment": row.enrichment or {},
    }


def _explore_row_response(row: Record, rules: list, hidden_override: bool = None) -> dict:
    d = ExploreRowResponse.model_validate({
        "id": row.id,
        "session_id": row.session_id,
        "company_name": row.company_name,
        "website": row.website,
        "industry": row.industry,
        "headcount": row.headcount,
        "location": row.location,
        "source": row.source,
        "raw_data": row.raw_data or {},
        "fit_score": row.fit_score or 0,
        "enrichment": row.enrichment or {},
        "hidden": row.hidden or False,
        "created_at": row.created_at,
    }).model_dump()
    if hidden_override is not None:
        d["hidden"] = hidden_override
    else:
        d["hidden"] = row.hidden or not apply_filter_rules(_row_dict(row), rules)
    return d


async def _session_response(db: SupabaseStore, session: Record) -> dict:
    rows = await db.list_explore_rows(session.id, order="fit_score", desc=True)
    rules = session.filter_rules or []
    visible = [_explore_row_response(row, rules) for row in rows]

    messages_raw = await db.list_explore_messages(session.id)
    messages = [
        {
            "id": str(m.id),
            "role": m.role,
            "content": m.content,
            "meta": m.meta or {},
            "created_at": m.created_at,
        }
        for m in messages_raw
    ]

    scraper_status = session.scraper_status or get_job_state(str(session.id)).get("scrapers", {})

    return {
        "id": uuid.UUID(str(session.id)),
        "icp_prompt": session.icp_prompt,
        "parsed_icp": session.parsed_icp or {},
        "status": session.status,
        "scraper_status": scraper_status,
        "filter_rules": session.filter_rules or [],
        "enrichment_columns": session.enrichment_columns or [],
        "rows": visible,
        "messages": messages,
        "created_at": session.created_at,
    }


@router.post("/sessions", response_model=ExploreSessionResponse)
async def create_session(body: ExploreSessionCreate, background_tasks: BackgroundTasks, db: UserStore = Depends(get_db)):
    prompt = body.icp_prompt.strip()
    if not prompt:
        raise HTTPException(400, "ICP prompt is required")

    parsed = await parse_icp_prompt(prompt)
    now = datetime.utcnow().isoformat()
    session = await db.insert(
        "explore_sessions",
        {
            "id": str(uuid.uuid4()),
            "icp_prompt": prompt,
            "parsed_icp": parsed,
            "status": "running",
            "scraper_status": {},
            "filter_rules": [],
            "enrichment_columns": [],
            "created_at": now,
            "updated_at": now,
        },
    )

    sid = uuid.UUID(str(session.id))

    async def _run():
        store = get_store()
        await run_explore_pipeline(sid, store)

    background_tasks.add_task(_run)

    return await _session_response(db, session)


@router.get("/sessions/{session_id}", response_model=ExploreSessionResponse)
async def get_session(session_id: uuid.UUID, db: UserStore = Depends(get_db)):
    session = await db.select_one("explore_sessions", session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return await _session_response(db, session)


@router.patch("/sessions/{session_id}/rows/{row_id}")
async def update_row(
    session_id: uuid.UUID,
    row_id: uuid.UUID,
    body: ExploreRowUpdate,
    db: UserStore = Depends(get_db),
):
    rows = await db.select_many(
        "explore_rows",
        filters={"id": str(row_id), "session_id": str(session_id)},
        limit=1,
    )
    row = rows[0] if rows else None
    if not row:
        raise HTTPException(404, "Row not found")

    patch = {}
    for field in ("company_name", "website", "industry", "headcount", "location"):
        val = getattr(body, field, None)
        if val is not None:
            patch[field] = val

    sess = await db.select_one("explore_sessions", session_id)
    merged = {**_row_dict(row), **patch}
    if sess:
        patch["fit_score"] = score_row(merged, sess.parsed_icp or {}, sess.icp_prompt)

    await db.update("explore_rows", row_id, patch)
    return {"ok": True, "fit_score": patch.get("fit_score", row.fit_score)}


@router.post("/sessions/{session_id}/refine")
async def refine_session(session_id: uuid.UUID, body: ExploreRefineRequest, background_tasks: BackgroundTasks, db: UserStore = Depends(get_db)):
    session = await db.select_one("explore_sessions", session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    now = datetime.utcnow().isoformat()
    await db.insert(
        "explore_chat_messages",
        {
            "id": str(uuid.uuid4()),
            "session_id": str(session.id),
            "role": "user",
            "content": body.message,
            "created_at": now,
        },
    )

    cols = [c.get("key") for c in (session.enrichment_columns or [])]
    explore_rows = await db.list_explore_rows(session.id)
    row_count = len(explore_rows)

    plan = await parse_refinement(body.message, session.icp_prompt, cols, row_count)
    action = plan.get("action", "rescore")
    reply = plan.get("explanation", "Done.")

    session_patch: dict = {"updated_at": now}

    if action == "filter" and plan.get("filter_rules"):
        session_patch["filter_rules"] = list(session.filter_rules or []) + plan["filter_rules"]
    elif action == "update_icp" and plan.get("icp_addendum"):
        new_prompt = session.icp_prompt + "\n" + plan["icp_addendum"]
        session_patch["icp_prompt"] = new_prompt
        session_patch["parsed_icp"] = await parse_icp_prompt(new_prompt)
    elif action == "add_column" and plan.get("enrichment_column"):
        ec = plan["enrichment_column"]
        cols_list = list(session.enrichment_columns or [])
        if not any(c.get("key") == ec.get("key") for c in cols_list):
            cols_list.append(ec)
        session_patch["enrichment_columns"] = cols_list
        background_tasks.add_task(_enrich_column_all, str(session.id), ec.get("key"), ec.get("type", "tech_stack"))
    elif action in ("add_rows", "find_people"):
        hint = plan.get("search_hint") or body.message
        parsed = {**(session.parsed_icp or {}), "keywords": hint}
        new_rows = await generate_companies_for_source(parsed, "refinement", count=8)
        session_fresh = await db.select_one("explore_sessions", session_id)
        if session_fresh:
            await _persist_rows(db, session_fresh, dedupe_rows(new_rows), parsed)

    if action in ("rescore", "update_icp", "filter"):
        sess = await db.select_one("explore_sessions", session_id)
        parsed_icp = (sess.parsed_icp if sess else session.parsed_icp) or {}
        icp_prompt = sess.icp_prompt if sess else session.icp_prompt
        for row in await db.list_explore_rows(session_id):
            fit = score_row(_row_dict(row), parsed_icp, icp_prompt)
            await db.update("explore_rows", row.id, {"fit_score": fit})

    if len(session_patch) > 1:
        await db.update("explore_sessions", session_id, session_patch)

    await db.insert(
        "explore_chat_messages",
        {
            "id": str(uuid.uuid4()),
            "session_id": str(session.id),
            "role": "assistant",
            "content": reply,
            "meta": plan,
            "created_at": now,
        },
    )

    session = await db.select_one("explore_sessions", session_id)
    return await _session_response(db, session)


async def _enrich_column_all(session_id: str, column_key: str, column_type: str):
    db = get_store()
    sid = uuid.UUID(session_id)
    sess = await db.select_one("explore_sessions", sid)
    if not sess:
        return

    rows = await db.list_explore_rows(sid)
    for row in rows:
        enrich = dict(row.enrichment or {})
        enrich[column_key] = {"value": "", "status": "loading"}
        await db.update("explore_rows", row.id, {"enrichment": enrich})

    for row in await db.list_explore_rows(sid):
        try:
            row_fresh = await db.select_one("explore_rows", row.id)
            result = await enrich_cell(_row_dict(row_fresh or row), column_type, sess.icp_prompt)
        except Exception as e:
            result = {"value": "Error", "status": "error", "meta": {"error": str(e)[:100]}}
        enrich = dict((row_fresh or row).enrichment or {})
        enrich[column_key] = result
        await db.update("explore_rows", row.id, {"enrichment": enrich})


@router.post("/sessions/{session_id}/enrich")
async def add_enrichment_column(
    session_id: uuid.UUID,
    body: ExploreEnrichRequest,
    background_tasks: BackgroundTasks,
    db: UserStore = Depends(get_db),
):
    session = await db.select_one("explore_sessions", session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    cols = list(session.enrichment_columns or [])
    if not any(c.get("key") == body.column_key for c in cols):
        cols.append({"key": body.column_key, "type": body.column_type, "label": body.column_key.replace("_", " ").title()})
    await db.update("explore_sessions", session_id, {"enrichment_columns": cols})

    background_tasks.add_task(_enrich_column_all, str(session.id), body.column_key, body.column_type)
    session = await db.select_one("explore_sessions", session_id)
    return await _session_response(db, session)


@router.put("/sessions/{session_id}/filters")
async def set_filters(
    session_id: uuid.UUID,
    rules: List[ExploreFilterRule],
    db: UserStore = Depends(get_db),
):
    session = await db.select_one("explore_sessions", session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    await db.update(
        "explore_sessions",
        session_id,
        {"filter_rules": [rule.model_dump() for rule in rules]},
    )
    session = await db.select_one("explore_sessions", session_id)
    return await _session_response(db, session)


@router.get("/sessions/{session_id}/export.csv")
async def export_csv(session_id: uuid.UUID, db: UserStore = Depends(get_db)):
    session = await db.select_one("explore_sessions", session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    data = await _session_response(db, session)
    enrich_cols = session.enrichment_columns or []
    base_cols = ["Company", "Website", "Industry", "Headcount", "Location", "Source", "Fit Score"]
    extra_labels = [c.get("label", c.get("key", "")) for c in enrich_cols]

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(base_cols + extra_labels)

    rules = session.filter_rules or []
    for row in data["rows"]:
        if row.get("hidden"):
            continue
        if not apply_filter_rules(
            {
                "company_name": row["company_name"],
                "website": row["website"],
                "industry": row["industry"],
                "headcount": row["headcount"],
                "location": row["location"],
                "source": row["source"],
                "fit_score": row["fit_score"],
                "enrichment": row.get("enrichment", {}),
            },
            rules,
        ):
            continue
        enrich = row.get("enrichment") or {}
        extra_vals = []
        for c in enrich_cols:
            cell = enrich.get(c.get("key"), {})
            extra_vals.append(cell.get("value", "") if isinstance(cell, dict) else str(cell))
        w.writerow(
            [
                row["company_name"],
                row["website"],
                row["industry"],
                row["headcount"],
                row["location"],
                row["source"],
                row["fit_score"],
            ]
            + extra_vals
        )

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="talon-explore-{session_id}.csv"'},
    )
