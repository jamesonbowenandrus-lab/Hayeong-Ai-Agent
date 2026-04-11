@echo off
echo Starting Ollama...
start "" "C:\Users\James\AppData\Local\Programs\Ollama\ollama.exe" serve
timeout /t 3 /nobreak >nul
echo Starting Hayeong...
wsl -d Ubuntu-24.04 tmux has-session -t hayeong 2>nul
if %errorlevel% == 0 (
    echo Hayeong already running - attaching...
    wsl -d Ubuntu-24.04 tmux attach -t hayeong
) else (
    echo Creating new session...
    wsl -d Ubuntu-24.04 tmux new-session -d -s hayeong
    wsl -d Ubuntu-24.04 tmux send-keys -t hayeong "powershell.exe" Enter
    timeout /t 2 /nobreak >nul
    wsl -d Ubuntu-24.04 tmux send-keys -t hayeong "cd H:\\hayeong" Enter
    wsl -d Ubuntu-24.04 tmux send-keys -t hayeong "H:\\hayeong\\.venv\\Scripts\\Activate.ps1" Enter
    wsl -d Ubuntu-24.04 tmux send-keys -t hayeong "python main.py --text" Enter
    echo Hayeong started - attaching...
    wsl -d Ubuntu-24.04 tmux attach -t hayeong
)