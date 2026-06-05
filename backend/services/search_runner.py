"""Origami-only search pipeline — poll, store leads in Supabase, heuristic score."""
import asyncio
import os
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from store import get_store
from services.origami_service import (
    build_auto_answer,
    build_outreach_schedule,
    build_search_prompt,
    continue_agent_run,
    count_rows_with_drafts,
    create_agent_run,
    ensure_linkedin_drafts,
    extract_primary_table,
    fetch_table_rows,
    get_run,
    launch_origami_sequences,
    linkedin_slug,
    map_origami_row,
    normalize_linkedin_url,
    parse_agent_run_ids,
    parse_pending_questions,
    poll_run_until_done,
    release_research_capacity,
    resolve_live_table,
    run_progress_message,
    user_facing_message,
    wants_founders,
)
from services.outreach_templates import fit_connection_note
from services.outreach_templates import build_outreach_kit

search_jobs: Dict[str, Dict[str, Any]] = {}
_run_locks: Dict[str, asyncio.Lock] = {}


def _is_stale_agent_error(err: BaseException) -> bool:
    msg = str(err).lower()
    return "agent_not_found" in msg or ("404" in msg and "agent" in msg)


def heuristic_score(lead: Dict[str, Any], prompt: str) -> int:
    s = 5
    prompt_l = prompt.lower()
    title = (lead.get("title") or "").lower()
    company = (lead.get("company") or "").lower()
    if lead.get("email"):
        s += 2
    if lead.get("linkedin_url"):
        s += 1
    senior = ("vp", "vice president", "director", "head of", "chief", "ceo", "founder", "president")
    if any(t in title for t in senior):
        s += 1
    if "saas" in prompt_l and ("saas" in company or "software" in company):
        s += 1
    if "series" in prompt_l and any(x in company + title for x in ("series", "raised", "funding")):
        s += 1
    return max(1, min(10, s))


async def _update_search(
    search_id: uuid.UUID,
    *,
    status: Optional[str] = None,
    message: Optional[str] = None,
    lead_count: Optional[int] = None,
    origami_job_id: Optional[str] = None,
    table_id: Optional[str] = None,
    table_url: Optional[str] = None,
):
    sid = str(search_id)
    db = get_store()
    patch: Dict[str, Any] = {}
    if status is not None:
        patch["status"] = status
    if lead_count is not None:
        patch["lead_count"] = lead_count
    if origami_job_id is not None:
        patch["origami_job_id"] = origami_job_id
    if table_id is not None:
        patch["origami_table_id"] = table_id
    if table_url is not None:
        patch["origami_table_url"] = table_url
    if message is not None:
        patch["status_message"] = user_facing_message(message)
    if patch:
        await db.update_search(search_id, **patch)
    if sid in search_jobs and message:
        search_jobs[sid]["step"] = user_facing_message(message)
    if sid in search_jobs and lead_count is not None:
        search_jobs[sid]["count"] = lead_count


def _lead_match_key(first: str, last: str, company: str) -> str:
    return "|".join(
        x.lower().strip()
        for x in (first or "", last or "", company or "")
        if x.strip()
    )


def _is_founder_person(p: Dict[str, Any], *, want_founders: bool) -> bool:
    if not want_founders:
        return True
    if p.get("first_name") or p.get("last_name"):
        return True
    li = (p.get("linkedin_url") or "").lower()
    if "/in/" in li:
        return True
    title = (p.get("title") or "").lower()
    return any(t in title for t in ("founder", "ceo", "co-founder", "cofounder"))


