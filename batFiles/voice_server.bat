@echo off
title Hayeong — Voice Server

:: ─────────────────────────────────────────────
:: ROCm GPU environment — MUST be set before Python starts.
:: HSA initializes at the OS level — setting these inside Python is too late.
:: RX 7900 XTX is gfx1100 — the override tells ROCm to treat it as supported.
:: ─────────────────────────────────────────────
set HSA_OVERRIDE_GFX_VERSION=11.0.0
set ROCR_VISIBLE_DEVICES=0
set HIP_VISIBLE_DEVICES=0

:: Ollama GPU routing (already set system-wide but set here as safety net)
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
echo   GPU: ROCm (RX 7900 XTX)
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
