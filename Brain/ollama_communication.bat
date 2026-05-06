@echo off
title Hayeong — Ollama Communication LLM (port 11434)

:: CUDA targeting — RTX 3090 only, exclude AMD ROCm
set CUDA_VISIBLE_DEVICES=0
set OLLAMA_NUM_GPU=99
set ROCR_VISIBLE_DEVICES=
set HIP_VISIBLE_DEVICES=

:: Instance-specific home and port
set OLLAMA_HOME=H:\hayeong\ollama\communication
set OLLAMA_HOST=127.0.0.1:11434
set OLLAMA_MODELS=H:\AI\ollama\models

:: Keep model loaded — never unload between calls
set OLLAMA_KEEP_ALIVE=-1

echo ─────────────────────────────────────────
echo   Hayeong Communication LLM
echo   Model: llama3.2:latest
echo   Port:  11434
echo   GPU:   CUDA (RTX 3090)
echo ─────────────────────────────────────────
echo.

ollama serve

pause
