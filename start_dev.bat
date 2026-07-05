@echo off
echo Starting DEF(kari) Development Server...
echo.

start "DEF-API" cmd /k "cd /d E:\tools\DEF && E:\tools\DEF\poc\venv\Scripts\python.exe -m uvicorn def_kari.api.main:app --host 127.0.0.1 --port 8511 --reload"

timeout /t 3 /nobreak >nul

start "DEF-React" cmd /k "cd /d E:\tools\DEF\frontend && npm run dev"

echo.
echo FastAPI: http://127.0.0.1:8511
echo React:   http://localhost:3000
echo.
