@echo off
title Hayeong - Starting Up
color 0A

echo.
echo +==============================================+
echo ^|        HAYEONG STARTUP SEQUENCE             ^|
echo +==============================================+
echo.

cd /d H:\hayeong
call H:\hayeong\.venv\Scripts\activate.bat

:: STEP 1: Start Presence LLM
echo [1/4] Starting Presence LLM (port 11435)...
start "Hayeong - Presence LLM" /min H:\hayeong\brain\ollama_reasoning.bat
call :wait_for_ollama 11435 Presence
if errorlevel 1 goto :startup_failed
echo.

:: STEP 2: Voice - skipped for now
echo [2/4] Voice server - skipped for now.
echo.

:: STEP 3: Start Dashboard
echo [3/4] Starting Dashboard...
start "Hayeong - Dashboard" /min cmd /c "cd /d H:\hayeong && call H:\hayeong\.venv\Scripts\activate.bat && python Dashboard\dashboard_server.py"
call :wait_for_dashboard
if errorlevel 1 (
    echo     WARNING - Dashboard did not respond. Continuing without it.
    echo.
) else (
    echo     Dashboard ready.
    echo.
)

:: STEP 4: Start Hayeong
echo [4/4] Starting Hayeong...
echo.
echo +==============================================+
echo ^|            HAYEONG IS LIVE                  ^|
echo +==============================================+
echo.

python main.py %*

echo.
echo Hayeong has stopped. Press any key to close.
pause
exit /b 0


:: -------------------------------------------
:: SUBROUTINES
:: -------------------------------------------

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
    echo     %name% LLM is ready on port %port%
    endlocal
    exit /b 0
)
set /a attempts+=1
if %attempts% geq %max_attempts% (
    echo     FAILED - %name% LLM did not start within 60 seconds
    endlocal
    exit /b 1
)
echo     Waiting for %name%... (%attempts%/%max_attempts%)
goto :ollama_poll


:wait_for_dashboard
setlocal
set /a attempts=0
set /a max_attempts=10

:dashboard_poll
timeout /t 2 /nobreak >nul
curl -s -f http://localhost:8080/health >nul 2>&1
if not errorlevel 1 (
    endlocal
    exit /b 0
)
set /a attempts+=1
if %attempts% geq %max_attempts% (
    endlocal
    exit /b 1
)
echo     Waiting for dashboard... (%attempts%/%max_attempts%)
goto :dashboard_poll


:startup_failed
echo.
echo +==============================================+
echo ^|           STARTUP FAILED                    ^|
echo +==============================================+
pause
exit /b 1
