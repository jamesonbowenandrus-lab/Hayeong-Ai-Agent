@echo off
title Hayeong — Voice Client

:: ROCm env vars — set here as a safety net for any indirect GPU imports
set HSA_OVERRIDE_GFX_VERSION=11.0.0
set ROCR_VISIBLE_DEVICES=0

echo.
echo ─────────────────────────────────────────
echo   Hayeong Voice Client
echo   Connecting to voice server...
echo ─────────────────────────────────────────
echo.

cd /d H:\hayeong

:: Activate the venv
call H:\hayeong\.venv\Scripts\activate.bat

:: Small delay — give the voice server a moment if Hayeong just launched
timeout /t 2 /nobreak >nul

:: Launch the local voice client
python voice_client_local.py

:: If it exits (F9 or Ctrl+C), pause so you can read any error messages
echo.
echo Voice client closed.
pause