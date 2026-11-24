#!/usr/bin/env bash
# Start CloudGuard locally on Linux/macOS (backend in background, frontend in foreground).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

cd "$ROOT/backend"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements-dev.txt
fi
[ -f .env ] || echo "WARNING: backend/.env missing - copy .env.example and set DATABASE_URL / JWT_SECRET_KEY" >&2
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!
trap 'kill $BACKEND_PID' EXIT

cd "$ROOT/frontend"
[ -d node_modules ] || npm install
echo "CloudGuard: http://localhost:5173   API docs: http://127.0.0.1:8000/docs"
npm run dev
