@echo off
title Hayeong — Ollama Reasoning LLM (port 11435)

:: CUDA targeting — RTX 3090
set CUDA_VISIBLE_DEVICES=0
set OLLAMA_NUM_GPU=99

:: Instance-specific home and port
set OLLAMA_HOME=H:\hayeong\ollama\reasoning
set OLLAMA_HOST=127.0.0.1:11435
set OLLAMA_MODELS=H:\hayeong\ollama\reasoning\models

:: Keep model loaded — never unload between calls
set OLLAMA_KEEP_ALIVE=-1

echo ─────────────────────────────────────────
echo   Hayeong Reasoning LLM
echo   Model: qwen2.5:14b-instruct-q4_K_M
echo   Port:  11435
echo   GPU:   CUDA (RTX 3090)
echo ─────────────────────────────────────────
echo.

ollama serve

pause
