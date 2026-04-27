@echo off
title Hayeong — Dashboard
color 0A

cd /d H:\hayeong
call H:\hayeong\.venv\Scripts\activate.bat

python dashboard.py

echo.
echo Dashboard closed.
pause
