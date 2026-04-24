@echo off
title Hayeong — Model Warmup

echo Warming up Communication LLM (7b on port 11434)...
curl -s -X POST http://localhost:11434/api/generate ^
  -H "Content-Type: application/json" ^
  -d "{\"model\": \"qwen2.5:7b-instruct-q4_K_M\", \"prompt\": \"hi\", \"stream\": false}" ^
  > nul
echo   Done.

echo Warming up Reasoning LLM (14b on port 11435)...
curl -s -X POST http://localhost:11435/api/generate ^
  -H "Content-Type: application/json" ^
  -d "{\"model\": \"qwen2.5:14b-instruct-q4_K_M\", \"prompt\": \"hi\", \"stream\": false}" ^
  > nul
echo   Done.

echo.
echo Both models loaded into VRAM. Hayeong is ready.
pause
