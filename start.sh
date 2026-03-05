#!/usr/bin/env bash
set -euo pipefail

uvicorn app.main:app --host 0.0.0.0 --port 8000 &
API_PID=$!

cleanup() {
  kill "$API_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

python - <<'PY'
import time
import urllib.request

url = "http://localhost:8000/health"
for _ in range(40):
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            if response.status == 200:
                break
    except Exception:
        time.sleep(0.25)
else:
    raise SystemExit("API did not become ready on http://localhost:8000")
PY

export NICKEL_API_BASE_URL="${NICKEL_API_BASE_URL:-http://localhost:8000}"
python -m cli.main
