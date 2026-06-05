"""Build Talon workspace lists via Origami API v2 agent."""
import asyncio
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from services.lead_agent import _lead_exists
from services.origami_service import (
    create_agent_run,
    extract_primary_table,
    fetch_table_rows,
    map_origami_row,
    poll_run_until_done,
)
from store import get_store


async def _save_rows(
    list_id: uuid.UUID,
    search_id: uuid.UUID,
    rows: list,
    *,
    replace: bool,
) -> int:
    db = get_store()
    if replace:
        await db.delete_workspace_list_leads(list_id)

    saved = 0
    now = datetime.utcnow().isoformat()
    for i, raw in enumerate(rows):
        p = map_origami_row(raw if isinstance(raw, dict) else {})
        li = p.get("linkedin_url", "")
        em = p.get("email", "")
        if await _lead_exists(db, li, em) and not replace:
            continue
        first, last = p.get("first_name", ""), p.get("last_name", "")
        lead_id = str(uuid.uuid4())
        await db.insert(
            "leads",
            {
                "id": lead_id,
                "search_id": str(search_id),
                "name": p.get("name", ""),
                "first_name": first,
                "last_name": last,
                "title": p.get("title", ""),
                "company": p.get("company", ""),
                "email": em,
                "linkedin_url": li,
                "icp_score": p.get("icp_score", 7),
                "score_reason": p.get("score_reason", ""),
                "source_url": p.get("source_url", li),
                "sequence_status": "new",
                "created_at": now,
                "updated_at": now,
            },
        )
        await db.insert(
            "workspace_list_leads",
            {
                "id": str(uuid.uuid4()),
                "list_id": str(list_id),
                "lead_id": lead_id,
                "first_name": first,
                "last_name": last,
                "title": p.get("title", ""),
                "company": p.get("company", ""),
                "linkedin_url": li,
                "icp_score": p.get("icp_score", 7),
                "extra": {"email": em, "score_reason": p.get("score_reason", ""), "source": "origami"},
                "sort_order": i,
                "created_at": now,
            },
        )
        saved += 1

    wl = await db.get_workspace_list(list_id)
    if wl:
        await db.update("workspace_lists", list_id, {"row_count": saved})
    return saved