async def _save_leads(
    search_id: uuid.UUID,
    rows: list,
    prompt: str,
    *,
    replace: bool,
    merge: bool = False,
    want_founders: bool = False,
) -> int:
    db = get_store()
    srow = await db.get_search(search_id)
    user_id = str(srow.user_id) if srow and srow.user_id else None
    if replace and not merge:
        if user_id:
            await db.delete_where(
                "leads", {"search_id": str(search_id), "user_id": user_id}
            )
        else:
            await db.delete_leads_for_search(search_id)

    slug_to_lead: dict[str, Record] = {}
    name_to_lead: dict[str, Record] = {}
    if merge:
        filters: dict = {"search_id": str(search_id)}
        if user_id:
            filters["user_id"] = user_id
        rows_existing = await db.select_many("leads", filters=filters)
        for r in rows_existing:
            slug = linkedin_slug(r.linkedin_url or "")
            if slug:
                slug_to_lead[slug] = r
            nk = _lead_match_key(r.first_name or "", r.last_name or "", r.company or "")
            if nk:
                name_to_lead[nk] = r

    saved = 0
    for raw in rows:
        p = map_origami_row(raw if isinstance(raw, dict) else {})
        if not _is_founder_person(p, want_founders=want_founders):
            continue
        email = (p.get("email") or "").strip()
        if email and user_id and await db.lead_email_exists_for_user(email, user_id):
            continue
        if email and not user_id and await db.lead_email_exists(email):
            continue
        if email:
            email = email.lower()
        li = normalize_linkedin_url(p.get("linkedin_url") or "")
        origami_sc = p.get("origami_score")
        sc = origami_sc if origami_sc is not None else heuristic_score(p, prompt)
        draft = fit_connection_note((p.get("linkedin_draft") or "").strip())
        follow = (p.get("follow_up_draft") or "").strip()
        profile_id = (p.get("linkedin_profile_id") or "").strip()

        existing: Optional[Record] = None
        if merge:
            slug = linkedin_slug(li)
            if slug:
                existing = slug_to_lead.get(slug)
            if not existing:
                nk = _lead_match_key(
                    p.get("first_name", ""), p.get("last_name", ""), p.get("company", "")
                )
                if nk:
                    existing = name_to_lead.get(nk)

        if merge and existing:
            patch: Dict[str, Any] = {}
            if li and not (existing.linkedin_url or "").strip():
                patch["linkedin_url"] = li
            elif li and linkedin_slug(existing.linkedin_url or "") != linkedin_slug(li):
                patch["linkedin_url"] = li
            if p.get("first_name") and not (existing.first_name or "").strip():
                patch["first_name"] = p["first_name"]
            if p.get("last_name") and not (existing.last_name or "").strip():
                patch["last_name"] = p["last_name"]
            if p.get("name") and not (existing.name or "").strip():
                patch["name"] = p["name"]
            if p.get("title") and not (existing.title or "").strip():
                patch["title"] = p["title"]
            if p.get("company") and not (existing.company or "").strip():
                patch["company"] = p["company"]
            if profile_id and not (getattr(existing, "linkedin_profile_id", None) or "").strip():
                patch["linkedin_profile_id"] = profile_id
            if origami_sc is not None:
                patch["score"] = sc
                patch["icp_score"] = sc
            if draft:
                patch["linkedin_draft"] = draft
                patch["sequence_status"] = "drafted"
            elif (existing.sequence_status or "") in ("drafted", "failed"):
                if li:
                    patch["sequence_status"] = "new"
            if follow:
                patch["follow_up_draft"] = follow
            if (existing.sequence_status or "") == "failed" and li and draft:
                patch["sequence_status"] = "drafted"
            if patch:
                await db.update_lead(existing.id, **patch)
                if li:
                    slug_to_lead[linkedin_slug(li)] = existing
            saved += 1
            continue

        slug = linkedin_slug(li)
        if merge and slug and slug in slug_to_lead:
            continue
        new_row = await db.insert_lead(
            {
                "search_id": str(search_id),
                "user_id": user_id,
                "first_name": p.get("first_name", ""),
                "last_name": p.get("last_name", ""),
                "name": p.get("name", ""),
                "title": p.get("title", ""),
                "company": p.get("company", ""),
                "email": email,
                "linkedin_url": li,
                "linkedin_profile_id": profile_id or None,
                "linkedin_draft": draft or None,
                "follow_up_draft": follow or None,
                "score": sc,
                "icp_score": sc,
                "sequence_status": "drafted" if draft else "new",
            }
        )
        if slug:
            slug_to_lead[slug] = new_row
        nk = _lead_match_key(p.get("first_name", ""), p.get("last_name", ""), p.get("company", ""))
        if nk:
            name_to_lead[nk] = new_row
        saved += 1
    return saved


