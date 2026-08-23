@echo off
setlocal enabledelayedexpansion
echo Starting DEF(kari) Development Server...
echo.

start "DEF-API" cmd /k "cd /d E:\tools\DEF && E:\tools\DEF\poc\venv\Scripts\python.exe -m uvicorn def_kari.api.main:app --host 127.0.0.1 --port 8511 --reload"

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
