$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
python -m uvicorn app.main:app --host 0.0.0.0 --port 8090