async def heal_failed_enrollments(search_id: uuid.UUID) -> int:
    """Reset Talon-LinkedIn launch failures once Origami profiles are synced."""
    db = get_store()
    camp = await db.latest_campaign_for_search(search_id)
    if not camp:
        return 0
    now = datetime.utcnow().isoformat()
    healed = 0
    for enr in await db.list_enrollments(camp.id):
        if (enr.status or "") != "failed":
            continue
        lead = await db.select_one("leads", enr.lead_id)
        if not lead or not (lead.linkedin_url or "").strip():
            continue
        note = (enr.connection_note or getattr(lead, "linkedin_draft", None) or "").strip()
        if not note:
            continue
        await db.update(
            "campaign_enrollments",
            enr.id,
            {"status": "drafted", "last_error": None, "updated_at": now},
        )
        if (lead.sequence_status or "") == "failed":
            await db.update_lead(lead.id, sequence_status="drafted")
        healed += 1
    return healed


async def _ingest_table(
    search_id: uuid.UUID,
    prompt: str,
    tbl: Dict[str, Any],
    *,
    sid: str,
    replace: bool = True,
    merge: bool = False,
    want_founders: bool = False,
) -> int:
    table_id = tbl.get("id")
    if not table_id:
        return 0
    rows = await fetch_table_rows(table_id)
    if not rows:
        return 0
    n = await _save_leads(
        search_id, rows, prompt, replace=replace, merge=merge, want_founders=want_founders
    )
    name = tbl.get("name") or "table"
    count = tbl.get("leadCount") or n
    if want_founders and n == 0 and "compan" in name.lower():
        msg = "Building founder profiles… (company list ready, waiting for people table)"
    elif n > 0:
        msg = f"Found {n} so far — still enriching…"
    else:
        msg = f"{name}: {count} rows ({n} in Talon)"
    await _update_search(
        search_id,
        lead_count=n,
        message=msg,
        table_id=table_id,
        table_url=tbl.get("url", ""),
    )
    search_jobs[sid]["count"] = n
    return n


def _parse_dt(val: Any) -> Optional[datetime]:
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    try:
        return datetime.fromisoformat(str(val).replace("Z", "+00:00").replace("+00:00", ""))
    except ValueError:
        return None


async def sync_origami_outreach_schedule(search_id: uuid.UUID, rows: list) -> int:
    """Mirror Origami sequencer status + estimated send times onto enrollments."""
    db = get_store()
    s = await db.get_search(search_id)
    camp = await db.latest_campaign_for_search(search_id)
    if not s or not camp or not rows:
        return 0

    anchor = _parse_dt(getattr(s, "origami_launch_at", None))
    if not anchor:
        for enr in await db.list_enrollments(camp.id):
            sent = _parse_dt(enr.connection_sent_at)
            if sent and (not anchor or sent < anchor):
                anchor = sent
    if not anchor:
        scheduled_count = sum(
            1
            for r in rows
            if isinstance(r, dict)
            and (map_origami_row(r).get("origami_send_status") or "") == "scheduled"
        )
        anchor = datetime.utcnow() - timedelta(minutes=max(0, scheduled_count - 1) * 25)

    schedule_by_slug = build_outreach_schedule(rows, anchor=anchor)
    if not schedule_by_slug:
        return 0

    now = datetime.utcnow().isoformat()
    updated = 0

    for enr in await db.list_enrollments(camp.id):
        lead = await db.select_one("leads", enr.lead_id)
        if not lead:
            continue
        slug = linkedin_slug(lead.linkedin_url or "")
        meta = schedule_by_slug.get(slug)
        if not meta:
            continue
        patch: Dict[str, Any] = {
            "origami_send_status": meta.get("send_status"),
            "scheduled_at": meta.get("scheduled_at"),
            "updated_at": now,
        }
        if (meta.get("send_status") or "") == "scheduled":
            if (enr.status or "") in ("drafted", "pending", "failed"):
                patch["status"] = "connection_sent"
                patch["last_error"] = None
            if not enr.connection_sent_at:
                patch["connection_sent_at"] = meta.get("scheduled_at")
        await db.update("campaign_enrollments", enr.id, patch)
        if (meta.get("send_status") or "") == "scheduled":
            await db.update_lead(lead.id, sequence_status="connection_sent")
        updated += 1
    return updated


