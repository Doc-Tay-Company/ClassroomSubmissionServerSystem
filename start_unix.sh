#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo "No project virtual environment found. Follow README.md first-run instructions." >&2
  exit 1
fi
exec .venv/bin/python run_server.py
