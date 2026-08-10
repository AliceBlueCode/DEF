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
echo cloudflared（Quick Tunnel）は dual_run.py が自動起動します。発行されたURLは
echo DEF-API-Dual ウィンドウのログに出るほか、セッション画面の招待欄にも自動表示されます。
echo 固定ドメイン（Named Tunnel）を使う場合は --cloudflare-tunnel を外し、
echo cloudflared tunnel run ^<tunnel-name^> を別途手動で起動してください。
echo その場合 config.yml の ingress は 8512 番ポートだけを指定すること
echo （8511=フル機能・APIキー等を外部公開に含めないこと）。
echo.
