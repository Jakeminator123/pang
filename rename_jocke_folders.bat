@echo off
echo ============================================
echo BYTA NAMN PA JOCKE-MAPPARNA
echo ============================================
echo.
echo Detta script byter namn pa:
echo   10_jocke     -> 10_jocke_OLD
echo   10_jocke_sub -> 10_jocke
echo.
echo STANG CURSOR/VS CODE FORST!
echo.
pause

cd /d "%~dp0"

echo.
echo Steg 1: Byter namn pa 10_jocke till 10_jocke_OLD...
if exist "10_jocke" (
    ren "10_jocke" "10_jocke_OLD"
    if errorlevel 1 (
        echo FEL: Kunde inte byta namn. Filen ar last av ett annat program.
        echo Stang Cursor och forsok igen.
        pause
        exit /b 1
    )
    echo OK!
) else (
    echo 10_jocke finns inte, hoppar over...
)

echo.
echo Steg 2: Byter namn pa 10_jocke_sub till 10_jocke...
if exist "10_jocke_sub" (
    ren "10_jocke_sub" "10_jocke"
    if errorlevel 1 (
        echo FEL: Kunde inte byta namn.
        pause
        exit /b 1
    )
    echo OK!
) else (
    echo 10_jocke_sub finns inte!
    pause
    exit /b 1
)

echo.
echo Steg 3: Uppdaterar .gitmodules...
powershell -Command "(Get-Content .gitmodules) -replace '10_jocke_sub', '10_jocke' | Set-Content .gitmodules"
echo OK!

echo.
echo Steg 4: Uppdaterar git submodule config...
git config --file=.gitmodules submodule.10_jocke.path 10_jocke
git add .gitmodules
git submodule sync

echo.
echo ============================================
echo KLART!
echo ============================================
echo.
echo Du kan nu ta bort 10_jocke_OLD nar du vill:
echo   rmdir /s /q 10_jocke_OLD
echo.
echo Glom inte att committa andringarna:
echo   git add .gitmodules 10_jocke
echo   git commit -m "Rename jocke submodule to 10_jocke"
echo.
pause

