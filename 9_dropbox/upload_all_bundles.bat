@echo off
chcp 65001 >nul
echo ============================================
echo   UPLOAD ALLA ZIP-BUNDLES TILL DASHBOARD
echo ============================================
echo.

cd /d "%~dp0"

:: Kolla om UPLOAD_SECRET är satt
if "%UPLOAD_SECRET%"=="" (
    echo [INFO] UPLOAD_SECRET inte satt i miljon.
    echo [INFO] Forsoker ladda fran .env...
    
    :: Försök läsa från .env
    if exist "..\\.env" (
        for /f "tokens=1,2 delims==" %%a in ('findstr /r "^UPLOAD_SECRET=" "..\\.env"') do (
            set "UPLOAD_SECRET=%%b"
        )
    )
)

if "%UPLOAD_SECRET%"=="" (
    echo.
    echo [FEL] UPLOAD_SECRET ar inte satt!
    echo.
    echo Satt den i .env filen:
    echo   UPLOAD_SECRET=din-hemliga-nyckel
    echo.
    echo Eller kor med:
    echo   set UPLOAD_SECRET=din-nyckel
    echo   upload_all_bundles.bat
    echo.
    pause
    exit /b 1
)

echo [OK] UPLOAD_SECRET hittad
echo.

:: Kör Python-scriptet med --all
python upload_to_dashboard.py --all

echo.
echo ============================================
if %ERRORLEVEL%==0 (
    echo   KLART! Alla bundles uppladdade.
) else (
    echo   Nagra uploads misslyckades.
)
echo ============================================
echo.
pause

