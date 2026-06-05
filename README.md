# Talon — AI-Powered B2B LinkedIn Outreach Agent

**Repo:** github.com/NeilChandran/talon  
**Demo video:** https://drive.google.com/file/d/18TQxJRrnpxKec2hCpj6zO_H68BNsu2Ra/view?usp=sharing

---

## Problem & Insight

Founders doing outbound face three sequential bottlenecks. First, finding ICP-matched people is manual — LinkedIn search requires dozens of filtered queries to surface the right profiles. Second, writing personalized connection notes under 300 characters for each person takes hours. Third, tracking who got messaged, who accepted, and who replied lives in spreadsheets or nowhere at all.

Existing tools solve one piece. Apollo and ZoomInfo give you lists but no outreach. LinkedIn Sales Navigator gives you search but no copy. Outreach tools like Instantly handle sequencing but require you to bring your own leads and write your own messages. Nothing closes the loop from ICP description to sent message to reply tracking in one place.

Talon does. You describe your ideal customer in plain English, get a live-sourced table of matched people back in seconds, review personalized connection notes generated for each one, and launch the full sequence without leaving the app.

The motivation is direct: Hedwig's ICP is founders and operators at early-stage startups. We needed a repeatable way to find them and reach them on LinkedIn. We built Talon to solve our own outbound problem and turned it into a standalone tool.

---

## Execution & Technical Work

**What was built:** A full-stack web app (Next.js 14 + FastAPI) used for real outreach campaigns, not a prototype.

**Stack:**

| Layer | Implementation |
|---|---|
| Frontend | Next.js App Router, TypeScript |
| Backend | FastAPI, async Python |
| Database | Supabase (Postgres) with SQLite fallback |
| AI | Anthropic Claude — lead scoring, note generation, agent chat |
| Research | Origami API v2 — people search, table sync, sequencer |

**Features that work today:**

- Plain-English ICP prompt → Origami agent run → live lead table populated in real time
- Per-lead 2-step sequence (connection request + follow-up) with status tracking: Drafted, Scheduled, In Progress, Sent, Replied
- Launch all → POST to Origami sequencer, auto-confirms needs_input states
- Inbox aggregating all enrollment states across campaigns with Origami sync
- Global Messages tab to edit LinkedIn templates with `{{first_name}}` / `{{company}}` variables, persisted across sessions
- Audience-aware template logic — Series B founders get different copy than YC founders, inferred from the search prompt

**Iteration evidence (git history):**

| Phase | What changed |
|---|---|
| v0 | Apify prospecting, LinkedIn Voyager, basic sequences |
| v1 | GTM analytics, send caps, reply detection |
| v2 | Origami workspace UI, campaign enrollments |
| v3 | Origami launch path, inbox, Messages tab, audience-aware templates, schedule labels |

---

## Evaluation & Evidence

| Claim | How it was validated |
|---|---|
| Origami returns real founders | Live searches ("find founders of series a startup") consistently return 30 rows with /in/ LinkedIn URLs |
| Sequencer schedules sends | Origami linkedin-outreach column shows `sendStatus: scheduled`; mirrored to `campaign_enrollments` |
| Notes personalize correctly | `personalize_connection()` tested on long company names, edge cases, non-YC audiences |
| Inbox reflects real state | `GET /outreach/inbox` returns accurate bucket counts across draft / scheduled / in_progress / sent |
| Audience copy is correct | `audience_phrase()` + `note_has_wrong_audience()` regression fixed after real outreach surfaced the bug |

**Performance metrics from internal runs:**
- ~30 leads per Origami run (configurable via `MAX_LEADS_PER_SEARCH`)
- Schedule spacing: 25-minute estimated intervals when Origami API omits exact timestamps
- Polling reduced from 1s to 3s after socket hang-ups; Origami sync throttled to 5s per search

**Honest limitations:**

