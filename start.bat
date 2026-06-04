@echo off
cd /d "%~dp0"
echo Starting Crypto Research Autopilot...
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
pause
