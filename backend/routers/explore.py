"""Origami-style explore API: ICP prompt → parallel scrapers → table."""
import asyncio
import csv
import io
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal, get_db
from models import ExploreChatMessage, ExploreRow, ExploreSession
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
from services.explore.orchestrator import get_job_state, run_explore_pipeline
from services.explore.refinement import parse_refinement
from services.explore.scoring import apply_filter_rules, score_row
from services.explore.scrapers.claude_companies import generate_companies_for_source
from services.explore.scrapers.base import dedupe_rows
from services.explore.orchestrator import _persist_rows  # noqa: F401 — used in refine

router = APIRouter()


def _row_dict(row: ExploreRow) -> dict:
    return {
        "company_name": row.company_name,
        "website": row.website,
        "industry": row.industry,
        "headcount": row.headcount,
        "location": row.location,
        "source": row.source,
        "enrichment": row.enrichment or {},
    }


async def _session_response(db: AsyncSession, session: ExploreSession) -> dict:
    rows_r = await db.execute(
        select(ExploreRow)
        .where(ExploreRow.session_id == session.id)
        .order_by(ExploreRow.fit_score.desc(), ExploreRow.created_at)
    )
    rows = list(rows_r.scalars().all())
    rules = session.filter_rules or []
    visible = []
    for row in rows:
        d = ExploreRowResponse.model_validate(row).model_dump()
        d["hidden"] = row.hidden or not apply_filter_rules(_row_dict(row), rules)
        visible.append(d)

    msg_r = await db.execute(
        select(ExploreChatMessage)
        .where(ExploreChatMessage.session_id == session.id)
        .order_by(ExploreChatMessage.created_at)
    )
    messages = [
        {
            "id": str(m.id),
            "role": m.role,
            "content": m.content,
            "meta": m.meta or {},
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in msg_r.scalars().all()
    ]

    scraper_status = session.scraper_status or get_job_state(str(session.id)).get("scrapers", {})

    return {
        "id": session.id,
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
async def create_session(body: ExploreSessionCreate, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    prompt = body.icp_prompt.strip()
    if not prompt:
        raise HTTPException(400, "ICP prompt is required")

    parsed = await parse_icp_prompt(prompt)
    session = ExploreSession(
        id=uuid.uuid4(),
        icp_prompt=prompt,
        parsed_icp=parsed,
        status="running",
        scraper_status={},
        filter_rules=[],
        enrichment_columns=[],
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    async def _run():
        async with AsyncSessionLocal() as bg_db:
            await run_explore_pipeline(session.id, bg_db)

    background_tasks.add_task(_run)

    return await _session_response(db, session)


@router.get("/sessions/{session_id}", response_model=ExploreSessionResponse)
async def get_session(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(ExploreSession).where(ExploreSession.id == session_id))
    session = r.scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Session not found")
    return await _session_response(db, session)


@router.patch("/sessions/{session_id}/rows/{row_id}")
async def update_row(
    session_id: uuid.UUID,
    row_id: uuid.UUID,
    body: ExploreRowUpdate,
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(
        select(ExploreRow).where(ExploreRow.id == row_id, ExploreRow.session_id == session_id)
    )
    row = r.scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Row not found")
    for field in ("company_name", "website", "industry", "headcount", "location"):
        val = getattr(body, field, None)
        if val is not None:
            setattr(row, field, val)
    sess_r = await db.execute(select(ExploreSession).where(ExploreSession.id == session_id))
    sess = sess_r.scalar_one_or_none()
    if sess:
        row.fit_score = score_row(_row_dict(row), sess.parsed_icp or {}, sess.icp_prompt)
    await db.commit()
    return {"ok": True, "fit_score": row.fit_score}


@router.post("/sessions/{session_id}/refine")
async def refine_session(session_id: uuid.UUID, body: ExploreRefineRequest, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(ExploreSession).where(ExploreSession.id == session_id))
    session = r.scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Session not found")

    db.add(
        ExploreChatMessage(
            id=uuid.uuid4(),
            session_id=session.id,
            role="user",
            content=body.message,
            created_at=datetime.utcnow(),
        )
    )
    await db.commit()

    cols = [c.get("key") for c in (session.enrichment_columns or [])]
    rows_r = await db.execute(select(ExploreRow).where(ExploreRow.session_id == session.id))
    row_count = len(list(rows_r.scalars().all()))

    plan = await parse_refinement(body.message, session.icp_prompt, cols, row_count)
    action = plan.get("action", "rescore")
    reply = plan.get("explanation", "Done.")

    if action == "filter" and plan.get("filter_rules"):
        session.filter_rules = list(session.filter_rules or []) + plan["filter_rules"]
    elif action == "update_icp" and plan.get("icp_addendum"):
        session.icp_prompt = session.icp_prompt + "\n" + plan["icp_addendum"]
        session.parsed_icp = await parse_icp_prompt(session.icp_prompt)
    elif action == "add_column" and plan.get("enrichment_column"):
        ec = plan["enrichment_column"]
        cols_list = list(session.enrichment_columns or [])
        if not any(c.get("key") == ec.get("key") for c in cols_list):
            cols_list.append(ec)
        session.enrichment_columns = cols_list
        background_tasks.add_task(_enrich_column_all, str(session.id), ec.get("key"), ec.get("type", "tech_stack"))
    elif action in ("add_rows", "find_people"):
        hint = plan.get("search_hint") or body.message
        parsed = {**(session.parsed_icp or {}), "keywords": hint}
        new_rows = await generate_companies_for_source(parsed, "refinement", count=8)
        await _persist_rows(db, session, dedupe_rows(new_rows), parsed)

    if action in ("rescore", "update_icp", "filter"):
        rows_r = await db.execute(select(ExploreRow).where(ExploreRow.session_id == session.id))
        for row in rows_r.scalars().all():
            row.fit_score = score_row(_row_dict(row), session.parsed_icp or {}, session.icp_prompt)

    db.add(
        ExploreChatMessage(
            id=uuid.uuid4(),
            session_id=session.id,
            role="assistant",
            content=reply,
            meta=plan,
            created_at=datetime.utcnow(),
        )
    )
    session.updated_at = datetime.utcnow()
    await db.commit()
    return await _session_response(db, session)


async def _enrich_column_all(session_id: str, column_key: str, column_type: str):
    async with AsyncSessionLocal() as db:
        sid = uuid.UUID(session_id)
        sess_r = await db.execute(select(ExploreSession).where(ExploreSession.id == sid))
        sess = sess_r.scalar_one_or_none()
        if not sess:
            return
        rows_r = await db.execute(select(ExploreRow).where(ExploreRow.session_id == sid))
        for row in rows_r.scalars().all():
            enrich = dict(row.enrichment or {})
            enrich[column_key] = {"value": "", "status": "loading"}
            row.enrichment = enrich
        await db.commit()

        rows_r = await db.execute(select(ExploreRow).where(ExploreRow.session_id == sid))
        for row in rows_r.scalars().all():
            try:
                result = await enrich_cell(_row_dict(row), column_type, sess.icp_prompt)
            except Exception as e:
                result = {"value": "Error", "status": "error", "meta": {"error": str(e)[:100]}}
            enrich = dict(row.enrichment or {})
            enrich[column_key] = result
            row.enrichment = enrich
            await db.commit()


@router.post("/sessions/{session_id}/enrich")
async def add_enrichment_column(
    session_id: uuid.UUID,
    body: ExploreEnrichRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(ExploreSession).where(ExploreSession.id == session_id))
    session = r.scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Session not found")

    cols = list(session.enrichment_columns or [])
    if not any(c.get("key") == body.column_key for c in cols):
        cols.append({"key": body.column_key, "type": body.column_type, "label": body.column_key.replace("_", " ").title()})
    session.enrichment_columns = cols
    await db.commit()

    background_tasks.add_task(_enrich_column_all, str(session.id), body.column_key, body.column_type)
    return await _session_response(db, session)


@router.put("/sessions/{session_id}/filters")
async def set_filters(
    session_id: uuid.UUID,
    rules: List[ExploreFilterRule],
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(ExploreSession).where(ExploreSession.id == session_id))
    session = r.scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Session not found")
    session.filter_rules = [rule.model_dump() for rule in rules]
    await db.commit()
    return await _session_response(db, session)


@router.get("/sessions/{session_id}/export.csv")
async def export_csv(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(ExploreSession).where(ExploreSession.id == session_id))
    session = r.scalar_one_or_none()
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