| Limitation | Impact |
|---|---|
| Origami API returns 500 intermittently | Search can stall; auto-fails after 5 min with 0 leads |
| Exact send time not always in Origami response | Schedule labels are estimates, ±25 min |
| No formal user study | Validated by operator dogfooding and integration tests only |
| Supabase required for full cloud parity | Local dev uses SQLite fallback |

**Failures caught and fixed:**
- `GET /leads/stats` returning 500 — Supabase-only code path not falling back to SQLite
- Inbox showing only "in progress" — wrong status bucket order in aggregation
- "YC founders" copy appearing on Series B searches — template logic assumed all founder prompts were YC
- Frontend "Server error" overlay — unhandled 500 from background stats prefetch

---

## Communication & Presentation

**Happy path for graders:**
Home → type "find founders of series b startups"
→ wait for leads table to populate
→ open campaign pane → verify Messages templates
→ Launch all → check Inbox for scheduled statuses

**Architecture:**
User prompt
→ FastAPI /searches (create + background Origami run)
→ Origami agent (people table + draft columns)
→ sync_origami_drafts() → Talon leads + enrollments
→ Campaign UI (SearchCampaignPane)
→ launch_origami_sequences() → Origami sequencer
→ sync_origami_outreach_schedule() → Inbox statuses

**Key files:**

| File | Role |
|---|---|
| `backend/services/origami_service.py` | Origami API, row mapping, schedule |
| `backend/services/search_runner.py` | Search jobs, sync, launch |
| `backend/services/inbox_service.py` | Inbox rows and stats |
| `backend/services/outreach_templates.py` | Audience-aware copy |
| `frontend/components/SearchCampaignPane.tsx` | Sequencer UI |
| `frontend/app/outreach/page.tsx` | Inbox |
| `frontend/app/messages/page.tsx` | Template editor |

---

## Process, Integrity & Disclosure

**AI usage:**

| Tool | How used |
|---|---|
| Anthropic Claude (runtime) | Lead scoring, LinkedIn note generation, agent replies |
| Origami (runtime) | People search agents + LinkedIn sequencer — third-party API |
| Cursor / Claude (development) | Implementation assistance, debugging, UI work — all code reviewed and run locally |

**Sources and citations:**

| Source | Relationship | Substantial changes made |
|---|---|---|
| NeilChandran/talon | Original project base | Extended from LinkedIn-only prospecting to full Origami-integrated research + sequencer |
| Origami.chat | UI/UX inspiration + API integration | Talon is a custom frontend and orchestration layer calling Origami v2 — not a fork |
| Next.js, FastAPI, Supabase | Open-source frameworks | Standard usage |
| Anthropic API | Managed AI service | Structured prompting for outreach personalization |
| subha@talon.ai | Early commits | GTM/outbound foundation (see git history) |

**Major decisions:**
- Used Origami for sending rather than building LinkedIn automation — avoids ToS risk while keeping operator UX inside Talon
- SQLite fallback lowers setup friction for grading without requiring a Supabase project
- Global Messages tab with per-search override capability rather than forcing per-campaign template setup

---

## Setup

```bash
git clone https://github.com/NeilChandran/talon.git
cd talon
cp .env.example backend/.env
# Add ORIGAMI_API_KEY, ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_KEY to backend/.env
./scripts/start.sh
# Frontend at http://localhost:3000 — API at http://localhost:8000
```

**Required environment variables:**

| Variable | Required | Description |
|---|---|---|
| `ORIGAMI_API_KEY` | Yes | Origami agent + sequencer |
| `ANTHROPIC_API_KEY` | Yes | Claude scoring + note generation |
| `SUPABASE_URL` | Yes (cloud) | Postgres + auth |
| `SUPABASE_KEY` | Yes (cloud) | Postgres + auth |
| `DATABASE_URL` | Optional | Defaults to local SQLite `talon.db` |
| `INSTANTLY_API_KEY` | Optional | Email outreach export |

---

**Video order:** Problem → Demo (search → campaign → launch → inbox) → Architecture → Limitations → AI disclosure → git log
