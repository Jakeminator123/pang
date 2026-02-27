@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT=%~dp0"
cd /d "%ROOT%"

set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"

echo ==================================================>> "%ROOT%task_stdout.log"
echo %date% %time% START run_main_task.bat>> "%ROOT%task_stdout.log"
echo Working dir: %CD%>> "%ROOT%task_stdout.log"

REM Log if running elevated (admin)
net session >nul 2>&1
if !errorlevel! EQU 0 (
  echo %date% %time% CONTEXT: ELEVATED>> "%ROOT%task_stdout.log"
) else (
  echo %date% %time% CONTEXT: NORMAL>> "%ROOT%task_stdout.log"
)

REM Fail-safe: if something hangs -> SLEEP after 4h
powershell -NoProfile -Command ^
  "$p = Start-Process cmd -WindowStyle Hidden -PassThru -ArgumentList '/c timeout /t 14400 /nobreak >nul & rundll32.exe powrprof.dll,SetSuspendState 0,1,0';" ^
  "$p.Id | Out-File -Encoding ASCII '%ROOT%failsafe_pid.txt'"

REM Keep computer awake and screen ON during run (AC + DC)
powercfg -change -monitor-timeout-ac 0 >nul 2>&1
powercfg -change -monitor-timeout-dc 0 >nul 2>&1
powercfg -change -standby-timeout-ac 0 >nul 2>&1
powercfg -change -standby-timeout-dc 0 >nul 2>&1
powercfg -change -hibernate-timeout-ac 0 >nul 2>&1
powercfg -change -hibernate-timeout-dc 0 >nul 2>&1

REM Kill any running Chrome before starting (prevents exit=0 delegation)
taskkill /IM chrome.exe /F >nul 2>&1
timeout /t 2 /nobreak >nul 2>&1

REM Chrome-lock cleanup
del /f /q "%ROOT%1_poit\chrome_profile\Singleton*" >nul 2>&1
del /f /q "%ROOT%1_poit\chrome_profile\Lockfile" >nul 2>&1

echo %date% %time% Running: py -3 -u "%ROOT%main.py">> "%ROOT%task_stdout.log"
py -3 -u "%ROOT%main.py" >> "%ROOT%python_stdout.log" 2>&1
set "EC=!ERRORLEVEL!"

echo %date% %time% main.py EXITCODE=!EC!>> "%ROOT%task_stdout.log"

REM Stop fail-safe timer
if exist "%ROOT%failsafe_pid.txt" (
  for /f %%i in (%ROOT%failsafe_pid.txt) do (
    powershell -NoProfile -Command "Try { Stop-Process -Id %%i -Force -ErrorAction Stop } Catch {}"
  )
  del "%ROOT%failsafe_pid.txt" >nul 2>&1
)

REM Restore normal power timeouts (AC + DC)
REM hibernate-timeout=0 keeps machine in S3-sleep so Task Scheduler can wake it
powercfg -change -monitor-timeout-ac 30 >nul 2>&1
powercfg -change -monitor-timeout-dc 30 >nul 2>&1
powercfg -change -standby-timeout-ac 30 >nul 2>&1
powercfg -change -standby-timeout-dc 30 >nul 2>&1
powercfg -change -hibernate-timeout-ac 0 >nul 2>&1
powercfg -change -hibernate-timeout-dc 0 >nul 2>&1

REM Only sleep if main succeeded
if not "!EC!"=="0" (
  echo %date% %time% NOT sleeping because main failed. See python_stdout.log>> "%ROOT%task_stdout.log"
  endlocal
  exit /b !EC!
)

echo %date% %time% DONE OK - sleeping now>> "%ROOT%task_stdout.log"
rundll32.exe powrprof.dll,SetSuspendState 0,1,0

endlocal
exit /b 0
