@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT=%~dp0"
cd /d "%ROOT%"

echo ==================================================>> "%ROOT%task_stdout.log"
echo %date% %time% START run_main_task.bat>> "%ROOT%task_stdout.log"
echo Working dir: %CD%>> "%ROOT%task_stdout.log"

REM Logga om vi kör elevated (admin)
net session >nul 2>&1
if !errorlevel! EQU 0 (
  echo %date% %time% CONTEXT: ELEVATED(ADMIN)>> "%ROOT%task_stdout.log"
) else (
  echo %date% %time% CONTEXT: NORMAL(USER)>> "%ROOT%task_stdout.log"
)

REM Fail-safe: om något hänger -> SLEEP efter 4h
powershell -NoProfile -Command ^
  "$p = Start-Process cmd -WindowStyle Hidden -PassThru -ArgumentList '/c timeout /t 14400 /nobreak >nul & rundll32.exe powrprof.dll,SetSuspendState 0,1,0';" ^
  "$p.Id | Out-File -Encoding ASCII '%ROOT%failsafe_pid.txt'"

REM Håll datorn vaken + håll skärmen PÅ under körning (AC + DC)
powercfg -change -monitor-timeout-ac 0 >nul 2>&1
powercfg -change -monitor-timeout-dc 0 >nul 2>&1
powercfg -change -standby-timeout-ac 0 >nul 2>&1
powercfg -change -standby-timeout-dc 0 >nul 2>&1
powercfg -change -hibernate-timeout-ac 0 >nul 2>&1
powercfg -change -hibernate-timeout-dc 0 >nul 2>&1

REM Kill any running Chrome before starting (prevents exit=0 delegation to existing instance)
taskkill /IM chrome.exe /F >nul 2>&1
timeout /t 2 /nobreak >nul 2>&1

REM Chrome-lock cleanup
del /f /q "%ROOT%1_poit\chrome_profile\Singleton*" >nul 2>&1
del /f /q "%ROOT%1_poit\chrome_profile\Lockfile" >nul 2>&1

echo %date% %time% Running: py -3 -u "%ROOT%main.py">> "%ROOT%task_stdout.log"
py -3 -u "%ROOT%main.py" >> "%ROOT%python_stdout.log" 2>&1
set "EC=!ERRORLEVEL!"

echo %date% %time% main.py EXITCODE=!EC!>> "%ROOT%task_stdout.log"

REM Stoppa fail-safe timern
if exist "%ROOT%failsafe_pid.txt" (
  for /f %%i in (%ROOT%failsafe_pid.txt) do (
    powershell -NoProfile -Command "Try { Stop-Process -Id %%i -Force -ErrorAction Stop } Catch {}"
  )
  del "%ROOT%failsafe_pid.txt" >nul 2>&1
)

REM Återställ dina normala energitider (AC + DC)
powercfg -change -monitor-timeout-ac 30 >nul 2>&1
powercfg -change -monitor-timeout-dc 30 >nul 2>&1
powercfg -change -standby-timeout-ac 30 >nul 2>&1
powercfg -change -standby-timeout-dc 30 >nul 2>&1
powercfg -change -hibernate-timeout-ac 45 >nul 2>&1
powercfg -change -hibernate-timeout-dc 45 >nul 2>&1

REM Somna bara om main lyckades
if not "!EC!"=="0" (
  echo %date% %time% NOT sleeping because main failed. See python_stdout.log>> "%ROOT%task_stdout.log"
  exit /b !EC!
)

echo %date% %time% SLEEP now>> "%ROOT%task_stdout.log"
rundll32.exe powrprof.dll,SetSuspendState 0,1,0

endlocal
