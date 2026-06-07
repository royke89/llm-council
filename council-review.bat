@echo off
REM council-review launcher - run the LLM Council on the current project.
REM Path-independent: works wherever this repo is cloned (uses its own folder).
setlocal
set "REPO=%~dp0"
if "%REPO:~-1%"=="\" set "REPO=%REPO:~0,-1%"
uv run --directory "%REPO%" python -m backend.review --base-dir "%CD%" %*