async def sync_origami_drafts(search_id: uuid.UUID) -> int:
    """Pull LinkedIn URLs, profiles, and draft columns from Origami into Talon leads."""
    db = get_store()
    s = await db.get_search(search_id)
    if not s or not s.origami_table_id:
        return 0
    rows = await fetch_table_rows(s.origami_table_id)
    if not rows:
        return 0
    n = await _save_leads(
        search_id,
        rows,
        s.prompt,
        replace=False,
        merge=True,
        want_founders=wants_founders(s.prompt),
    )
    await sync_origami_outreach_schedule(search_id, rows)
    await heal_failed_enrollments(search_id)
    return n


async def sync_search_progress(search_id: uuid.UUID) -> Optional[int]:
    sid = str(search_id)
    db = get_store()
    s = await db.get_search(search_id)
    if not s or not s.origami_job_id:
        return None
    prompt = s.prompt
    prior_count = s.lead_count or 0
    agent_id, run_id = parse_agent_run_ids(s.origami_job_id)
    table_hint = s.origami_table_id or ""
    founder_search = wants_founders(prompt)

    if not agent_id or not run_id:
        return None

    try:
        body, _ = await get_run(agent_id, run_id)
        run = body.get("run") or body
        msg = run_progress_message(run)
        if founder_search:
            msg = msg.replace("Finding leads", "Finding founders")
        await _update_search(search_id, message=msg)
        tbl = await resolve_live_table(
            run,
            workspace_id=run.get("workspaceId"),
            table_id_hint=table_hint or None,
            want_founders=founder_search,
        )
        if not tbl or not (tbl.get("leadCount") or 0):
            if founder_search:
                await _update_search(search_id, message="Building founder profiles…")
            return prior_count
        return await _ingest_table(
            search_id,
            prompt,
            tbl,
            sid=sid,
            replace=True,
            merge=False,
            want_founders=founder_search,
        )
    except Exception as e:
        print(f"[search_runner] sync {search_id}: {e}", flush=True)
        return None


async def run_search(search_id: uuid.UUID, prompt: str, *, resume: bool = False) -> None:
    sid = str(search_id)
    if sid not in _run_locks:
        _run_locks[sid] = asyncio.Lock()
    lock = _run_locks[sid]
    if lock.locked():
        print(f"[search_runner] {sid} already running — skip duplicate dispatch", flush=True)
        return

    async with lock:
        await _run_search_impl(search_id, prompt, resume=resume)


