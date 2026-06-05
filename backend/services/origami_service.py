"""Origami API v2 — agent runs + v1 table reads. See .cursor/skills/origami-api/SKILL.md"""
import asyncio
import os
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

ORIGAMI_API_KEY = os.getenv("ORIGAMI_API_KEY", "")
ORIGAMI_BASE = os.getenv("ORIGAMI_BASE_URL", "https://origami.chat")
MAX_ROWS = int(os.getenv("MAX_LEADS_PER_SEARCH", "25"))
POLL_DEFAULT_SEC = 1.5


def user_facing_message(msg: str) -> str:
    """Strip vendor names — errors/status shown in Talon UI."""
    if not msg:
        return msg
    out = msg
    for old, new in (
        ("Origami concurrent agent limit (1 on your plan). Wait for the current run to finish, then retry.", "Research queue was busy — retrying now."),
        ("Origami concurrent agent limit — wait and retry", "Research queue was busy — try again."),
        ("Origami agent busy — try again in a minute", "Research is busy — try again in a moment."),
        ("Origami agent busy — wait for the current run to finish", "Research is busy — wait a moment and retry."),
        ("Origami working…", "Talon researching…"),
        ("Answering Origami questions…", "Answering research questions…"),
        ("Origami run timed out", "Research timed out"),
        ("Origami table empty", "No leads returned"),
        ("No table returned from Origami", "No lead list returned"),
        ("No founder profiles returned from Origami", "No founder profiles returned"),
    ):
        out = out.replace(old, new)
    if "Origami" in out:
        out = out.replace("Origami", "Talon")
    if "origami" in out:
        out = out.replace("origami", "Talon")
    if "CONCURRENT_LIMIT" in out or "concurrent agent limit" in out.lower():
        return "Research queue was busy — click Try again."
    if "create agent failed (429)" in out.lower() or "research start failed (429)" in out.lower():
        return "Research queue was busy — click Try again."
    if "AGENT_NOT_FOUND" in out or "agent not found" in out.lower():
        return "Research session expired — click Try again."
    if "RATE_LIMITED" in out or "rate limit" in out.lower() or "poll failed (429)" in out.lower():
        return "Research is temporarily busy — wait a moment, then click Try again."
    return out


def _headers() -> Dict[str, str]:
    if not ORIGAMI_API_KEY:
        raise RuntimeError("ORIGAMI_API_KEY not set")
    return {
        "Authorization": f"Bearer {ORIGAMI_API_KEY}",
        "Content-Type": "application/json",
    }


def _normalize_row_keys(row: Dict[str, Any]) -> Dict[str, Any]:
    """Origami v1 rows use slugs like first-name, linkedin-url, company-name."""
    out: Dict[str, Any] = {}
    for k, v in row.items():
        if k == "id" or v is None:
            continue
        norm = str(k).lower().replace("-", " ").replace("_", " ")
        out[norm] = v
    return out


def _pick(row: Dict[str, Any], *keys: str) -> str:
    """Case-insensitive column lookup for Origami table rows."""
    lower = _normalize_row_keys(row)
    for key in keys:
        v = lower.get(key.lower().replace("-", " ").replace("_", " "))
        if v is not None and str(v).strip() and not isinstance(v, (dict, list)):
            return str(v).strip()
    return ""


def normalize_linkedin_url(val: Any) -> str:
    """Turn Origami handles (/in/slug or bare slug) into a canonical profile URL."""
    if not val:
        return ""
    if isinstance(val, dict):
        for k in ("url", "linkedin", "linkedin_url", "linkedinUrl", "publicProfileUrl", "profileUrl"):
            if val.get(k):
                return normalize_linkedin_url(val[k])
        if val.get("publicIdentifier"):
            return f"https://www.linkedin.com/in/{str(val['publicIdentifier']).strip('/')}"
        if val.get("handle"):
            return normalize_linkedin_url(val["handle"])
        return ""
    s = str(val).strip()
    if not s or s.lower() in ("—", "-", "n/a", "none"):
        return ""
    if s.startswith("http"):
        s = s.split("?")[0].rstrip("/")
        if "/in/" in s:
            slug = s.split("/in/")[-1].strip("/")
            if slug:
                return f"https://www.linkedin.com/in/{slug}"
        if "/companies/" in s:
            return ""
        return s
    if "/in/" in s:
        slug = s.split("/in/")[-1].strip("/").split("?")[0]
        return f"https://www.linkedin.com/in/{slug}" if slug else ""
    handle = s.lstrip("@").strip("/")
    if handle and " " not in handle and "." not in handle.split("/")[0]:
        return f"https://www.linkedin.com/in/{handle}"
    return ""


