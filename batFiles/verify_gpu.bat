@echo off
title Hayeong — GPU Verification

echo.
echo ════════════════════════════════════════
echo   HAYEONG GPU VERIFICATION
echo ════════════════════════════════════════
echo.

echo [1] Checking Communication LLM (port 11434)...
curl -s http://localhost:11434/api/ps
echo.

echo [2] Checking Reasoning LLM (port 11435)...
curl -s http://localhost:11435/api/ps
echo.

echo [3] CUDA devices visible to Python:
call H:\hayeong\.venv\Scripts\activate.bat
python -c "import torch; print('  CUDA available:', torch.cuda.is_available()); print('  Device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'none')"
echo.

echo [4] Voice server health:
curl -s http://localhost:8765/health
echo.

echo ════════════════════════════════════════
echo   Check output above:
echo   - Both Ollama instances should show models loaded
echo   - size_vram should equal size_total (no RAM spillover)
echo   - CUDA should show RTX 3090
echo   - Voice server should return healthy
echo ════════════════════════════════════════
pause
