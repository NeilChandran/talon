# Talon — AI-Powered B2B LinkedIn Outreach

**Repository:** [github.com/NeilChandran/talon](https://github.com/NeilChandran/talon)  
**Product:** [Hedwig](https://hedwigmail.com) — AI-native inbox for Gmail + Google Calendar  
**Course submission:** This README is structured to address the **Project Submission Rubric (15 points)**. A demo video should walk through the same sections in order.

---

## Quick start

```bash
git clone https://github.com/NeilChandran/talon.git
cd talon
cp .env.example backend/.env
# Add ORIGAMI_API_KEY, ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_KEY to backend/.env

./scripts/start.sh
# Opens frontend at http://localhost:3000 and API at http://localhost:8000
```

`start.sh` rsyncs the repo to `~/Projects/talon-outreach` (avoids iCloud Desktop timeouts), installs deps, and runs both servers.

---

## Rubric: Problem & Insight (3 points)

### Meaningful problem

Founders doing outbound spend hours manually:
1. Finding ICP-matched people on LinkedIn  
2. Writing personalized connection notes (≤300 characters)  
3. Tracking who is drafted, scheduled, sent, accepted, or replied  

Existing tools either stop at list-building (no sequencer) or require jumping between tabs. **Talon closes the loop:** plain-English ICP → qualified people table → personalized copy → Origami-powered LinkedIn sequencer → unified inbox.

### Motivation

Hedwig is an AI inbox for Gmail + Google Calendar. Our best users are founders and operators at early-stage startups (YC, Series A/B, a16z/Pear portfolio). We needed a repeatable way to **find** those founders and **reach them on LinkedIn** without hand-copying drafts into another product.

### Original, ambitious approach

| Idea | Why it matters |
|------|----------------|
| **Origami as research + sequencer backend** | Talon owns UX and copy; [Origami](https://origami.chat) runs agentic people search and LinkedIn outreach scheduling — one launch path instead of rebuilding Voyager automation |
| **Prompt-aware templates** | “Series B founders” must not get “YC founders” copy — audience is inferred from the search prompt, not a single global template |
| **Origami-style sequencer UI in Talon** | Step cards, Premium → sender → recipient routing, “Scheduled for 3:14 PM” labels — operators stay in Talon while Origami executes |
| **Messages tab** | Global connection + follow-up templates (`{{first_name}}`, `{{company}}`) applied across all campaigns |

---

## Rubric: Execution & Technical Work (5 points)

### What was built

**End-to-end artifact:** a working web app (Next.js 14 + FastAPI) used for real outreach campaigns.

| Layer | Implementation |
|-------|------------------|
| **Frontend** | Next.js App Router, TypeScript, Origami-inspired campaign pane, Inbox, Messages editor, workspace search UI |
| **Backend** | FastAPI, async Python, modular routers (`/searches`, `/outreach`, `/campaigns`, …) |
| **Data** | Supabase (Postgres) with SQLite fallback for local dev (`sqlite_store.py`) |
| **AI** | Anthropic Claude — lead scoring, connection notes, agent chat |
| **Research** | Origami API v2 — agent runs, table sync, sequencer launch |
| **Auth** | Supabase JWT middleware (`middleware_auth.py`, optional) |

### Major features (functional today)

1. **Home / search** — Plain-English ICP prompt → Origami agent run → live lead table  
2. **Campaign pane** — Per-lead 2-step sequence (connection + follow-up), status pills (Drafted, Scheduled for …, In progress, Sent, Replied)  
3. **Launch all** — `POST /searches/{id}/campaign/launch-origami` → Origami sequencer, auto-confirms `needs_input`  
4. **Inbox** (`/outreach`) — All enrollments: draft, scheduled, sent, in progress, replied; Origami sync button  
5. **Messages** (`/messages`) — Edit global LinkedIn connection + follow-up templates; persisted in `talon_settings.json`  
6. **Origami sync** — LinkedIn URLs, drafts, `sendStatus`, estimated schedule times backfilled to enrollments  
7. **Template intelligence** — Series B / YC / generic founder audiences; strips stale “YC founders” copy on non-YC searches  

### Technical effort (scope-matched)

- **~50+ backend/frontend files** touched across search pipeline, inbox aggregation, outreach templates, SQLite migrations  
- **Origami integration:** `origami_service.py` (table rows, schedule estimation, launch), `search_runner.py` (sync, heal failed enrollments)  
- **Inbox service:** `inbox_service.py` — buckets enrollments + draft rows for leads without enrollments  
- **Resilience:** throttled Origami polling on search read, 500 retries, stale-search failure, SQLite-safe `/leads/stats`  

### Iteration & progress (evidence in git)

Public commit history shows evolution:

| Phase | Commits / work |
|-------|----------------|
| v0 | Apify prospecting, LinkedIn Voyager, basic sequences |
| v1 | GTM analytics, send caps, reply detection |
| v2 | Origami workspace UI, branding, campaign enrollments |
| v3 | Origami launch path, inbox, Messages tab, Series B templates, schedule labels |

See `git log --oneline` for full timeline.

### Routes

| Route | Purpose |
|-------|---------|
| `/` | New search (ICP prompt) |
| `/search/{id}` | Workspace — leads table, campaign pane, chat |
| `/workspaces` | All searches |
| `/sequencing/campaigns` | Campaign list |
| `/messages` | **Connection + follow-up templates** |
| `/outreach` | **Inbox** — all message states |
| `/settings` | LinkedIn session, Instantly, API keys |

---

## Rubric: Evaluation & Evidence (3 points)

### How we validate claims

| Claim | Evidence |
|-------|----------|
| Origami returns real founders | Live searches (e.g. “find founders of series a startup”) → 30 rows with `/in/` LinkedIn URLs |
| Sequencer schedules sends | Origami `linkedin-outreach` column `sendStatus: scheduled`; Talon mirrors to `campaign_enrollments.origami_send_status` |
| Templates personalize | `personalize_connection()` + `fit_connection_note()` — connection notes ≤300 chars, no mid-word cuts (tested on long company names) |
| Inbox reflects state | `GET /outreach/inbox` returns bucket counts (draft / scheduled / in_progress / sent) |
| Series B ≠ YC copy | `audience_phrase()` + `note_has_wrong_audience()` — regression fixed after user report |

### Benchmarks / metrics (internal runs)

- **Search completion:** ~30 leads per Origami run (configurable via `MAX_LEADS_PER_SEARCH`)  
- **Schedule spacing:** 25-minute intervals estimated from `origami_launch_at` when Origami API omits exact times  
- **API load:** Search polling reduced from 1s → 3s; Origami sync throttled to 5s per search to prevent socket hang-ups  

### Limitations (honest)

| Limitation | Impact |
|------------|--------|
| Origami API sometimes returns 500 on poll | Search may stall; auto-fail after 5 min with 0 leads |
| Exact send time not always in Origami table API | Talon **estimates** queue times — labels say “Scheduled for …” but may be ±25 min |
| LinkedIn automation via Talon Voyager path is legacy | **Production path is Origami launch**, not Talon `li_at` session |
| Supabase schema required for cloud | Local dev falls back to SQLite; run `supabase/schema.sql` for full parity |
| No formal user study yet | Validation is operator dogfooding + API/integration tests |

### Failure analysis performed

- SQLite `GET /leads/stats` 500 → fixed Supabase-only code path  
- Inbox showing only “in progress” → missing API + wrong status bucket order  
- “YC founders” on Series B search → template logic assumed all founder prompts = YC  
- Frontend “Server error” overlay → unhandled 500 from background stats prefetch  

---

## Rubric: Communication & Presentation (2 points)

### For reviewers / TAs

1. **Watch the demo video** (linked in submission) — follows this README section order  
2. **Clone & run** — `./scripts/start.sh` with keys in `backend/.env`  
3. **Happy path:** Home → “find founders of series b startups” → wait for leads → open campaign → verify Messages templates → Launch all → check Inbox  

### Architecture (high level)

```
User prompt
    → FastAPI /searches (create + background Origami run)
    → Origami agent (people table + draft columns)
    → sync_origami_drafts() → Talon leads + enrollments
    → Campaign UI (SearchCampaignPane)
    → launch_origami_sequences() → Origami sequencer
    → sync_origami_outreach_schedule() → Inbox statuses
```

### Key files

| File | Role |
|------|------|
| `backend/services/origami_service.py` | Origami API, row mapping, schedule build |
| `backend/services/search_runner.py` | Search jobs, sync, Origami launch |
| `backend/services/inbox_service.py` | Inbox rows + stats |
| `backend/services/outreach_templates.py` | Audience-aware copy |
| `backend/services/app_settings.py` | Messages tab defaults |
| `frontend/components/SearchCampaignPane.tsx` | Origami-style sequencer UI |
| `frontend/app/outreach/page.tsx` | Inbox |
| `frontend/app/messages/page.tsx` | Template editor |

---

## Rubric: Process, Integrity & Disclosure (2 points)

### AI usage disclosure

| Tool | How it was used |
|------|-----------------|
| **Anthropic Claude** | Runtime: lead scoring, LinkedIn note generation, workspace agent replies (`claude_service.py`) |
| **Origami** | Runtime: people search agents + LinkedIn sequencer (third-party API, not generative AI) |
| **Cursor / Claude (development)** | Implementation assistance: debugging, UI parity with Origami, inbox API, template fixes, README — **all code reviewed and run locally by the author** |

We disclose AI-assisted **development**; product-facing copy is templated + Claude-personalized per lead with human-approved global templates in `/messages`.

### Sources & collaborators — MUST cite

| Source | Relationship | Our substantial changes |
|--------|--------------|-------------------------|
| **[NeilChandran/talon](https://github.com/NeilChandran/talon)** (this repo) | Original project base | Extended from LinkedIn-only prospecting to Origami-integrated research + sequencer |
| **[Origami.chat](https://origami.chat)** | **UI/UX inspiration + API integration** | Talon is a custom frontend/orchestration layer; we call Origami v2 agents API, sync tables, launch sequences — not a fork of Origami source |
| **Next.js, FastAPI, Supabase** | Open-source frameworks | Standard usage |
| **Anthropic API** | Managed AI service | Prompting + structured outputs for outreach |
| **Contributor: subha@talon.ai** | Early commits | GTM/outbound foundation (see git history) |

If you forked starter code: **this repository is the canonical Talon codebase**; prior commits document incremental authorship.

### Major decisions

1. **Origami for send, Talon for find+edit** — avoids LinkedIn ToS risk on Talon-side automation while keeping operator UX in one app  
2. **SQLite fallback** — lowers setup friction for grading/repro without Supabase project  
3. **Global Messages tab** — one connection + follow-up for Hedwig GTM; per-search overrides via `linkedin_message_template` on search row  
4. **Estimated schedule times** — better UX than “Scheduled” with no time when API lacks timestamps  

### Development artifacts

- Public GitHub repo with commit history  
- `supabase/schema.sql` — cloud schema  
- `.env.example` — required keys documented (no secrets committed)  
- `scripts/start.sh` / `scripts/start-local.sh` — reproducible local run  

---

## Environment variables

Copy `.env.example` → `backend/.env`.

| Variable | Required | Description |
|----------|----------|-------------|
| `ORIGAMI_API_KEY` | ✅ for search | Origami agent + sequencer |
| `ANTHROPIC_API_KEY` | ✅ for AI copy | Claude scoring + generation |
| `SUPABASE_URL` / `SUPABASE_KEY` | ✅ for cloud | Postgres + auth (SQLite used if unavailable) |
| `DATABASE_URL` | Optional | Default: local SQLite `talon.db` |
| `INSTANTLY_API_KEY` | Optional | Email outreach export |

Frontend (optional auth): copy `frontend/.env.local.example` → `frontend/.env.local`.

---

## Default LinkedIn copy (Messages tab)

**Connection request** (≤300 chars, uses `{{first_name}}` / `{{company}}`):

> Hey {{first_name}}! I'm Neil, a Stanford student and Z Fellow building Hedwig, an AI-native inbox for Gmail + Google Calendar. It handles scheduling, follow-ups, drafting replies, and inbox organization. Free to use: hedwigmail.com. Thought it could fit well for you at {{company}}. Would love to connect.

**Follow-up** (after accept):

> Wanted to follow up here. Hedwig plugs directly into Gmail + Google Calendar and handles scheduling, follow-ups, inbox organization, and drafting replies in your tone.
>
> Teams across Stanford, Harvard, Yale, Berkeley, and UCLA have been using it heavily already, along with people from YC, a16z, and Pear portfolio companies. No migration or workflow change required. Completely free to use right now at hedwigmail.com - would love your thoughts.

Edit anytime under **Sequencing → Messages**.

---

## API reference (selected)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/searches/` | Start ICP search |
| `GET` | `/searches/{id}` | Search + leads + progress |
| `POST` | `/searches/{id}/campaign/prepare` | Draft enrollments |
| `POST` | `/searches/{id}/campaign/launch-origami` | Launch Origami sequencer |
| `GET` | `/outreach/inbox?sync=1` | Inbox list + Origami sync |
| `GET/PUT` | `/outreach-export/settings` | Messages templates + Instantly |

---

## Security

- Never commit `.env`, `backend/talon.db`, or `backend/talon_settings.json` (gitignored)  
- Use service-role Supabase key only on backend  
- LinkedIn `li_at` session files are gitignored  

---

## License & contact

Internal Hedwig / course project. Questions: open an issue on GitHub or contact the repo owner.

**Submission checklist for video:** Problem → Demo (search → campaign → launch → inbox) → Architecture slide → Limitations → AI disclosure → `git log` screenshot.
