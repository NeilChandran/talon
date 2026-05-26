# Hedwig Outreach

Internal AI lead prospecting tool for [Hedwig AI](https://hedwig-ai.com).

## Stack

- **Frontend**: Next.js 14 (App Router), Tailwind CSS, TypeScript
- **Backend**: Python FastAPI, SQLAlchemy async, asyncpg
- **Database**: PostgreSQL
- **AI**: Anthropic Claude (`claude-sonnet-4-20250514`) — lead scoring + email generation
- **Scraping**: Playwright (Google + company sites)
- **Email enrichment**: Hunter.io API
- **Email sending**: Resend API

---

## Setup

### 1. Clone & configure

```bash
cp .env.example .env
# Fill in ANTHROPIC_API_KEY, HUNTER_API_KEY, RESEND_API_KEY
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
playwright install chromium
python init_db.py          # creates tables + seeds default sequences
uvicorn main:app --reload  # runs on :8000
```

### 4. Frontend

```bash
cd frontend
npm install
npm run dev                # runs on :3000
```

Open [http://localhost:3000](http://localhost:3000).

---

## Pages

| Route | Feature |
|-------|---------|
| `/` | Dashboard — stats + recent leads feed |
| `/prospecting` | AI-powered lead discovery — describe a target, Claude finds + scores leads |
| `/leads` | Full sortable/filterable lead table with inline status editing |
| `/outreach` | Select leads + sequence → Claude writes personalized emails → copy or send |
| `/sequences` | Manage email sequences (Cold Intro / Follow-up / Break-up) |

---

## How prospecting works

1. You describe a target (e.g. _"YC W24 founders building B2B SaaS with 5-20 employees"_)
2. Claude parses it into 5 targeted Google search queries
3. Playwright scrapes results, extracting names, titles, companies, LinkedIn URLs
4. Claude scores each lead 1–10 against Hedwig's ICP rubric
5. Hunter.io finds professional email addresses
6. Leads are saved to the database and appear in the Leads table

**Note**: Web scraping is inherently fragile. LinkedIn actively blocks scrapers — results come primarily from Google snippets and company websites. Expect ~5-25 leads per prospecting run depending on the query.

---

## Lead scoring rubric

| Score | Profile |
|-------|---------|
| **10** | Founder/CEO at 1–20 person YC/VC startup, Gmail/Superhuman user |
| **7–9** | CoS / Ops Lead / VP Ops at startup, productivity-focused |
| **4–6** | Knowledge worker at mid-size company, Notion/Linear/Slack user |
| **1–3** | Enterprise, non-email-heavy role, Outlook/Microsoft stack |

---

## Email sequences

Three defaults are seeded on `init_db.py`:

| Sequence | Subject | Delay |
|----------|---------|-------|
| Cold Intro | "your inbox, but smarter" | Day 0 |
| Follow-up | "Re: your inbox" | Day 3 |
| Break-up | "okay, last one" | Day 7 |

Claude personalizes every email based on the lead's role, company, tech stack, and score reason.

---

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | ✅ | Claude API key |
| `HUNTER_API_KEY` | Optional | Hunter.io for email enrichment |
| `RESEND_API_KEY` | Optional | Resend for sending emails |
| `FROM_EMAIL` | Optional | Sender address (default: outreach@hedwig-ai.com) |
| `DATABASE_URL` | ✅ | PostgreSQL connection string |
