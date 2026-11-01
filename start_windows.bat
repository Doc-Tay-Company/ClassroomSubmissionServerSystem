@echo off
setlocal
cd /d "%~dp0"
set PYTHONNOUSERSITE=1
set PYTHONDONTWRITEBYTECODE=1
if not exist ".venv\Scripts\python.exe" (
  echo [INFO] Run setup_windows.bat once before starting the server.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m app.configure_admin
if errorlevel 1 (
  echo [ERROR] Admin configuration failed. The server was not started.
  pause
  exit /b 1
)

echo [INFO] Starting server on http://127.0.0.1:8080 ...
start "" /b ".venv\Scripts\python.exe" run_server.py

echo [INFO] Waiting for the server, then opening the login page...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ready=$false; 1..30 | ForEach-Object { try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8080/health -TimeoutSec 1 | Out-Null; $ready=$true; break } catch {}; Start-Sleep -Milliseconds 500 }; if ($ready) { Start-Process 'http://127.0.0.1:8080/login' } else { exit 1 }"
if errorlevel 1 echo [WARN] Server did not respond within 15 seconds. Open http://127.0.0.1:8080/login manually.
pause