def linkedin_slug(url: str) -> str:
    """Normalized public id for deduping (garrettkurtt, etc.)."""
    u = normalize_linkedin_url(url)
    if not u or "/in/" not in u:
        return ""
    return u.split("/in/")[-1].strip("/").lower()


def _linkedin_from_row(row: Dict[str, Any]) -> str:
    """Best-effort LinkedIn URL from any Origami column shape."""
    for key in row:
        kl = str(key).lower()
        if "linkedin" not in kl or "outreach" in kl or "message" in kl or "draft" in kl:
            continue
        v = row.get(key)
        if isinstance(v, dict):
            url = normalize_linkedin_url(v)
            if url:
                return url
        elif v and not isinstance(v, (list,)):
            url = normalize_linkedin_url(v)
            if url:
                return url
    return ""


def _name_from_linkedin(url: str) -> tuple[str, str]:
    import re

    m = re.search(r"/in/([^/?#]+)", url)
    if not m:
        return "", ""
    slug = m.group(1).strip("/")
    if "%" in slug:
        from urllib.parse import unquote

        slug = unquote(slug)
    parts = [p for p in slug.replace("_", "-").split("-") if p]
    if len(parts) >= 2:
        return parts[0].title(), " ".join(p.title() for p in parts[1:])
    if parts:
        return parts[0].title(), ""
    return "", ""


def extract_outreach_meta(row: Dict[str, Any]) -> Dict[str, Any]:
    """Parse Origami linkedin-outreach sequencer column."""
    lo = row.get("linkedin-outreach") or row.get("linkedin_outreach") or {}
    if not isinstance(lo, dict):
        return {}
    scheduled_raw = (
        lo.get("scheduledAt")
        or lo.get("scheduled_at")
        or lo.get("sendAt")
        or lo.get("send_at")
        or lo.get("nextSendAt")
        or lo.get("next_send_at")
    )
    return {
        "send_status": str(lo.get("sendStatus") or "").strip().lower(),
        "message_id": str(lo.get("messageId") or "").strip(),
        "scheduled_at": scheduled_raw,
        "send_status_reason": lo.get("sendStatusReason"),
    }


def _parse_schedule_dt(val: Any) -> Optional[datetime]:
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    s = str(val).strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00").replace("+00:00", ""))
    except ValueError:
        return None


