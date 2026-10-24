@echo off
rem Double-click to start Rasid. Close this window to stop the server.
title Rasid server (close this window to stop)
cd /d "%~dp0"
python -m uv run python -m rasid.app
if errorlevel 1 pause
