@echo off
rem One-time setup on Windows: a private Python environment (.venv) with Blender,
rem Molecular Nodes and the web app's packages. About 1 GB to download.
rem Needs Python 3.13 from https://www.python.org/downloads/
setlocal
cd /d "%~dp0"
rem Give this copy of Blender its own user folder, so add-ons and extensions installed in
rem the desktop Blender (for example Molecular Nodes, with its own nodebpy) are not loaded
rem in place of the tested versions in .venv.
set "BLENDER_USER_RESOURCES=%~dp0data\blender-user"

set "PY="
py -3.13 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY=py -3.13"
if not defined PY (
  python -c "import sys; sys.exit(sys.version_info[:2] != (3, 13))" >nul 2>&1
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo Python 3.13 was not found.
  echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH",
  echo then double-click this file again.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating the environment in the .venv folder ...
  %PY% -m venv .venv
  if errorlevel 1 goto failed
)

echo Installing packages. The first time downloads about 1 GB and can take 5-15 minutes ...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -c "import bpy, molecularnodes; print('Blender', bpy.app.version_string, 'and Molecular Nodes are ready.')"
if errorlevel 1 goto failed

echo.
echo Done. Double-click start-windows.bat to open the app.
pause
exit /b 0

:failed
echo.
echo Setup did not finish; the error is shown above.
echo If it mentions a long path or "No such file or directory", move this project folder to a
echo short path such as C:\rtm, delete its .venv folder, and double-click this file again.
pause
exit /b 1
