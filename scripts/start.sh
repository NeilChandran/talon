#!/usr/bin/env bash
# Start Talon — copies off iCloud Desktop, then runs frontend + backend.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$HOME/Projects/talon-outreach"

echo "→ Syncing to $RUN (avoids iCloud Desktop timeouts)..."
mkdir -p "$RUN"
rsync -a --delete \
  --exclude node_modules --exclude .next --exclude venv --exclude .git \
  --exclude '__pycache__' --exclude 'backend/talon.db' \
  "$ROOT/" "$RUN/"

echo "→ Backend..."
cd "$RUN/backend"
if [[ ! -d venv ]]; then python3 -m venv venv; fi
source venv/bin/activate
pip install -q -U pip
pip install -q fastapi uvicorn httpx anthropic python-dotenv greenlet \
  "pydantic>=2.10" "sqlalchemy>=2.0" aiosqlite python-multipart websockets playwright \
  celery redis
playwright install chromium 2>/dev/null || true

export DATABASE_URL="${DATABASE_URL:-sqlite+aiosqlite:///$RUN/backend/talon.db}"
# Celery only when Redis is actually running (otherwise searches never execute)
if ! command -v redis-cli >/dev/null 2>&1 || ! redis-cli ping >/dev/null 2>&1; then
  unset REDIS_URL
fi
python init_db.py 2>/dev/null || true

echo "→ Frontend..."
cd "$RUN/frontend"
[[ -d node_modules ]] || npm install
# Clear stale Next cache so UI changes (logo, styles) always show
rm -rf .next

echo ""
echo "══════════════════════════════════════════════"
echo "  Open in browser: http://localhost:3000"
echo "  Backend health:  http://localhost:8000/health"
echo "══════════════════════════════════════════════"
echo ""
echo "Starting servers (Ctrl+C to stop both)..."

trap 'kill 0' EXIT
cd "$RUN/backend" && source venv/bin/activate && uvicorn main:app --reload --port 8000 &
sleep 2
cd "$RUN/frontend" && npm run dev