async def run_origami_list_build(
    list_id: uuid.UUID,
    prompt: str,
    job: Optional[Dict[str, Any]] = None,
) -> None:
    lid = str(list_id)
    search_id = uuid.uuid4()

    db = get_store()
    wl = await db.get_workspace_list(list_id)
    if not wl:
        if job:
            job["status"] = "failed"
            job["error"] = "List not found"
        return

    now = datetime.utcnow().isoformat()
    await db.update(
        "workspace_lists",
        list_id,
        {
            "status": "building",
            "build_step": "Starting Origami agent…",
            "icp_prompt": prompt,
            "updated_at": now,
        },
    )
    await db.insert(
        "searches",
        {
            "id": str(search_id),
            "prompt": prompt,
            "list_id": str(list_id),
            "status": "running",
            "created_at": now,
        },
    )

    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    table_id: Optional[str] = None

    async def on_tick(run: Dict[str, Any]):
        nonlocal table_id
        status = run.get("status", "running")
        step = {
            "running": "Origami agent running…",
            "needs_input": "Origami needs your input — check Origami dashboard",
            "completed": "Fetching leads from Origami table…",
        }.get(status, f"Origami: {status}")
        if job:
            job["step"] = step
        store = get_store()
        wl_tick = await store.get_workspace_list(list_id)
        if wl_tick:
            await store.update("workspace_lists", list_id, {"build_step": step})
        tbl = extract_primary_table(run)
        if tbl and tbl.get("id"):
            table_id = tbl["id"]
            try:
                partial = await fetch_table_rows(table_id)
                if partial:
                    await _save_rows(list_id, search_id, partial, replace=True)
                    if job:
                        job["count"] = len(partial)
            except Exception as e:
                print(f"[origami] partial sync: {e}", flush=True)

    try:
        if job:
            job["step"] = "Generating search queries…"
        await _update_step(list_id, "Generating search queries…", job)

        admission = await create_agent_run(
            f"Find up to {50} leads matching: {prompt}. Include first name, last name, title, company, LinkedIn URL, and work email when available."
        )
        agent = admission.get("agent") or {}
        run0 = admission.get("run") or {}
        agent_id = agent.get("id") or admission.get("agentId")
        run_id = run0.get("id") or admission.get("runId")
        if not agent_id or not run_id:
            raise RuntimeError("Origami did not return agent/run ids")

        if job:
            job["step"] = "Running search agents…"
        await _update_step(list_id, "Running 15 searches…", job)

        terminal = await poll_run_until_done(agent_id, run_id, on_tick=on_tick)

        status = terminal.get("status")
        if status == "needs_input":
            raise RuntimeError(
                "Origami agent needs input — answer pending questions in Origami or refine your prompt."
            )
        if status in ("errored", "timed_out", "cancelled"):
            raise RuntimeError(f"Origami run ended with status: {status}")

        tbl = extract_primary_table(terminal)
        if not tbl or not tbl.get("id"):
            from services.origami_service import ORIGAMI_BASE, _headers
            import httpx

            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{ORIGAMI_BASE}/api/v2/agents/{agent_id}/runs",
                    headers=_headers(),
                    json={"prompt": "Build the table now from your prior research. Materialize all leads you found."},
                )
                if resp.status_code in (200, 202):
                    run2 = resp.json().get("run") or resp.json()
                    run_id2 = run2.get("id")
                    if run_id2:
                        terminal = await poll_run_until_done(agent_id, run_id2, on_tick=on_tick)
                        tbl = extract_primary_table(terminal)

        if not tbl or not tbl.get("id"):
            raise RuntimeError("Origami completed but no table was created")

        table_id = tbl["id"]
        table_url = tbl.get("url", "")

        if job:
            job["step"] = "Enriching leads…"
        await _update_step(list_id, "Enriching leads…", job)

        cells_running = (tbl.get("cells") or {}).get("running", 0)
        if cells_running > 0:
            await _update_step(list_id, f"Enriching leads… ({cells_running} cells still loading)", job)
            for _ in range(18):
                await asyncio.sleep(10)
                partial = await fetch_table_rows(table_id)
                if partial:
                    saved = await _save_rows(list_id, search_id, partial, replace=True)
                    if job:
                        job["count"] = saved

        if job:
            job["step"] = "Scoring leads…"
        await _update_step(list_id, "Scoring leads…", job)

        rows = await fetch_table_rows(table_id)
        if not rows:
            raise RuntimeError("Origami table is empty after run completed")

        saved = await _save_rows(list_id, search_id, rows, replace=True)

        done_now = datetime.utcnow().isoformat()
        await db.update(
            "workspace_lists",
            list_id,
            {
                "status": "ready",
                "row_count": saved,
                "build_step": f"Done — {saved} leads (Origami)",
                "origami_meta": {
                    "agentId": agent_id,
                    "tableId": table_id,
                    "tableUrl": table_url,
                    "runId": run_id,
                },
                "updated_at": done_now,
            },
        )
        await db.update_search(search_id, status="completed")
        wl = await db.get_workspace_list(list_id)
        if wl:
            await db.update("workspaces", wl.workspace_id, {"updated_at": done_now})

        if job:
            job["status"] = "completed"
            job["count"] = saved
            job["step"] = f"Done — {saved} leads"
            job["origami_table_url"] = table_url

    except Exception as e:
        print(f"[origami_list_builder] {list_id}: {e}", flush=True)
        if job:
            job["status"] = "failed"
            job["error"] = str(e)[:200]
        wl = await db.get_workspace_list(list_id)
        if wl:
            await db.update(
                "workspace_lists",
                list_id,
                {"status": "failed", "build_step": str(e)[:200]},
            )


async def _update_step(list_id: uuid.UUID, step: str, job: Optional[Dict[str, Any]]):
    if job is not None:
        job["step"] = step
    db = get_store()
    wl = await db.get_workspace_list(list_id)
    if wl:
        await db.update("workspace_lists", list_id, {"build_step": step})
