@echo off
title Finventory Backend

REM ── Self-elevate to Administrator (required for WebView2 loopback exemption) ──
NET SESSION >nul 2>&1
IF %errorlevel% NEQ 0 (
    echo [Finventory] Requesting administrator privileges...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb runas -WorkingDirectory '%~dp0'"
    EXIT /b
)

echo [Finventory] Starting services...

REM ── Wait for Docker Desktop to be ready (up to 90 seconds) ──────────────────
set /a attempts=0
:WAIT_DOCKER
docker info >nul 2>&1
if %errorlevel% neq 0 (
    set /a attempts+=1
    if %attempts% geq 18 (
        echo [Finventory] ERROR: Docker Desktop did not start within 90 seconds.
        echo              Make sure Docker Desktop is set to start on login.
        timeout /t 10 /nobreak >nul
        exit /b 1
    )
    echo [Finventory] Waiting for Docker Desktop... (%attempts%/18)
    timeout /t 5 /nobreak >nul
    goto WAIT_DOCKER
)

echo [Finventory] Docker ready.

REM ── Allow WebView2 (Tauri) to reach localhost (Windows network isolation fix) ─
CheckNetIsolation.exe LoopbackExempt -a -n="Microsoft.Win32WebViewHost_cw5n1h2txyewy" >nul 2>&1
echo [Finventory] Network isolation exemption applied.

REM ── Start PostgreSQL and Redis containers ────────────────────────────────────
cd /d "c:\Dev Projects\FinTax App\finventory"
docker compose up -d db redis
echo [Finventory] Containers started.

REM ── Wait for PostgreSQL to accept connections ────────────────────────────────
echo [Finventory] Waiting for PostgreSQL to be ready...
timeout /t 8 /nobreak >nul

REM ── Run migrations (safe to run repeatedly — skips already-applied ones) ─────
cd /d "c:\Dev Projects\FinTax App\finventory\backend"
call "..\venv\Scripts\activate.bat"
echo [Finventory] Running migrations...
python manage.py migrate --noinput

REM ── Start Django development server ─────────────────────────────────────────
echo [Finventory] Backend running at http://localhost:8000
echo              Keep this window open while using the app.
echo              Close it to stop the backend.
echo.
python manage.py runserver

pause
