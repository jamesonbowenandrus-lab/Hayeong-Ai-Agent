@echo off
title Hayeong — Dashboard
color 0A

cd /d H:\hayeong
call H:\hayeong\.venv\Scripts\activate.bat
set PYTHONIOENCODING=utf-8

python dashboard_server.py

echo.
echo Dashboard closed.
pause
