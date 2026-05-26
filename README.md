# Talon — Hedwig Internal Sourcing Tool

Talon is Hedwig's internal LinkedIn prospecting and outreach automation platform. It finds real people on LinkedIn, scores them against our ICP, generates personalized connection messages using Claude AI, and automates the full outreach sequence — all from one interface.

**Built for speed. Zero manual LinkedIn browsing.**

---

## What it does

1. **Prospect** — Describe who you're looking for in plain English. Talon searches real LinkedIn profiles via the Voyager API and returns scored, ranked results in seconds.
2. **Score** — Every lead is automatically scored 1–10 against Hedwig's ICP rubric using Claude. You see exactly why each person scored the way they did.
3. **Generate** — Claude writes personalized LinkedIn connection notes (≤300 chars) and follow-up messages tailored to each person's role, company, and background.
4. **Automate** — Run a sequence and Talon sends connection requests + messages automatically, with human-paced delays to stay under LinkedIn's radar.

---

## Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 14 (App Router), TypeScript, inline styles |
| Backend | Python FastAPI, SQLAlchemy async, asyncpg |
| Database | PostgreSQL |
| AI | Anthropic Claude `claude-sonnet-4-20250514` — scoring + message generation |
| LinkedIn | Voyager API (internal LinkedIn API) — real profile search + automation |

---

## Setup

### 1. Clone and configure

```bash
git clone https://github.com/NeilChandran/talon.git
cd talon
cp .env.example .env
# Add your ANTHROPIC_API_KEY and DATABASE_URL to .env
```

### 2. Start PostgreSQL

```bash
docker-compose up postgres -d
```

### 3. Backend

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python init_db.py          # creates tables + seeds default sequences
uvicorn main:app --reload  # runs on :8000
```

### 4. Frontend

```bash
cd frontend
npm install
npm run dev                # runs on :3000
```

Open [http://localhost:3000](http://localhost:3000)

---

## Pages

| Route | What it does |
|-------|-------------|
| `/` | Dashboard — new prospects waiting for outreach |
| `/prospecting` | Search LinkedIn by plain-English description |
| `/leads` | Full lead table — filter, sort, bulk-select, update status |
| `/outreach` | Generate Claude-personalized LinkedIn messages per lead |
| `/sequences` | Create and run automated connection + message sequences |
| `/settings` | Connect LinkedIn account (paste `li_at` cookie — one field) |

---

## LinkedIn connection

Talon authenticates with LinkedIn using your session cookie — no OAuth, no official API needed.

1. Go to **Settings** in the app
2. Open LinkedIn in Chrome → DevTools → Application → Cookies
3. Copy the value of `li_at`
4. Paste it into Talon — done

JSESSIONID is derived automatically. The session is stored permanently until you disconnect.

---

## ICP scoring rubric

| Score | Profile |
|-------|---------|
| **10** | Founder / CEO at 1–20 person YC or VC-backed startup |
| **7–9** | Chief of Staff / Ops Lead / VP Ops at a fast-moving startup |
| **4–6** | Knowledge worker, uses Notion / Linear / Slack |
| **1–3** | Enterprise role, non-decision-maker, Outlook stack |

---

## Sequences

Three defaults are seeded on first run:

| Sequence | Type | Timing |
|----------|------|--------|
| Connect + Intro | Connection request + note | Day 0 |
| Follow-up | Direct message after connecting | Day 3 |
| Final Message | Short, leaves the door open | Day 7 |

All messages are AI-generated per lead unless you provide a custom template with `{{first_name}}` and `{{company}}` placeholders.

---

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | ✅ | Claude API — scoring and message generation |
| `DATABASE_URL` | ✅ | PostgreSQL connection string |

---

## Important

- LinkedIn limits connection requests to ~100/week. Talon adds 4–10 second random delays between actions.
- Never commit `.env` or `.linkedin_session.json` — both are in `.gitignore`.
- This tool is for internal Hedwig use only.
