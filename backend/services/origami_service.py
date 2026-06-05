"""Origami API v2 — agent runs + v1 table reads. See .cursor/skills/origami-api/SKILL.md"""
import asyncio
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

ORIGAMI_API_KEY = os.getenv("ORIGAMI_API_KEY", "")
ORIGAMI_BASE = os.getenv("ORIGAMI_BASE_URL", "https://origami.chat")
MAX_ROWS = int(os.getenv("MAX_LEADS_PER_SEARCH", "25"))
POLL_DEFAULT_SEC = 10


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


def map_origami_row(row: Dict[str, Any]) -> Dict[str, Any]:
    first = _pick(row, "first name", "first_name", "firstname")
    last = _pick(row, "last name", "last_name", "lastname")
    if not first and not last:
        full = _pick(row, "name", "full name", "contact name", "founder name")
        parts = full.split(None, 1) if full else []
        first = parts[0] if parts else ""
        last = parts[1] if len(parts) > 1 else ""

    linkedin = _pick(row, "linkedin", "linkedin url", "linkedin_url", "linkedin profile")
    raw = row.get("raw-data") or row.get("raw_data")
    if isinstance(raw, dict):
        link = raw.get("link") or {}
        if not linkedin and isinstance(link, dict):
            linkedin = str(link.get("linkedin") or "").strip()
        prof = raw.get("profile") or {}
        if isinstance(prof, dict):
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
            if v and "linkedin" in str(k).lower() and str(v).startswith("http"):
                linkedin = str(v).strip()
                break
    if linkedin and "/companies/" in linkedin:
        linkedin = ""
    if linkedin and not linkedin.startswith("http"):
        linkedin = f"https://www.linkedin.com/in/{linkedin.lstrip('/')}"

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

    return {
        "first_name": first,
        "last_name": last,
        "name": f"{first} {last}".strip() or _pick(row, "name"),
        "title": title,
        "company": company,
        "email": _pick(row, "email", "work email", "verified email", "email address"),
        "linkedin_url": linkedin,
        "icp_score": 7,
        "score_reason": "Origami agent",
        "source_url": linkedin or _pick(row, "website", "company website", "company domain"),
    }


def parse_lead_count_from_prompt(user_prompt: str) -> int:
    import re

    m = re.search(r"\b(\d{1,3})\b", user_prompt)
    if m:
        return max(5, min(MAX_ROWS, int(m.group(1))))
    return min(20, MAX_ROWS)


def wants_founders(user_prompt: str) -> bool:
    pl = user_prompt.lower()
    return any(w in pl for w in ("founder", "founders", "co-founder", "cofounder"))


def build_search_prompt(user_prompt: str) -> str:
    """Short, concrete brief — Origami works faster with a specific count."""
    n = parse_lead_count_from_prompt(user_prompt)
    if wants_founders(user_prompt):
        return (
            f"Find {n} individual founders (people, not companies) matching: {user_prompt.strip()}. "
            "Create a PEOPLE table with columns: First Name, Last Name, Title, Company Name, "
            "LinkedIn URL (/in/), YC Batch. "
            "Do NOT stop at a companies-only table — I need founder profiles to message. "
            "Skip deep email enrichment. Do not ask clarifying questions."
        )
    return (
        f"Find {n} people matching: {user_prompt.strip()}. "
        "Columns: First Name, Last Name, Title, Company, LinkedIn URL. "
        "Build the people table immediately; skip deep email enrichment. "
        "Do not ask clarifying questions."
    )


def run_progress_message(run: Dict[str, Any]) -> str:
    steps = run.get("steps") or {}
    done, mx = steps.get("completed"), steps.get("max")
    if isinstance(done, int) and isinstance(mx, int) and mx > 0:
        return f"Origami working… step {done}/{mx}"
    st = run.get("status", "running")
    if st == "needs_input":
        return "Answering Origami questions…"
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


async def create_agent_run(prompt: str) -> Dict[str, Any]:
    """POST /api/v2/agents — returns admission payload with agent + run."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{ORIGAMI_BASE}/api/v2/agents",
            headers=_headers(),
            json={"prompt": prompt[:4000]},
        )
        if resp.status_code == 409:
            raise RuntimeError("Origami agent busy — try again in a minute")
        if resp.status_code == 429:
            raise RuntimeError(
                "Origami concurrent agent limit (1 on your plan). Wait for the current run to finish, then retry."
            )
        if resp.status_code not in (200, 202):
            raise RuntimeError(f"Origami create agent failed ({resp.status_code}): {resp.text[:300]}")
        return resp.json()


async def continue_agent_run(agent_id: str, prompt: str) -> Dict[str, Any]:
    """POST follow-up run on existing agent (answer needs_input or refine)."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{ORIGAMI_BASE}/api/v2/agents/{agent_id}/runs",
            headers=_headers(),
            json={"prompt": prompt[:4000]},
        )
        if resp.status_code == 409:
            raise RuntimeError("Origami agent busy — wait for the current run to finish")
        if resp.status_code == 429:
            raise RuntimeError("Origami concurrent agent limit — wait and retry")
        if resp.status_code not in (200, 202):
            raise RuntimeError(f"Origami continue run failed ({resp.status_code}): {resp.text[:300]}")
        return resp.json()


async def get_run(agent_id: str, run_id: str) -> Tuple[Dict[str, Any], int]:
    """GET run; returns (body, retry_after_seconds)."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(
            f"{ORIGAMI_BASE}/api/v2/agents/{agent_id}/runs/{run_id}",
            headers=_headers(),
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Origami poll failed ({resp.status_code}): {resp.text[:300]}")
        retry = int(resp.headers.get("retry-after", POLL_DEFAULT_SEC))
        return resp.json(), retry


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
        wait = max(retry, POLL_DEFAULT_SEC)
        await asyncio.sleep(wait)
        elapsed += wait
    raise RuntimeError("Origami run timed out waiting for completion")


async def fetch_table_rows(table_id: str, page_size: int = 50) -> List[Dict[str, Any]]:
    """GET /api/v1/tables/:id/rows — free read."""
    rows: List[Dict[str, Any]] = []
    page_token: Optional[str] = None
    async with httpx.AsyncClient(timeout=60.0) as client:
        while len(rows) < MAX_ROWS:
            params: Dict[str, Any] = {"pageSize": min(page_size, MAX_ROWS - len(rows))}
            if page_token:
                params["pageToken"] = page_token
            resp = await client.get(
                f"{ORIGAMI_BASE}/api/v1/tables/{table_id}/rows",
                headers=_headers(),
                params=params,
            )
            if resp.status_code != 200:
                print(f"[origami] rows fetch {resp.status_code}: {resp.text[:200]}", flush=True)
                break
            data = resp.json()
            batch = data.get("rows") or data.get("data") or []
            if isinstance(batch, list):
                rows.extend(batch[: MAX_ROWS - len(rows)])
            page_token = data.get("nextPageToken") or data.get("next_page_token")
            if not page_token or not batch:
                break
    return rows[:MAX_ROWS]


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
