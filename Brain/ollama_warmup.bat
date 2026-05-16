@echo off
title Hayeong — Model Warmup

echo Warming up Presence LLM (qwen2.5:32b on port 11435)...
curl -s -X POST http://localhost:11435/api/generate ^
  -H "Content-Type: application/json" ^
  -d "{\"model\": \"qwen2.5:32b-instruct-q4_K_M\", \"prompt\": \"hi\", \"stream\": false}" ^
  > nul
echo   Done.

echo.
echo Qwen 32b loaded into VRAM. Hayeong is ready.
pause
