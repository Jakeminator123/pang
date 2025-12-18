@echo off
REM Windows Task Scheduler Script
REM Kör Bolagsverket Scraper mot Render-server

cd /d "%~dp0"

echo ================================================
echo BOLAGSVERKET SCRAPER - Task Scheduler (Render)
echo Starttid: %date% %time%
echo ================================================

REM Uppdatera config.txt för att peka på Render
echo [*] Kontrollerar konfiguration...
findstr /C:"SERVER_URL=https://" config.txt >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [!] Varning: SERVER_URL verkar peka på lokal server
    echo [!] Uppdatera config.txt om du vill använda Render-server
)

REM Kör scrapern
echo [*] Startar scraper mot Render-server...
python automation\scrape_kungorelser.py

echo.
echo ================================================
echo Klart: %date% %time%
echo ================================================
pause