async def _run_search_impl(search_id: uuid.UUID, prompt: str, *, resume: bool = False) -> None:
    sid = str(search_id)
    search_jobs[sid] = {"status": "running", "step": "Finding leads...", "count": 0}
    db = get_store()

    if not os.getenv("ORIGAMI_API_KEY"):
        await _update_search(search_id, status="failed", message="ORIGAMI_API_KEY not configured")
        search_jobs[sid] = {"status": "failed", "error": "Missing ORIGAMI_API_KEY"}
        return

    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    table_id: Optional[str] = None
    founder_search = wants_founders(prompt)

    async def on_tick(run: Dict[str, Any]):
        nonlocal table_id
        msg = run_progress_message(run)
        if founder_search:
            msg = msg.replace("Finding leads", "Finding founders")
        await _update_search(search_id, message=msg)
        try:
            tbl = await resolve_live_table(
                run,
                workspace_id=run.get("workspaceId"),
                table_id_hint=table_id,
                want_founders=founder_search,
            )
            if tbl and tbl.get("id"):
                table_id = tbl["id"]
                await _ingest_table(
                    search_id,
                    prompt,
                    tbl,
                    sid=sid,
                    replace=False,
                    merge=True,
                    want_founders=founder_search,
                )
        except Exception as e:
            print(f"[search_runner] partial: {e}", flush=True)

    try:
        await release_research_capacity()
        await _update_search(search_id, status="running", message="Finding leads...")

        terminal: Optional[Dict[str, Any]] = None
        existing_job = ""
        if resume:
            s = await db.get_search(search_id)
            existing_job = (s.origami_job_id or "") if s else ""

        if resume and existing_job:
            agent_id, run_id = parse_agent_run_ids(existing_job)
            if agent_id and run_id:
                try:
                    body, _ = await get_run(agent_id, run_id)
                    terminal = body.get("run") or body
                    if terminal.get("status") == "running":
                        terminal = await poll_run_until_done(
                            agent_id, run_id, on_tick=on_tick, max_wait_sec=900
                        )
                    elif terminal.get("status") == "needs_input":
                        await _update_search(search_id, message="Answering Origami questions...")
                        answer = build_auto_answer(terminal, prompt)
                        cont = await continue_agent_run(agent_id, answer)
                        run_next = cont.get("run") or cont
                        run_id = str(run_next.get("id") or "")
                        await _update_search(search_id, origami_job_id=f"{agent_id}:{run_id}")
                        terminal = await poll_run_until_done(
                            agent_id, run_id, on_tick=on_tick, max_wait_sec=900
                        )
                except RuntimeError as e:
                    if _is_stale_agent_error(e):
                        print(f"[search_runner] stale agent for {sid}, starting fresh", flush=True)
                        await _update_search(search_id, origami_job_id="")
                        terminal = None
                    else:
                        raise

        s0 = await db.get_search(search_id)
        msg_tpl = (s0.linkedin_message_template or "").strip() if s0 else ""

        if terminal is None:
            admission = await create_agent_run(build_search_prompt(prompt, message_template=msg_tpl))
            agent = admission.get("agent") or {}
            run0 = admission.get("run") or {}
            agent_id = str(agent.get("id") or admission.get("agentId") or "")
            run_id = str(run0.get("id") or admission.get("runId") or "")
            if not agent_id or not run_id:
                raise RuntimeError("Origami did not return agent/run ids")

            await _update_search(
                search_id,
                origami_job_id=f"{agent_id}:{run_id}",
                message="Finding leads...",
            )
            search_jobs[sid]["step"] = "Finding leads..."

            try:
                terminal = await poll_run_until_done(
                    agent_id, run_id, on_tick=on_tick, max_wait_sec=900
                )
            except RuntimeError as e:
                if _is_stale_agent_error(e):
                    raise RuntimeError("Research session expired — click Try again.") from e
                raise

        for _ in range(3):
            if terminal.get("status") != "needs_input":
                break
            await _update_search(search_id, message="Answering Origami questions...")
            answer = build_auto_answer(terminal, prompt)
            cont = await continue_agent_run(agent_id, answer)
            run_next = cont.get("run") or cont
            run_id = str(run_next.get("id") or "")
            if not run_id:
                break
            await _update_search(search_id, origami_job_id=f"{agent_id}:{run_id}")
            terminal = await poll_run_until_done(agent_id, run_id, on_tick=on_tick, max_wait_sec=900)

        if terminal.get("status") == "needs_input":
            qs = parse_pending_questions(terminal)
            preview = qs[0].get("question", "")[:120] if qs else "Open Origami to answer"
            await _update_search(
                search_id,
                status="needs_input",
                message=f"Still needs input: {preview}",
            )
            search_jobs[sid] = {"status": "needs_input", "step": "Needs input", "questions": qs}
            return

        if terminal.get("status") in ("errored", "timed_out", "cancelled"):
            raise RuntimeError(f"Origami run {terminal.get('status')}")

        tbl = extract_primary_table(terminal)
        if not tbl or not tbl.get("id"):
            import httpx
            from services.origami_service import ORIGAMI_BASE, _headers

            materialize = (
                "Materialize a PEOPLE table of founders with first name, last name, title, company, "
                "LinkedIn /in/ URLs, LinkedIn Message Draft (≤300 chars each), and Follow-up Message columns."
                if founder_search
                else "Materialize the table with all leads plus LinkedIn Message Draft and Follow-up Message columns."
            )
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{ORIGAMI_BASE}/api/v2/agents/{agent_id}/runs",
                    headers=_headers(),
                    json={"prompt": materialize},
                )
                if resp.status_code in (200, 202):
                    run2 = resp.json().get("run") or resp.json()
                    rid2 = run2.get("id")
                    if rid2:
                        terminal = await poll_run_until_done(agent_id, str(rid2), on_tick=on_tick)
                        tbl = extract_primary_table(terminal)

        live = await resolve_live_table(
            terminal,
            workspace_id=terminal.get("workspaceId"),
            table_id_hint=table_id,
            want_founders=founder_search,
        )
        if live and live.get("id"):
            table_id = live["id"]
            table_url = live.get("url", "")
        elif tbl and tbl.get("id"):
            table_id = tbl["id"]
            table_url = tbl.get("url", "")
        else:
            raise RuntimeError(
                "No founder profiles returned from Origami" if founder_search else "No table returned from Origami"
            )
        await _update_search(search_id, message="Enriching...", table_id=table_id, table_url=table_url)

        cells_running = (tbl.get("cells") or {}).get("running", 0)
        if cells_running > 0:
            n = 0
            for _ in range(4):
                await asyncio.sleep(1.5)
                partial = await fetch_table_rows(table_id)
                if partial:
                    n = await _save_leads(
                        search_id,
                        partial,
                        prompt,
                        replace=False,
                        merge=True,
                        want_founders=founder_search,
                    )
                    await _update_search(search_id, lead_count=n, message=f"Enriching… ({n} founders)")
                    search_jobs[sid]["count"] = n
                if n and n >= (tbl.get("leadCount") or 0):
                    break

        await _update_search(search_id, message="Drafting LinkedIn messages in Origami...")
        rows = await fetch_table_rows(table_id)
        if not rows:
            raise RuntimeError("Origami table empty")

        if count_rows_with_drafts(rows) < max(1, int(len(rows) * 0.5)):
            rows = await ensure_linkedin_drafts(
                agent_id,
                table_id,
                template=msg_tpl,
                on_tick=on_tick,
            )

        await _update_search(search_id, message="Scoring leads...")
        saved = await _save_leads(
            search_id, rows, prompt, replace=True, merge=False, want_founders=founder_search
        )
        srow = await db.get_search(search_id)
        tpl = (srow.linkedin_message_template or "").strip() if srow else ""
        kit = build_outreach_kit(prompt, linkedin_template=tpl)
        lead_rows = await db.list_leads_by_search(search_id)
        drafted = sum(1 for l in lead_rows if (getattr(l, "linkedin_draft", None) or "").strip())
        if drafted == saved and saved:
            done_msg = (
                f"{saved} founders ready — LinkedIn notes drafted in Origami."
                if founder_search
                else f"{saved} leads ready — LinkedIn notes drafted in Origami."
            )
        elif drafted > 0:
            done_msg = f"{saved} leads ready — {drafted} LinkedIn notes drafted in Origami."
        else:
            done_msg = (
                f"{saved} founders ready — open Origami to finish drafting messages."
                if founder_search
                else f"{saved} leads ready — open Origami to finish drafting messages."
            )
        await _update_search(
            search_id,
            status="completed",
            message=done_msg,
            lead_count=saved,
            table_id=table_id,
            table_url=table_url,
        )
        search_jobs[sid] = {
            "status": "completed",
            "count": saved,
            "step": done_msg,
            "outreach": kit,
        }

    except Exception as e:
        print(f"[search_runner] {search_id}: {e}", flush=True)
        err = user_facing_message(str(e)[:200])
        lead_rows = await db.list_leads_by_search(search_id)
        saved = len(lead_rows)
        if saved > 0:
            srow = await db.get_search(search_id)
            tpl = (srow.linkedin_message_template or "").strip() if srow else ""
            kit = build_outreach_kit(prompt, linkedin_template=tpl)
            drafted = sum(1 for l in lead_rows if (getattr(l, "linkedin_draft", None) or "").strip())
            if drafted == saved:
                done_msg = f"{saved} leads ready — LinkedIn notes drafted in Origami."
            elif drafted > 0:
                done_msg = f"{saved} leads ready — {drafted} LinkedIn notes drafted in Origami."
            else:
                done_msg = f"{saved} leads ready — open Origami to finish drafting messages."
            await _update_search(
                search_id,
                status="completed",
                message=done_msg,
                lead_count=saved,
            )
            search_jobs[sid] = {
                "status": "completed",
                "count": saved,
                "step": done_msg,
                "outreach": kit,
            }
        else:
            await _update_search(search_id, status="failed", message=err)
            search_jobs[sid] = {"status": "failed", "error": err}


