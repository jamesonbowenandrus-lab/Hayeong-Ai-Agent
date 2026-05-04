@echo off
title Hayeong — Model Warmup

echo Warming up Communication LLM (llama3.2 on port 11434)...
curl -s -X POST http://localhost:11434/api/generate ^
  -H "Content-Type: application/json" ^
  -d "{\"model\": \"llama3.2:latest\", \"prompt\": \"hi\", \"stream\": false}" ^
  > nul
echo   Done.

echo Warming up Reasoning LLM (deepseek-r1 on port 11435)...
curl -s -X POST http://localhost:11435/api/generate ^
  -H "Content-Type: application/json" ^
  -d "{\"model\": \"deepseek-r1:latest\", \"prompt\": \"hi\", \"stream\": false}" ^
  > nul
echo   Done.

echo Warming up Task Agent (phi3:mini on port 11436)...
curl -s -X POST http://localhost:11436/api/generate ^
  -H "Content-Type: application/json" ^
  -d "{\"model\": \"phi3:mini\", \"prompt\": \"hi\", \"stream\": false}" ^
  > nul
echo   Done.

echo.
echo All models loaded into VRAM. Hayeong is ready.
pause
