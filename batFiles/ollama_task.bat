@echo off
title Hayeong Task Agent
color 0B

echo =========================================
echo   Hayeong Task Agent
echo   Model: phi3:mini
echo   Port:  11436
echo   GPU:   CUDA (RTX 3090)
echo =========================================

set OLLAMA_HOST=127.0.0.1:11436
set CUDA_VISIBLE_DEVICES=0
set OLLAMA_NUM_GPU=99
set OLLAMA_KEEP_ALIVE=-1

ollama serve
