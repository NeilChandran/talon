# Open Talon in your browser

## One command (recommended)

Open **Terminal** and run:

```bash
/Users/neil/Desktop/talon/hedwig-outreach/scripts/start.sh
```

Wait until you see `Ready` and `Uvicorn running`.

Then open: **http://localhost:3000/workspace**

---

## Why not Desktop?

The project on **Desktop** often breaks `npm run dev` (iCloud timeouts). The script copies everything to `~/Projects/talon-outreach` and runs from there.

---

## Manual (two terminals)

**Terminal 1 — backend**
```bash
cd ~/Projects/talon-outreach/backend
source venv/bin/activate
pip install greenlet fastapi uvicorn httpx anthropic python-dotenv sqlalchemy aiosqlite python-multipart websockets pydantic
python init_db.py
uvicorn main:app --reload --port 8000
```

**Terminal 2 — frontend**
```bash
cd ~/Projects/talon-outreach/frontend
npm install
npm run dev
```

Open: **http://localhost:3000/workspace**

---

## Check it works

| URL | Should show |
|-----|-------------|
| http://localhost:8000/health | `{"status":"ok"}` |
| http://localhost:3000/workspace | Talon UI with sidebar |

If the page is blank or errors, the **backend** terminal must be running (port 8000).
