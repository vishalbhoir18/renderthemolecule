@echo off
rem Starts Render the Molecule on this PC at http://localhost:7860 and opens it in the browser.
rem Close this window (or press Ctrl+C) to stop it. Run setup-windows.bat once before.
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup-windows.bat first.
  pause
  exit /b 1
)

echo Starting Render the Molecule at http://localhost:7860 ...
echo Changes to the Python files in the app folder restart it by themselves;
echo after changes to the page, refresh the browser.
echo Close this window (or press Ctrl+C) to stop it.
echo.
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 6; Start-Process 'http://localhost:7860'"
".venv\Scripts\python.exe" -m uvicorn --factory app.main:create_app --port 7860 --reload --reload-dir app
pause
