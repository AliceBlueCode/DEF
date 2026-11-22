@echo off
setlocal enabledelayedexpansion
REM Keep this file CRLF (see .gitattributes). With LF line endings cmd cannot find
REM the labels below ("goto wait_backend" fails) and the frontend never starts
REM (2026-11-22).
REM Each step is logged to %TEMP%\def_launcher.log with the time.
set "DEF_LAUNCH_LOG=%TEMP%\def_launcher.log"
call :log "start_def_public.bat start"
echo Starting DEF(kari) with Public (Cloudflare Tunnel) Port...
echo.

REM Every command below is found through PATH. If one is missing, stop here
REM instead of skipping the port check and the health wait silently
REM (2026-11-22: a PATH starting with ";" made cmd find no command at all).
for %%C in (curl timeout netstat findstr npm) do (
    where %%C >nul 2>&1
    if errorlevel 1 (
        echo Command not found: %%C -- check the PATH environment variable.
        call :log "command not found: %%C"
        pause
        exit /b 1
    )
)
call :log "commands found"

REM Refuse to start while an old DEF still holds the ports. Otherwise the new
REM backend dies with error 10048 and the health check below is answered by the
REM old process, so the old code keeps running unnoticed (2026-11-15).
for %%P in (8511 8512) do (
    netstat -ano | findstr /R /C:"127\.0\.0\.1:%%P .*LISTENING" >nul
    if not errorlevel 1 (
        echo Port %%P is already in use -- an old DEF may still be running.
        echo Close the old DEF windows, or stop the process shown below, then run this again.
        netstat -ano | findstr /R /C:"127\.0\.0\.1:%%P .*LISTENING"
        call :log "port %%P already in use"
        pause
        exit /b 1
    )
)

start "DEF-API-Dual" cmd /k "cd /d E:\tools\DEF && E:\tools\DEF\venv\Scripts\python.exe -m def_kari.api.dual_run --local-port 8511 --public-port 8512 --cloudflare-tunnel"
call :log "backend window started"

echo Waiting for backend (http://127.0.0.1:8511/api/health) to respond...
set DEF_HEALTH_WAIT=0
:wait_backend
REM -m 5: do not hang while the backend is still starting up
curl -sf -m 5 http://127.0.0.1:8511/api/health >nul 2>&1
if errorlevel 1 (
    set /a DEF_HEALTH_WAIT+=1
    set /a DEF_HEALTH_MOD=DEF_HEALTH_WAIT %% 10
    if !DEF_HEALTH_MOD! EQU 0 call :log "waiting for backend: !DEF_HEALTH_WAIT!"
    if !DEF_HEALTH_WAIT! GEQ 60 (
        echo Backend did not respond within 60s -- starting frontend anyway.
        call :log "backend did not respond within 60 tries"
        goto start_frontend
    )
    timeout /t 1 /nobreak >nul
    goto wait_backend
)
echo Backend is up.
call :log "backend is up after !DEF_HEALTH_WAIT! waits"

:start_frontend
start "DEF-React" cmd /k "cd /d E:\tools\DEF\frontend && npm run dev"
call :log "frontend window started"

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
call :log "start_def_public.bat done"
exit /b 0

:log
echo [%date% %time%] %~1>> "%DEF_LAUNCH_LOG%"
exit /b 0
