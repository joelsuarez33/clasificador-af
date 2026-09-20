#!/usr/bin/env bash
# Levanta la API con el Python del venv. Host/puerto desde .env (API_HOST / API_PORT).
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/python -m app.main
