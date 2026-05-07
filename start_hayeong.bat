@echo off
title Hayeong — Starting Up
color 0A

echo.
echo ╔══════════════════════════════════════════════════════╗
echo ║              HAYEONG STARTUP SEQUENCE               ║
echo ╚══════════════════════════════════════════════════════╝
echo.

cd /d H:\hayeong
call H:\hayeong\venv\Scripts\activate.bat

:: ── STEP 1: Start Communication LLM ──
echo [1/4] Starting Communication LLM (port 11434)...
start "Hayeong — Communication LLM" /min H:\hayeong\Brain\ollama_communication.bat
call :wait_for_ollama 11434 "Communication LLM"
if errorlevel 1 goto :startup_failed
echo.

:: ── STEP 2: Start Reasoning LLM ──
echo [2/4] Starting Reasoning LLM (port 11435)...
start "Hayeong — Reasoning LLM" /min H:\hayeong\Brain\ollama_reasoning.bat
call :wait_for_ollama 11435 "Reasoning LLM"
if errorlevel 1 goto :startup_failed
echo.

:: ── STEP 3: Start Voice Server (optional) ──
echo [3/4] Starting Voice Server...
start "Hayeong — Voice Server" /min H:\hayeong\Toolbox\voice\voice_server.bat
call :wait_for_voice_server
if errorlevel 1 (
    echo     WARNING -- Voice server did not respond. Starting anyway.
    echo     Voice output may not work this session.
    echo.
)
echo.

:: ── STEP 4: Start Hayeong ──
echo [4/4] Starting Hayeong...
echo.
echo ╔══════════════════════════════════════════════════════╗
echo ║                  HAYEONG IS LIVE                    ║
echo ╚══════════════════════════════════════════════════════╝
echo.

python main.py %*

echo.
echo Hayeong has stopped. Press any key to close.
pause
exit /b 0


:: ─────────────────────────────────────────────
:: SUBROUTINES
:: ─────────────────────────────────────────────

:wait_for_ollama
setlocal
set port=%1
set name=%2
set /a attempts=0
set /a max_attempts=30

:ollama_poll
timeout /t 2 /nobreak >nul
curl -s -f http://localhost:%port%/ >nul 2>&1
if not errorlevel 1 (
    echo     %name% is ready on port %port%
    endlocal
    exit /b 0
)
set /a attempts+=1
if %attempts% geq %max_attempts% (
    echo     FAILED -- %name% did not start within 60 seconds
    endlocal
    exit /b 1
)
echo     Waiting for %name%... (%attempts%/%max_attempts%)
goto :ollama_poll


:wait_for_voice_server
setlocal
set /a attempts=0
set /a max_attempts=15

:voice_poll
timeout /t 2 /nobreak >nul
curl -s -f http://localhost:8765/health >nul 2>&1
if not errorlevel 1 (
    echo     Voice server is ready on port 8765
    endlocal
    exit /b 0
)
set /a attempts+=1
if %attempts% geq %max_attempts% (
    echo     Voice server did not respond in 30 seconds
    endlocal
    exit /b 1
)
echo     Waiting for voice server... (%attempts%/%max_attempts%)
goto :voice_poll


:startup_failed
echo.
echo ╔══════════════════════════════════════════════════════╗
echo ║              STARTUP FAILED                         ║
echo ╚══════════════════════════════════════════════════════╝
pause
exit /b 1
