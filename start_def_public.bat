@echo off
echo Starting DEF(kari) with Public (Cloudflare Tunnel) Port...
echo.

start "DEF-API-Dual" cmd /k "cd /d E:\tools\DEF && E:\tools\DEF\poc\venv\Scripts\python.exe -m def_kari.api.dual_run --local-port 8511 --public-port 8512"

timeout /t 3 /nobreak >nul

start "DEF-React" cmd /k "cd /d E:\tools\DEF\frontend && npm run dev"

echo.
echo FastAPI (local, full access):    http://127.0.0.1:8511
echo FastAPI (public, session only):  http://0.0.0.0:8512
echo React:                           http://localhost:3000
echo.
echo Cloudflare Tunnel の config.yml では 8512 番ポートだけを ingress に指定すること。
echo 8511（フル機能・APIキー等）を外部公開に含めないこと。
echo.
