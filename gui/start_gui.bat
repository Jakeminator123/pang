@echo off
title PANG Konfiguration
cd /d "%~dp0"
python config_gui.py
if errorlevel 1 (
    echo.
    echo Ett fel uppstod. Tryck valfri tangent for att stanga...
    pause >nul
)
