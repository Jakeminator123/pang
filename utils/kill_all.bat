@echo off
REM kill_all.bat - Windows batch-fil för att döda alla processer
REM Användning: kill_all.bat

echo ============================================================
echo DODAR ALLA PYTHON-PROCESSER, SERVRAR OCH CHROME
echo ============================================================
echo.

echo [1] Dodar Flask-server (port 51234)...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :51234 ^| findstr LISTENING') do (
    echo   Dodar PID %%a
    taskkill /F /PID %%a >nul 2>&1
)
echo.

echo [2] Dodar Python-processer...
taskkill /F /IM python.exe >nul 2>&1
taskkill /F /IM pythonw.exe >nul 2>&1
taskkill /F /IM py.exe >nul 2>&1
echo   Klart
echo.

echo [3] Dodar Chrome-processer...
taskkill /F /IM chrome.exe >nul 2>&1
echo   Klart
echo.

echo ============================================================
echo Klart!
echo ============================================================
pause

