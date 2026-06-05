# Can't open Talon / Workspace?

## Symptom

`npm run dev` fails with:

```
Error: ETIMEDOUT: connection timed out, read
```

or Next.js never shows "Ready".

## Cause

The repo is on **Desktop**, which macOS often syncs via **iCloud**. Node tries to read thousands of files in `node_modules` and times out on cloud-stub files.

## Fix (pick one)

### Option A — Run from a local copy (fastest)

```bash
chmod +x hedwig-outreach/scripts/start-local.sh
./hedwig-outreach/scripts/start-local.sh
```

Then in **two terminals**:

```bash
cd ~/Projects/talon-outreach/backend
source venv/bin/activate
uvicorn main:app --reload
```

```bash
cd ~/Projects/talon-outreach/frontend
npm run dev
```

Open: **http://localhost:3000/workspace**

### Option B — Move the project off Desktop

1. Move the whole `talon` folder to `~/Projects/talon`
2. In the new location:

```bash
cd ~/Projects/talon/hedwig-outreach/frontend
rm -rf node_modules .next
npm install
npm run dev
```

### Option C — Keep on Desktop but force download

1. Finder → Desktop → `talon` → right-click → **Download Now** (if iCloud)
2. Wait until the cloud icon disappears from files
3. `cd hedwig-outreach/frontend && rm -rf node_modules .next && npm install`

## LinkedIn connection keeps failing?

1. **Prefer browser login** — Settings → **Sign in with LinkedIn** (saves all cookies, not just `li_at`).
2. After connecting, click **Test API** — must show green before launching sequences.
3. Restart backend after updating code: `pip install -r requirements.txt` (needs `websockets`).
4. Manual cookies: paste **li_at** + **JSESSIONID** from Chrome DevTools → Application → Cookies → `linkedin.com`.
5. If you see **403**: disconnect, browser-login again (session rotated).
6. If you see **weekly limit**: LinkedIn cap (~100 invites/week) — wait or use another account.

## Explore / Origami scrapers

1. Install Playwright browsers once:
   ```bash
   cd backend && pip install playwright && playwright install chromium
   ```
2. **Google Maps** — Playwright sidebar scrape (no login).
3. **LinkedIn** — company search via CDP Chrome; **Jobs** uses same session for `/jobs/search/`.
4. **Crunchbase** — Playwright on discover/search (may hit login wall on some IPs).
5. **Indeed** — Playwright job listings → hiring companies.
6. **Shopify** — runs after other scrapers; HTTP check on `/admin/auth/login` + `window.Shopify` in HTML.
7. **News** — TechCrunch + BusinessWire Playwright search.
8. Connect LinkedIn in **Settings** first for LinkedIn company + jobs scrapers.

## Backend not running?

Workspace needs the API on port **8000**. Connect LinkedIn under **Settings** first.

```bash
cd hedwig-outreach/backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add keys
docker compose up postgres -d   # if using Postgres
python init_db.py
uvicorn main:app --reload
```

## Correct URL

| Page | URL |
|------|-----|
| Workspace | http://localhost:3000/workspace |
| Settings (LinkedIn) | http://localhost:3000/settings |

Not `file://` — must use `npm run dev`.
