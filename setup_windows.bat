@echo off
setlocal
cd /d "%~dp0"
set PYTHONNOUSERSITE=1
set PIP_DISABLE_PIP_VERSION_CHECK=1
set PIP_NO_PYTHON_VERSION_WARNING=1

if exist ".venv\Scripts\python.exe" goto install_deps

py --version >nul 2>&1
if not errorlevel 1 (
  set "PY_LAUNCH=py"
  goto create_venv
)
python --version >nul 2>&1
if not errorlevel 1 (
  set "PY_LAUNCH=python"
  goto create_venv
)
echo [ERROR] Python was not found. Install a Python version approved by your organization.
pause
exit /b 1

:create_venv
echo [INFO] Creating a virtual environment inside this project.
%PY_LAUNCH% -m venv .venv
if errorlevel 1 (
  echo [ERROR] Could not create .venv. Windows policy may be blocking Python.
  echo Contact IT; do not disable Device Guard or Application Control.
  pause
  exit /b 1
)

:install_deps
echo [INFO] Installing the only external dependency (Jinja2) inside .venv.
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] Dependency installation failed. Check network/package access or ask IT for an approved wheel/source.
  pause
  exit /b 1
)
echo.
echo [OK] Environment ready. Run start_windows.bat next.
pause
