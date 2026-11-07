#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo 'Create the Python environment first. See README.md.' >&2
  exit 1
fi
echo 'Plant Clinic: http://localhost:8000'
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8000}"
