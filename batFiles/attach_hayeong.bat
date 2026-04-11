@echo off
wsl -d Ubuntu-24.04 tmux has-session -t hayeong 2>nul
if %errorlevel% == 0 (
    wsl -d Ubuntu-24.04 tmux attach -t hayeong
) else (
    echo Hayeong is not running. Use start_hayeong.bat first.
    pause
)