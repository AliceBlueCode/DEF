@echo off
echo Starting DEF(kari) with Public (Cloudflare Tunnel) Port...
echo.

start "DEF-API-Dual" cmd /k "cd /d E:\tools\DEF && E:\tools\DEF\poc\venv\Scripts\python.exe -m def_kari.api.dual_run --local-port 8511 --public-port 8512 --cloudflare-tunnel"

timeout /t 3 /nobreak >nul

start "DEF-React" cmd /k "cd /d E:\tools\DEF\frontend && npm run dev"

echo.
echo FastAPI (local, full access):    http://127.0.0.1:8511
echo FastAPI (public, session only):  http://0.0.0.0:8512
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
