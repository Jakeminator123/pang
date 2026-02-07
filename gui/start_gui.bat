@echo off
setlocal EnableExtensions
title PANG Konfiguration
chcp 65001 >nul 2>&1

:: Work from the gui directory (where config_gui.py lives)
cd /d "%~dp0"

:: --- Find Python executable ---
set "PY="
where py >nul 2>&1 && set "PY=py"
if not defined PY (
    where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
    where python3 >nul 2>&1 && set "PY=python3"
)
if not defined PY (
    echo.
    echo  ERROR: Python hittades inte!
    echo.
    echo  Installera Python 3.10+ fran https://python.org
    echo  Se till att "Add Python to PATH" ar ikryssat vid installation.
    echo.
    pause
    exit /b 1
)

:: --- Check that customtkinter is installed ---
%PY% -c "import customtkinter" >nul 2>&1
if errorlevel 1 (
    echo Installerar customtkinter...
    %PY% -m pip install --quiet customtkinter
    if errorlevel 1 (
        echo.
        echo  VARNING: Kunde inte installera customtkinter automatiskt.
        echo  Kor manuellt: %PY% -m pip install customtkinter
        echo.
        pause
        exit /b 1
    )
)

:: --- Launch the GUI ---
%PY% config_gui.py
if errorlevel 1 (
    echo.
    echo  Ett fel uppstod vid korning av GUI:t.
    echo  Tryck valfri tangent for att stanga...
    pause >nul
)

endlocal
