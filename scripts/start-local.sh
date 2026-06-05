#!/usr/bin/env bash
# Run Talon OFF Desktop — iCloud-synced Desktop causes ETIMEDOUT when Node reads files.
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${TALON_DEV_DIR:-$HOME/Projects/talon-outreach}"

echo "→ Copying project to $DEST (skips .git, node_modules, .next, venv)..."
mkdir -p "$DEST"
rsync -a --delete \
  --exclude node_modules \
  --exclude .next \
  --exclude venv \
  --exclude __pycache__ \
  --exclude .git \
  --exclude '.linkedin_session.json' \
  "$SRC/" "$DEST/"

echo "→ Installing frontend dependencies..."
cd "$DEST/frontend"
npm install

echo "→ Backend venv..."
cd "$DEST/backend"
if [[ ! -d venv ]]; then
  python3 -m venv venv
fi
# shellcheck source=/dev/null
source venv/bin/activate
pip install -q -r requirements.txt

if [[ ! -f .env ]]; then
  if [[ -f "$SRC/.env" ]]; then
    cp "$SRC/.env" .env
  elif [[ -f "$SRC/.env.example" ]]; then
    cp "$SRC/.env.example" .env
    echo "   Created .env from example — add ANTHROPIC_API_KEY and DATABASE_URL"
  fi
fi

echo "→ Database tables..."
python init_db.py 2>/dev/null || true

echo ""
echo "════════════════════════════════════════════════════════"
echo "  Talon dev (local copy — not iCloud Desktop)"
echo "  Open: http://localhost:3000/workspace"
echo "════════════════════════════════════════════════════════"
echo ""
echo "  Terminal 1: cd $DEST/backend && source venv/bin/activate && uvicorn main:app --reload"
echo "  Terminal 2: cd $DEST/frontend && npm run dev"
echo ""

if [[ "${1:-}" == "--run" ]]; then
  echo "Starting backend + frontend..."
  cd "$DEST/backend" && source venv/bin/activate && uvicorn main:app --reload --port 8000 &
  sleep 2
  cd "$DEST/frontend" && npm run dev
fi
