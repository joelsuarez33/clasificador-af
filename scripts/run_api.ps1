# Levanta la API con el Python del venv. Host/puerto desde .env (API_HOST / API_PORT).
$ErrorActionPreference = "Stop"
Set-Location -Path (Join-Path $PSScriptRoot "..")
& ".\.venv\Scripts\python.exe" -m app.main
exit $LASTEXITCODE
