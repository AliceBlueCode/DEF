@echo off
setlocal enabledelayedexpansion
echo Starting DEF(kari) with Public (Cloudflare Tunnel) Port...
echo.

start "DEF-API-Dual" cmd /k "cd /d E:\tools\DEF && E:\tools\DEF\poc\venv\Scripts\python.exe -m def_kari.api.dual_run --local-port 8511 --public-port 8512 --cloudflare-tunnel"

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
echo FastAPI (local, full access):    http://127.0.0.1:8511
echo FastAPI (public, session only):  http://127.0.0.1:8512 (proxied via cloudflared)
echo React:                           http://localhost:3000
echo.
echo cloudflared (Quick Tunnel) is auto-launched by dual_run.py. The generated
echo URL is printed in the DEF-API-Dual window and also auto-filled in the
echo session screen's invite panel.
echo To use a fixed domain (Named Tunnel) instead, remove --cloudflare-tunnel
echo above and run "cloudflared tunnel run ^<tunnel-name^>" manually.
echo In that case, the ingress in config.yml must point only at port 8512
echo (do not expose port 8511 -- full access, API keys, etc.).
echo.
