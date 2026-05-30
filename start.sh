#!/bin/bash
# Start Hedwig backend + frontend
# node_modules live in ~/Library/Caches/hedwig-frontend/node_modules (not in iCloud)
# NODE_PATH lets Node + Next find them without a symlink in the project dir

NM_CACHE="$HOME/Library/Caches/hedwig-frontend/node_modules"
NODE20="/opt/homebrew/Cellar/node@20/20.20.2/bin/node"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$SCRIPT_DIR/backend"
FRONTEND="$SCRIPT_DIR/frontend"

# Kill any existing processes on these ports
lsof -ti :8000 | xargs kill -9 2>/dev/null || true
lsof -ti :3000 | xargs kill -9 2>/dev/null || true
pkill -f "next-server\|next dev" 2>/dev/null || true
sleep 1

echo "Starting backend (FastAPI)..."
cd "$BACKEND"
source venv/bin/activate 2>/dev/null || source .venv/bin/activate 2>/dev/null || true
uvicorn main:app --host 0.0.0.0 --port 8000 --reload > /tmp/hedwig-backend.log 2>&1 &
echo "  Backend PID: $! → log: /tmp/hedwig-backend.log"

echo "Starting frontend (Next.js, Node 20)..."
cd "$FRONTEND"
export NODE_PATH="$NM_CACHE"
NEXT_TELEMETRY_DISABLED=1 "$NODE20" "$NM_CACHE/.bin/next" dev > /tmp/hedwig-frontend.log 2>&1 &
FE_PID=$!
echo "  Frontend PID: $FE_PID → log: /tmp/hedwig-frontend.log"

echo ""
echo "Waiting for frontend to be ready..."
until grep -q "Ready" /tmp/hedwig-frontend.log 2>/dev/null; do
    printf "."
    sleep 3
done
echo ""
echo ""
grep "Ready" /tmp/hedwig-frontend.log | tail -1

echo ""
echo "  Backend:  http://localhost:8000"
echo "  Frontend: http://localhost:3000"
echo ""
echo "TIP: Ctrl+C to stop watching logs. Servers keep running."
echo "     tail -f /tmp/hedwig-frontend.log  to watch frontend"
echo "     tail -f /tmp/hedwig-backend.log   to watch backend"
