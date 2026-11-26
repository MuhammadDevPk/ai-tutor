#!/usr/bin/env bash
set -e

cleanup() {
  echo ""
  echo "Shutting down servers..."
  kill $(jobs -p) 2>/dev/null || true
  exit 0
}
trap cleanup SIGINT SIGTERM EXIT

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

echo "=== Starting AI Tutor ==="
echo "1. API Backend: http://127.0.0.1:8000 (Docs: http://127.0.0.1:8000/docs)"
(cd apps/api && .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000) &

echo "2. Next.js Web: http://localhost:3000"
(cd apps/web && pnpm dev) &

echo "3. LiveKit Voice Agent Worker"
(cd apps/api && .venv/bin/python -m app.worker dev) &

echo ""
echo "All services launched. Press Ctrl+C to stop all."
echo ""

wait
