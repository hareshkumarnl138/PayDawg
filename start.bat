@echo off
rem Double-click or run from Command Prompt. First run sets everything up, later runs just start the server.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Setting up PayDawg for the first time. This takes a minute or two...
  python -m venv .venv
)
if not exist .venv\Scripts\python.exe (
  echo.
  echo Could not set up Python for PayDawg. It needs Python 3.11 or newer:
  echo install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH", then run start.bat again.
  echo.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m pip install -q --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo.
  echo Note: installing the requirements did not finish. If PayDawg fails to start below, check your internet connection and run start.bat again.
)
if not exist .env copy .env.example .env >nul
echo.
echo PayDawg is starting. Console: http://127.0.0.1:8000   Pet shop: http://127.0.0.1:8000/shop
echo Live traffic (mock mode): in a second window run  .venv\Scripts\python demo_shop\simulate.py
echo Press Ctrl+C to stop.
echo.
.venv\Scripts\python.exe -m uvicorn app.main:app --no-proxy-headers
echo.
echo PayDawg has stopped. If it said the address is already in use, another PayDawg window is still open: close it and start again.
pause
