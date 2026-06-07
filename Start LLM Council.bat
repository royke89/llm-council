@echo off
REM ============================================================
REM  Start LLM Council - double-click launcher
REM  Opens backend + frontend, then your browser.
REM ============================================================

echo Starting LLM Council backend and frontend...
start "LLM Council - Backend"  /D "%~dp0"        cmd /k "uv run python -m backend.main"
start "LLM Council - Frontend" /D "%~dp0frontend" cmd /k "npm run dev"

REM Give the servers a few seconds to boot, then open the browser
timeout /t 6 /nobreak >nul
start "" "http://localhost:5173"

echo.
echo LLM Council is starting. Your browser will open at http://localhost:5173
echo To STOP it: close the two black terminal windows that just opened.
echo You can close THIS window now.
timeout /t 6 /nobreak >nul
