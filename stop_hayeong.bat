@echo off
echo.
echo ========================================
echo  Stopping Hayeong...
echo ========================================
echo.

REM Stop Python processes (main.py and all threads)
echo Stopping Python processes...
taskkill /F /IM python.exe /T >nul 2>&1
if %errorlevel% == 0 (
    echo   Python stopped.
) else (
    echo   No Python processes found.
)

REM Stop Node.js processes (Minecraft bot)
echo Stopping Node processes...
taskkill /F /IM node.exe /T >nul 2>&1
if %errorlevel% == 0 (
    echo   Node stopped.
) else (
    echo   No Node processes found.
)

REM Stop Ollama instances (unloads models from VRAM)
echo Stopping Ollama instances...
taskkill /F /IM ollama.exe /T >nul 2>&1
taskkill /F /IM ollama_llama_server.exe /T >nul 2>&1
if %errorlevel% == 0 (
    echo   Ollama stopped. VRAM freed.
) else (
    echo   No Ollama processes found.
)

echo.
echo ========================================
echo  Hayeong is offline. VRAM cleared.
echo ========================================
echo.
pause