async def run_origami_launch_job(job_id: str, search_id: uuid.UUID) -> None:
    """Launch LinkedIn sequences through Origami's sequencer (not Talon LinkedIn API)."""
    from services.campaign_runner import campaign_jobs

    job = campaign_jobs[job_id]
    job["status"] = "running"
    job["type"] = "origami_launch"
    job["step"] = "Launching sequences in Origami…"

    db = get_store()
    s = await db.get_search(search_id)
    if not s or not s.origami_job_id or not s.origami_table_id:
        job["status"] = "failed"
        job["error"] = "No Origami workspace linked to this search"
        return

    agent_id, _ = parse_agent_run_ids(s.origami_job_id)
    if not agent_id:
        job["status"] = "failed"
        job["error"] = "Origami agent not found — re-run the search"
        return

    camp = await db.latest_campaign_for_search(search_id)
    enrollments = await db.list_enrollments(camp.id) if camp else []
    ready = [
        e
        for e in enrollments
        if (e.status or "") in ("drafted", "pending")
        and (e.connection_note or "").strip()
    ]
    job["total"] = len(ready) or len(enrollments)
    job["done"] = 0
    job["sent"] = 0
    job["failed"] = 0

    def on_tick(run: Dict[str, Any]) -> None:
        job["step"] = run_progress_message(run).replace("Talon researching", "Origami launching")

    try:
        if s.origami_table_id:
            await sync_origami_drafts(search_id)
            s = await db.get_search(search_id) or s

        result = await launch_origami_sequences(
            agent_id,
            s.origami_table_id,
            count=job["total"],
            on_tick=on_tick,
        )
        launched = result.get("launched_count") or job["total"]
        summary = (result.get("text") or "").strip()
        now = datetime.utcnow().isoformat()

        if camp:
            sent = 0
            cap = launched if launched is not None else len(ready)
            for enr in ready[:cap]:
                await db.update(
                    "campaign_enrollments",
                    enr.id,
                    {
                        "status": "connection_sent",
                        "connection_sent_at": now,
                        "updated_at": now,
                    },
                )
                lead = await db.select_one("leads", enr.lead_id)
                if lead:
                    await db.update_lead(lead.id, sequence_status="connection_sent")
                sent += 1
            job["sent"] = sent
            job["done"] = job["total"]

        job["status"] = "completed"
        job["step"] = summary[:200] if summary else f"Launched {job['sent']} sequences in Origami"
        job["origami_summary"] = summary
        if result.get("table_url"):
            job["origami_table_url"] = result["table_url"]
        await db.update_search(
            search_id,
            status_message=job["step"],
            origami_launch_at=now,
        )
        if s.origami_table_id:
            rows = await fetch_table_rows(s.origami_table_id)
            if rows:
                await sync_origami_outreach_schedule(search_id, rows)
    except Exception as e:
        print(f"[search_runner] origami launch {search_id}: {e}", flush=True)
        job["status"] = "failed"
        job["error"] = user_facing_message(str(e)[:300])
        job["step"] = job["error"]
