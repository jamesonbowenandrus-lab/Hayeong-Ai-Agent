@echo off
title Hayeong — Voice Server

:: CUDA — RTX 3090
:: ROCm variables removed — voice server now runs on 3090 CUDA
set CUDA_VISIBLE_DEVICES=0

:: Ollama GPU routing (safety net)
set OLLAMA_NUM_GPU=99

:: Kill any existing voice server on port 8765 before starting
echo Checking for existing voice server on port 8765...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8765 ^| findstr LISTENING') do (
    echo   Killing old instance (PID %%a)...
    taskkill /PID %%a /F >nul 2>&1
)
timeout /t 1 /nobreak >nul

echo.
echo ─────────────────────────────────────────
echo   Hayeong Voice Server
echo   GPU: CUDA (RTX 3090)
echo   Port: 8765
echo ─────────────────────────────────────────
echo.

cd /d H:\hayeong

:: Activate the venv
call H:\hayeong\.venv\Scripts\activate.bat

:: Launch the voice server
python voice_server.py

:: If it exits unexpectedly, pause so you can read the error
echo.
echo Voice server stopped.
pause
