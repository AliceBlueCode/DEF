@echo off
setlocal enabledelayedexpansion
echo Starting DEF(kari) Development Server...
echo.

REM Refuse to start while an old DEF still holds the ports. Otherwise the new
REM backend dies with error 10048 and the health check below is answered by the
REM old process, so the old code keeps running unnoticed (2026-11-15).
for %%P in (8511) do (
    netstat -ano | findstr /R /C:"127\.0\.0\.1:%%P .*LISTENING" >nul
    if not errorlevel 1 (
        echo Port %%P is already in use -- an old DEF may still be running.
        echo Close the old DEF windows, or stop the process shown below, then run this again.
        netstat -ano | findstr /R /C:"127\.0\.0\.1:%%P .*LISTENING"
        pause
        exit /b 1
    )
)

start "DEF-API" cmd /k "cd /d E:\tools\DEF && E:\tools\DEF\venv\Scripts\python.exe -m uvicorn def_kari.api.main:app --host 127.0.0.1 --port 8511 --reload"

echo Waiting for backend (http://127.0.0.1:8511/api/health) to respond...
set DEF_HEALTH_WAIT=0
:wait_backend
curl -sf http://127.0.0.1:8511/api/health >nul 2>&1
if errorlevel 1 (
    set /a DEF_HEALTH_WAIT+=1
    if !DEF_HEALTH_WAIT! GEQ 60 (
        echo Backend did not respond within 60s -- starting frontend anyway.
        goto start_frontend
    )
    timeout /t 1 /nobreak >nul
    goto wait_backend
)
echo Backend is up.

:start_frontend
start "DEF-React" cmd /k "cd /d E:\tools\DEF\frontend && npm run dev"

echo.
echo FastAPI: http://127.0.0.1:8511
echo React:   http://localhost:3000
echo.