def build_outreach_schedule(
    rows: List[Dict[str, Any]],
    *,
    anchor: Optional[datetime] = None,
    interval_minutes: int = 25,
) -> Dict[str, Dict[str, Any]]:
    """
    Map linkedin slug -> outreach meta with estimated scheduled_at.
    Origami's public table API exposes sendStatus but not always the exact time;
    we estimate queue spacing to match the sequencer UI.
    """
    anchor = anchor or datetime.utcnow()
    scheduled: List[tuple[str, Dict[str, Any]]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        mapped = map_origami_row(row)
        slug = linkedin_slug(mapped.get("linkedin_url") or "")
        if not slug:
            continue
        meta = extract_outreach_meta(row)
        st = meta.get("send_status") or ""
        if st not in ("scheduled", "queued", "pending"):
            continue
        explicit = _parse_schedule_dt(meta.get("scheduled_at"))
        scheduled.append((slug, {**meta, "scheduled_at": explicit}))

    out: Dict[str, Dict[str, Any]] = {}
    queue_idx = 0
    for slug, meta in scheduled:
        explicit = meta.get("scheduled_at")
        if isinstance(explicit, datetime):
            est = explicit
        else:
            est = anchor + timedelta(minutes=queue_idx * interval_minutes)
            queue_idx += 1
        out[slug] = {**meta, "scheduled_at": est.isoformat()}
    return out


def map_origami_row(row: Dict[str, Any]) -> Dict[str, Any]:
    first = _pick(row, "first name", "first_name", "firstname")
    last = _pick(row, "last name", "last_name", "lastname")
    if not first and not last:
        full = _pick(row, "name", "full name", "contact name", "founder name")
        parts = full.split(None, 1) if full else []
        first = parts[0] if parts else ""
        last = parts[1] if len(parts) > 1 else ""

    linkedin = normalize_linkedin_url(
        _pick(row, "linkedin url", "linkedin_url", "linkedin", "linkedin profile", "linkedin handle")
        or _linkedin_from_row(row)
    )
    raw = row.get("raw-data") or row.get("raw_data")
    linkedin_profile_id = ""
    if isinstance(raw, dict):
        link = raw.get("link") or {}
        if not linkedin and isinstance(link, dict):
            linkedin = normalize_linkedin_url(link.get("linkedin") or link.get("url") or "")
        prof = raw.get("profile") or {}
        if isinstance(prof, dict):
            if not linkedin:
                linkedin = normalize_linkedin_url(
                    prof.get("linkedinUrl")
                    or prof.get("linkedin_url")
                    or prof.get("publicProfileUrl")
                    or prof.get("publicIdentifier")
                    or prof.get("vanityName")
                )
            linkedin_profile_id = str(
                prof.get("entityUrn", "").split(":")[-1]
                or prof.get("profileId")
                or prof.get("objectUrn", "").split(":")[-1]
                or ""
            ).strip()
            if not first:
                first = str(prof.get("firstName") or prof.get("first_name") or "").strip()
            if not last:
                last = str(prof.get("lastName") or prof.get("last_name") or "").strip()
        comp = raw.get("company") or {}
        if isinstance(comp, dict):
            summ = comp.get("summary") or {}
            if isinstance(summ, dict) and not _pick(row, "company name", "company"):
                pass

    if not linkedin:
        for k, v in row.items():
            if v and "linkedin" in str(k).lower() and "outreach" not in str(k).lower():
                linkedin = normalize_linkedin_url(v)
                if linkedin:
                    break
    linkedin = normalize_linkedin_url(linkedin)

    if not first and not last and linkedin:
        first, last = _name_from_linkedin(linkedin)

    company = _pick(row, "company name", "company", "organization")
    yc = _pick(row, "yc batch", "batch")
    if yc and company and yc.upper() not in company.upper():
        company = f"{company} ({yc})"
    elif yc and not company:
        company = yc

    title = _pick(row, "title", "job title", "role", "position")
    if not title and isinstance(raw, dict):
        pgs = raw.get("position_groups") or []
        if isinstance(pgs, list) and pgs:
            pg0 = pgs[0] if isinstance(pgs[0], dict) else {}
            positions = pg0.get("positions") or []
            if positions and isinstance(positions[0], dict):
                title = str(positions[0].get("title") or "").strip()

    import re

    score_raw = _pick(
        row,
        "score",
        "icp score",
        "fit score",
        "match score",
        "quality score",
        "rating",
        "relevance score",
    )
    origami_score: Optional[int] = None
    if score_raw:
        m = re.search(r"(\d+(?:\.\d+)?)", score_raw)
        if m:
            origami_score = max(1, min(10, int(round(float(m.group(1))))))

    outreach_meta = extract_outreach_meta(row)
    outreach_col = row.get("linkedin-outreach") or row.get("linkedin_outreach")
    if isinstance(outreach_col, dict):
        seq_note = str(outreach_col.get("connect_note") or outreach_col.get("connection_note") or "").strip()
        seq_follow = str(outreach_col.get("follow_up_body") or outreach_col.get("follow_up_message") or "").strip()
    else:
        seq_note = seq_follow = ""

    linkedin_draft = _pick(
        row,
        "linkedin message draft",
        "linkedin message",
        "connection message",
        "connection note",
        "connection request",
        "step 1 message",
        "step 1",
        "outreach message",
        "message draft",
        "connect note",
    ) or seq_note
    follow_up_draft = _pick(
        row,
        "follow-up message",
        "follow up message",
        "followup message",
        "step 2 message",
        "step 2",
        "dm message",
        "linkedin dm",
        "follow up body",
    ) or seq_follow

    return {
        "first_name": first,
        "last_name": last,
        "name": f"{first} {last}".strip() or _pick(row, "name"),
        "title": title,
        "company": company,
        "email": _pick(row, "email", "work email", "verified email", "email address"),
        "linkedin_url": linkedin,
        "linkedin_profile_id": linkedin_profile_id or None,
        "icp_score": origami_score if origami_score is not None else 7,
        "origami_score": origami_score,
        "score_reason": "Origami score" if origami_score is not None else "Origami agent",
        "linkedin_draft": linkedin_draft,
        "follow_up_draft": follow_up_draft,
        "origami_send_status": outreach_meta.get("send_status") or None,
        "origami_message_id": outreach_meta.get("message_id") or None,
        "source_url": linkedin or _pick(row, "website", "company website", "company domain"),
    }


def parse_lead_count_from_prompt(user_prompt: str) -> int:
    import re

    m = re.search(r"\b(\d{1,3})\b", user_prompt)
    if m:
        return max(5, min(MAX_ROWS, int(m.group(1))))
    return min(30, MAX_ROWS)


def wants_founders(user_prompt: str) -> bool:
    pl = user_prompt.lower()
    return any(w in pl for w in ("founder", "founders", "co-founder", "cofounder"))


def _extra_fields_from_query(user_prompt: str) -> str:
    pl = user_prompt.lower()
    extras: list[str] = []
    if "yc" in pl or "y combinator" in pl:
        extras.append("YC Batch")
    if "series" in pl:
        extras.append("Funding Stage")
    if wants_founders(pl):
        extras.append("Founder Type")
    return ", ".join(extras)


def build_search_prompt(user_prompt: str, *, message_template: str = "") -> str:
    """B2B lead generation brief sent to Origami — includes mandatory outreach draft columns."""
    n = parse_lead_count_from_prompt(user_prompt)
    q = user_prompt.strip()
    extra = _extra_fields_from_query(q)
    extra_cols = f", {extra}" if extra else ""
    style = ""
    if message_template.strip():
        style = (
            "\n\nUse this LinkedIn connection message style for every row "
            "(personalize names/companies per person, keep each draft ≤300 characters):\n"
            f"{message_template.strip()}"
        )
    return (
        f"Find {n} individual founders (people, not companies) matching: {q}\n\n"
        "REQUIREMENTS:\n"
        "1. Ask clarifying questions if the query is ambiguous before proceeding.\n"
        f"2. Build a PEOPLE table with columns: First Name, Last Name, Title, Company Name, "
        f"LinkedIn URL (/in/){extra_cols}, LinkedIn Message Draft, Follow-up Message\n"
        "3. Do NOT stop at a companies-only table — every row must be a person with a /in/ LinkedIn URL.\n"
        "4. Populate \"LinkedIn Message Draft\" for EVERY person: a personalized LinkedIn connection "
        "request (max 300 characters) referencing their name, company, and role. Ready to copy-paste.\n"
        "5. Populate \"Follow-up Message\" for EVERY person: a short DM sent after they accept, "
        "personalized to their company.\n"
        "6. Qualify leads as you normally would (fit score, verification, etc.).\n"
        "7. Run the draft columns for all rows before finishing."
        f"{style}"
    )


def build_draft_messages_prompt(*, template: str = "", count: int = 20) -> str:
    """Follow-up Origami prompt when the people table exists but drafts are missing."""
    style = ""
    if template.strip():
        style = (
            "Use this connection message style (replace names/companies per person, ≤300 chars each):\n"
            f"{template.strip()}\n\n"
        )
    else:
        style = (
            "Each LinkedIn Message Draft should greet by first name, briefly say who you are, "
            "why it fits their company/role, and stay under 300 characters without cutting off mid-sentence.\n\n"
        )
    return (
        "The people table is ready. Add outreach drafts visible in the table:\n"
        f"1. Add two plain text enrichment columns named exactly \"LinkedIn Message Draft\" and "
        f"\"Follow-up Message\" (not only a sequencer — these must be readable as table columns).\n"
        f"2. Populate \"LinkedIn Message Draft\" for all {count} qualified people.\n"
        "3. Populate \"Follow-up Message\" for all people (short DM after they accept the connection).\n"
        f"{style}"
        "If an outreach/sequencer column already has connect_note values, copy them into "
        "\"LinkedIn Message Draft\" and follow_up_body into \"Follow-up Message\". "
        "Run all cells now."
    )


def row_has_linkedin_draft(row: Dict[str, Any]) -> bool:
    return bool((map_origami_row(row).get("linkedin_draft") or "").strip())


def count_rows_with_drafts(rows: List[Dict[str, Any]]) -> int:
    return sum(1 for r in rows if row_has_linkedin_draft(r if isinstance(r, dict) else {}))


async def ensure_linkedin_drafts(
    agent_id: str,
    table_id: str,
    *,
    template: str = "",
    on_tick: Optional[Callable[[Dict[str, Any]], Any]] = None,
    max_wait_sec: int = 600,
) -> List[Dict[str, Any]]:
    """Ask Origami to populate draft columns; return refreshed table rows."""
    rows = await fetch_table_rows(table_id)
    if rows and count_rows_with_drafts(rows) >= max(1, int(len(rows) * 0.8)):
        return rows

    cont = await continue_agent_run(
        agent_id, build_draft_messages_prompt(template=template, count=len(rows) or 20)
    )
    run = cont.get("run") or cont
    run_id = str(run.get("id") or "")
    if not run_id:
        return rows

    await poll_run_until_done(agent_id, run_id, on_tick=on_tick, max_wait_sec=max_wait_sec)

    best = rows
    for _ in range(8):
        await asyncio.sleep(2)
        fresh = await fetch_table_rows(table_id)
        if fresh:
            best = fresh
        if fresh and count_rows_with_drafts(fresh) >= max(1, int(len(fresh) * 0.5)):
            break
    return best


def build_launch_sequences_prompt(*, count: int = 0, column_name: str = "") -> str:
    """Ask Origami to launch all sequencer sequences (same as Launch all in Origami UI)."""
    col = f' in "{column_name}"' if column_name else ""
    qty = f"all {count} " if count else "all "
    return (
        f"Launch {qty}LinkedIn outreach sequences{col} for every qualified row in this table. "
        "Start sending all connection requests now — same as clicking Launch all in the Origami sequencer."
    )


def _launch_confirm_answer(terminal: Dict[str, Any]) -> str:
    for q in parse_pending_questions(terminal):
        for ans in q.get("suggestedAnswers") or []:
            lower = ans.lower()
            if "yes" in lower and "launch" in lower:
                return ans
    return "Yes, launch all now"


def parse_launched_count(text: str) -> Optional[int]:
    import re

    if not text:
        return None
    m = re.search(r"(\d+)\s+of\s+(\d+)\s+connection", text, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s+sequences?\s+launched", text, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"launch(?:ed)?\s+(\d+)", text, re.I)
    if m:
        return int(m.group(1))
    return None


async def find_outreach_column_name(table_id: str) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{ORIGAMI_BASE}/api/v1/tables", headers=_headers())
        if resp.status_code != 200:
            return ""
        for tbl in resp.json().get("tables") or []:
            if tbl.get("id") != table_id:
                continue
            for col in tbl.get("columns") or []:
                slug = (col.get("slug") or "").lower()
                name = (col.get("name") or "").lower()
                if "outreach" in slug or "outreach" in name or slug == "linkedin-outreach":
                    return col.get("name") or ""
    return ""


async def launch_origami_sequences(
    agent_id: str,
    table_id: str,
    *,
    count: int = 0,
    outreach_column: str = "",
    on_tick: Optional[Callable[[Dict[str, Any]], Any]] = None,
    max_wait_sec: int = 600,
) -> Dict[str, Any]:
    """Trigger Origami sequencer Launch all; auto-confirms needs_input."""
    col_name = outreach_column or await find_outreach_column_name(table_id)
    focus = [table_id]
    cont = await continue_agent_run(
        agent_id,
        build_launch_sequences_prompt(count=count, column_name=col_name),
        focus_table_ids=focus,
    )
    run = cont.get("run") or cont
    run_id = str(run.get("id") or "")
    if not run_id:
        raise RuntimeError("Origami did not return a run id for launch")

    terminal = await poll_run_until_done(agent_id, run_id, on_tick=on_tick, max_wait_sec=max_wait_sec)

    for _ in range(4):
        if terminal.get("status") != "needs_input":
            break
        answer = _launch_confirm_answer(terminal)
        cont = await continue_agent_run(agent_id, answer, focus_table_ids=focus)
        run = cont.get("run") or cont
        run_id = str(run.get("id") or "")
        if not run_id:
            break
        terminal = await poll_run_until_done(agent_id, run_id, on_tick=on_tick, max_wait_sec=max_wait_sec)

    if terminal.get("status") in ("errored", "timed_out", "cancelled"):
        raise RuntimeError(f"Origami launch {terminal.get('status')}")

    response = terminal.get("response") or {}
    text = response.get("text") or ""
    launched = parse_launched_count(text)
    table_url = ""
    for tbl in response.get("tables") or []:
        if tbl.get("url"):
            table_url = tbl["url"]
            break
    return {
        "status": terminal.get("status"),
        "text": text,
        "launched_count": launched,
        "table_url": table_url,
    }


def run_progress_message(run: Dict[str, Any]) -> str:
    steps = run.get("steps") or {}
    done, mx = steps.get("completed"), steps.get("max")
    if isinstance(done, int) and isinstance(mx, int) and mx > 0:
        return f"Talon researching… step {done}/{mx}"
    st = run.get("status", "running")
    if st == "needs_input":
        return "Answering research questions…"
    return "Finding leads…"


def build_auto_answer(run: Dict[str, Any], user_prompt: str) -> str:
    """Pick suggested answers for needs_input so automated runs can continue."""
    todo = run.get("todo") or {}
    questions = todo.get("pendingQuestions") or []
    prompt_l = user_prompt.lower()
    parts: List[str] = []
    for q in questions:
        suggested = q.get("suggestedAnswers") or []
        qtext = (q.get("question") or "").lower()
        if "batch" in qtext or "yc" in qtext:
            if any(x in prompt_l for x in ("w26", "w25", "w24", "w23")):
                for token in ("w26", "w25", "w24", "w23"):
                    if token in prompt_l:
                        parts.append(f"Focus on YC {token.upper()} batch specifically.")
                        break
            elif suggested:
                parts.append(suggested[0])
        elif "industry" in qtext or "vertical" in qtext or "focus" in qtext:
            pick = next(
                (s for s in suggested if "b2b" in s.lower() or "saas" in s.lower()),
                suggested[0] if suggested else "All industries",
            )
            if "saas" in prompt_l or "b2b" in prompt_l:
                parts.append(pick)
            elif suggested:
                parts.append(suggested[0])
        elif "email" in qtext:
            pick = next((s for s in suggested if "nice" in s.lower()), suggested[-1] if suggested else "")
            parts.append(pick or "Include all founders; emails nice to have")
        elif suggested:
            parts.append(suggested[0])
    if not parts:
        parts.append("Use your best judgment and proceed with the search.")
    return ". ".join(parts) + f" Continue the list for: {user_prompt.strip()}"


def parse_pending_questions(run: Dict[str, Any]) -> List[Dict[str, Any]]:
    return (run.get("todo") or {}).get("pendingQuestions") or []


def parse_agent_run_ids(job_id: str) -> Tuple[str, str]:
    if ":" in job_id:
        a, r = job_id.split(":", 1)
        return a.strip(), r.strip()
    return "", ""


async def list_agents() -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{ORIGAMI_BASE}/api/v2/agents", headers=_headers())
        if resp.status_code != 200:
            return []
        return resp.json().get("agents") or []


async def cancel_agent(agent_id: str) -> bool:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{ORIGAMI_BASE}/api/v2/agents/{agent_id}/cancel",
            headers=_headers(),
            json={},
        )
        return resp.status_code in (200, 202)


async def delete_agent(agent_id: str) -> bool:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.delete(
            f"{ORIGAMI_BASE}/api/v2/agents/{agent_id}",
            headers=_headers(),
        )
        return resp.status_code in (200, 202)


async def _protected_agent_ids() -> set[str]:
    """Agent ids tied to in-flight Talon searches — never delete these."""
    protected: set[str] = set()
    try:
        from store import get_store

        rows = await get_store().select_many("searches", filters={"status": "running"}, limit=20)
        for row in rows:
            aid, _ = parse_agent_run_ids(getattr(row, "origami_job_id", "") or "")
            if aid:
                protected.add(aid)
    except Exception as e:
        print(f"[talon-research] protect list: {e}", flush=True)
    return protected


async def release_research_capacity() -> int:
    """Cancel orphaned API-owned runs so new searches can start."""
    protected = await _protected_agent_ids()
    freed = 0
    for agent in await list_agents():
        if not agent.get("apiKeyOwned"):
            continue
        last = agent.get("lastRun") or {}
        if last.get("status") != "running":
            continue
        aid = str(agent.get("id") or "")
        if not aid or aid in protected:
            continue
        try:
            await cancel_agent(aid)
            await delete_agent(aid)
            freed += 1
            print(f"[talon-research] released stale agent {aid[:8]}…", flush=True)
        except Exception as e:
            print(f"[talon-research] release {aid}: {e}", flush=True)
    return freed


async def _create_agent_run_once(prompt: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{ORIGAMI_BASE}/api/v2/agents",
            headers=_headers(),
            json={"prompt": prompt[:4000]},
        )
        if resp.status_code == 409:
            raise RuntimeError("Research is busy — try again in a moment.")
        if resp.status_code == 429:
            raise RuntimeError(
                "Research queue was busy — clearing and retrying."
            )
        if resp.status_code not in (200, 202):
            raise RuntimeError(f"Research start failed ({resp.status_code}): {resp.text[:200]}")
        return resp.json()


async def create_agent_run(prompt: str) -> Dict[str, Any]:
    """POST /api/v2/agents — returns admission payload with agent + run."""
    await release_research_capacity()
    last_err: Optional[RuntimeError] = None
    for attempt in range(5):
        try:
            return await _create_agent_run_once(prompt)
        except RuntimeError as e:
            last_err = e
            msg = str(e).lower()
            if "busy" in msg or "queue" in msg or "429" in msg:
                await release_research_capacity()
                await asyncio.sleep(2 + attempt * 2)
                continue
            raise
    raise last_err or RuntimeError("Research queue was busy — click Try again.")


async def continue_agent_run(
    agent_id: str,
    prompt: str,
    *,
    focus_table_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """POST follow-up run on existing agent (answer needs_input or refine)."""
    payload: Dict[str, Any] = {"prompt": prompt[:4000]}
    if focus_table_ids:
        payload["focusTableIds"] = focus_table_ids
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{ORIGAMI_BASE}/api/v2/agents/{agent_id}/runs",
            headers=_headers(),
            json=payload,
        )
        if resp.status_code in (409, 429):
            await release_research_capacity()
            raise RuntimeError("Research is busy — try again in a moment.")
        if resp.status_code not in (200, 202):
            raise RuntimeError(f"Research continue failed ({resp.status_code}): {resp.text[:200]}")
        return resp.json()


async def get_run(agent_id: str, run_id: str) -> Tuple[Dict[str, Any], int]:
    """GET run; returns (body, retry_after_seconds)."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        for attempt in range(10):
            resp = await client.get(
                f"{ORIGAMI_BASE}/api/v2/agents/{agent_id}/runs/{run_id}",
                headers=_headers(),
            )
            if resp.status_code == 429:
                wait = min(max(int(resp.headers.get("retry-after", 3)), 2), 12)
                await asyncio.sleep(wait)
                continue
            if resp.status_code >= 500 and attempt < 4:
                await asyncio.sleep(min(2 * (attempt + 1), 8))
                continue
            if resp.status_code != 200:
                raise RuntimeError(f"Origami poll failed ({resp.status_code}): {resp.text[:300]}")
            retry = int(resp.headers.get("retry-after", POLL_DEFAULT_SEC))
            return resp.json(), retry
        raise RuntimeError("Origami poll failed (429): rate limit")


async def poll_run_until_done(
    agent_id: str,
    run_id: str,
    on_tick: Optional[Callable[[Dict[str, Any]], Any]] = None,
    max_wait_sec: int = 600,
) -> Dict[str, Any]:
    """Poll until terminal status."""
    elapsed = 0
    while elapsed < max_wait_sec:
        body, retry = await get_run(agent_id, run_id)
        run = body.get("run") or body
        status = run.get("status", "running")
        if on_tick:
            maybe = on_tick(run)
            if asyncio.iscoroutine(maybe):
                await maybe
        if status != "running":
            return run
        wait = min(max(retry, 1), 3)
        await asyncio.sleep(wait)
        elapsed += wait
    raise RuntimeError("Research timed out — try again")


_DRAFT_COLUMN_SLUGS = (
    "first-name,last-name,title,company-name,linkedin-url,linkedin-profile,score,"
    "linkedin-message-draft,follow-up-message,linkedin-outreach,raw-data"
)


def _merge_rows_by_id(base: List[Dict[str, Any]], extra: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not extra:
        return base
    by_id = {str(r.get("id")): dict(r) for r in base if r.get("id")}
    for row in extra:
        rid = str(row.get("id") or "")
        if not rid:
            continue
        if rid in by_id:
            by_id[rid].update(row)
        else:
            by_id[rid] = dict(row)
    return list(by_id.values())


async def fetch_table_rows(
    table_id: str,
    page_size: int = 50,
    *,
    columns: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """GET /api/v1/tables/:id/rows — free read."""

    async def _page(params: Dict[str, Any]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        page_token: Optional[str] = None
        async with httpx.AsyncClient(timeout=60.0) as client:
            while len(out) < MAX_ROWS:
                q = {**params, "pageSize": min(page_size, MAX_ROWS - len(out))}
                if page_token:
                    q["pageToken"] = page_token
                resp = await client.get(
                    f"{ORIGAMI_BASE}/api/v1/tables/{table_id}/rows",
                    headers=_headers(),
                    params=q,
                )
                if resp.status_code != 200:
                    print(f"[origami] rows fetch {resp.status_code}: {resp.text[:200]}", flush=True)
                    break
                data = resp.json()
                batch = data.get("rows") or data.get("data") or []
                if isinstance(batch, list):
                    out.extend(batch[: MAX_ROWS - len(out)])
                page_token = data.get("nextPageToken") or data.get("next_page_token")
                if not page_token or not batch:
                    break
        return out[:MAX_ROWS]

    if columns:
        return await _page({"columns": columns})

    core = await _page({})
    draft = await _page({"columns": _DRAFT_COLUMN_SLUGS})
    return _merge_rows_by_id(core, draft)


def extract_primary_table(run: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    response = run.get("response") or {}
    tables = response.get("tables") or []
    if not tables:
        return None
    return max(tables, key=lambda t: t.get("leadCount") or 0)


def _table_looks_like_people(table: Dict[str, Any]) -> bool:
    cols = table.get("columns") or []
    text = " ".join(
        f"{c.get('slug', '')} {c.get('name', '')}".lower() for c in cols
    )
    return any(k in text for k in ("first", "last", "linkedin", "founder", "title", "email"))


def _table_is_companies_only(table: Dict[str, Any]) -> bool:
    name = (table.get("name") or "").lower()
    if "compan" in name and not _table_looks_like_people(table):
        return True
    cols = table.get("columns") or []
    text = " ".join(f"{c.get('slug', '')} {c.get('name', '')}".lower() for c in cols)
    if "compan" in text and not any(k in text for k in ("first", "last", "founder", "/in")):
        return True
    return False


def _table_score(table: Dict[str, Any], *, want_founders: bool) -> int:
    n = table.get("rowCount") or table.get("leadCount") or 0
    name = (table.get("name") or "").lower()
    if not want_founders:
        return n
    score = n
    if _table_is_companies_only(table):
        return -1
    if "founder" in name or "people" in name or "contact" in name:
        score += 10_000
    if "compan" in name:
        score -= 5_000
    if _table_looks_like_people(table):
        score += 1_000
    return score


async def list_workspace_tables(workspace_id: str) -> List[Dict[str, Any]]:
    """Free v1 read — tables for one Origami workspace."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{ORIGAMI_BASE}/api/v1/tables",
            headers=_headers(),
        )
        if resp.status_code != 200:
            return []
        tables = resp.json().get("tables") or []
        return [t for t in tables if t.get("workspaceId") == workspace_id]


