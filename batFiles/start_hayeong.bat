@echo off
setlocal

set HAYEONG_DIR=H:\hayeong
set PYTHON=%HAYEONG_DIR%\.venv\Scripts\python.exe
set OLLAMA=C:\Users\James\AppData\Local\Programs\Ollama\ollama.exe

echo Starting Ollama...
start "" "%OLLAMA%" serve
timeout /t 3 /nobreak >nul

echo Starting Hayeong watchdog (manages brain lifetime)...
start "Hayeong — Watchdog" cmd /k "cd /d %HAYEONG_DIR% && %PYTHON% watchdog.py"

timeout /t 5 /nobreak >nul

echo Starting text interface...
start "Hayeong — Text" cmd /k "cd /d %HAYEONG_DIR% && %PYTHON% text_io.py"

echo Starting voice interface (fails safely if Kokoro unavailable)...
start "Hayeong — Voice" cmd /k "cd /d %HAYEONG_DIR% && %PYTHON% voice_io.py"

echo.
echo All processes launched.
echo   Watchdog window : supervises brain, restarts on crash, acts on recovery notes
echo   Text window     : type here to talk to Hayeong
echo   Voice window    : Kokoro TTS + Whisper STT (safe to close if not needed)
echo.
echo If voice window crashes, watchdog and text are unaffected.
echo If brain crashes, watchdog restarts it and notifies James automatically.
