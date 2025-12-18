@echo off
REM Startar Chrome med extensionen och din profil manuellt
REM Använd detta för att testa att extensionen laddas korrekt

cd /d "%~dp0"

set EXT_PATH=%cd%\ext_bolag
set PROFILE_PATH=%cd%\chrome_profile

echo ================================================
echo ÖPPNAR CHROME MED EXTENSION
echo Extension: %EXT_PATH%
echo Profil: %PROFILE_PATH%
echo ================================================

REM Starta Chrome med extension och profil
"C:\Program Files\Google\Chrome\Application\chrome.exe" ^
  --user-data-dir="%PROFILE_PATH%" ^
  --profile-directory=Default ^
  --load-extension="%EXT_PATH%" ^
  https://www.google.com

echo.
echo Chrome öppnad. Kontrollera chrome://extensions för att se om extensionen laddades.
pause

