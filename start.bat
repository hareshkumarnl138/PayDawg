@echo off
rem Double-click or run from Command Prompt. First run sets everything up, later runs just start the server.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -q -r requirements.txt
if not exist .env copy .env.example .env
echo.
echo PayDawg is starting. Open http://127.0.0.1:8000 in your browser. Press Ctrl+C to stop.
echo.
uvicorn app.main:app --no-proxy-headers
pause