def pick_workspace_table(
    tables: List[Dict[str, Any]],
    *,
    want_founders: bool = False,
) -> Optional[Dict[str, Any]]:
    if not tables:
        return None
    if want_founders:
        ranked = [(t, _table_score(t, want_founders=True)) for t in tables]
        ranked = [(t, s) for t, s in ranked if s >= 0]
        if not ranked:
            return None
        return max(ranked, key=lambda x: x[1])[0]
    people = [t for t in tables if _table_looks_like_people(t)]
    pool = people or tables
    return max(pool, key=lambda t: t.get("rowCount") or t.get("leadCount") or 0)


async def resolve_live_table(
    run: Dict[str, Any],
    *,
    workspace_id: Optional[str] = None,
    table_id_hint: Optional[str] = None,
    want_founders: bool = False,
) -> Optional[Dict[str, Any]]:
    """Table from run response, or the best v1 table in the workspace (available while run is still going)."""
    tbl = extract_primary_table(run)
    if tbl and tbl.get("id"):
        return {
            "id": tbl["id"],
            "url": tbl.get("url", ""),
            "leadCount": tbl.get("leadCount") or 0,
            "name": tbl.get("name", ""),
        }
    ws = workspace_id or run.get("workspaceId")
    if not ws:
        return None
    v1_tables = await list_workspace_tables(ws)
    best = pick_workspace_table(v1_tables, want_founders=want_founders)
    if not best:
        return None
    if table_id_hint and table_id_hint != best.get("id"):
        hinted = next((t for t in v1_tables if t.get("id") == table_id_hint), None)
        if hinted and (hinted.get("rowCount") or 0) >= (best.get("rowCount") or 0):
            best = hinted
    url = f"{ORIGAMI_BASE}/workspace/{ws}?table={best['id']}"
    return {
        "id": best["id"],
        "url": url,
        "leadCount": best.get("rowCount") or 0,
        "name": best.get("name", ""),
    }


async def get_credits() -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{ORIGAMI_BASE}/api/v1/credits", headers=_headers())
        if resp.status_code == 200:
            return resp.json()
    return {}
