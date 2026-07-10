@echo off
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d E:\tools\DEF
E:\tools\DEF\poc\venv\Scripts\python.exe -m streamlit run def_kari/app.py --server.port 8510 --server.headless true
pause
