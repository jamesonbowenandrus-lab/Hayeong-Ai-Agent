@echo off
title Hayeong — Shutting Down

echo.
echo Stopping Hayeong...
echo.

:: Stop Hayeong main process
:: main.py handles SIGINT gracefully -- saves memory and state before exit
taskkill /FI "WINDOWTITLE eq Hayeong — Starting Up" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Hayeong*" /F >nul 2>&1

timeout /t 2 /nobreak >nul

:: Stop supporting services
echo Stopping voice server...
taskkill /FI "WINDOWTITLE eq Hayeong — Voice Server" /F >nul 2>&1

echo Stopping Ollama instances...
taskkill /FI "WINDOWTITLE eq Hayeong — Communication LLM*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Hayeong — Reasoning LLM*" /F >nul 2>&1

echo.
echo Hayeong stopped.
pause
