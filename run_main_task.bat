@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT=%~dp0"
cd /d "%ROOT%"

set "MAX_SECS=12600"
set /a "MAX_MS=MAX_SECS * 1000"
REM 3.5 timmar = 12600 s = 12600000 ms

echo ==================================================>> "%ROOT%task_stdout.log"
echo %date% %time% START run_main_task.bat>> "%ROOT%task_stdout.log"
echo Working dir: %CD%>> "%ROOT%task_stdout.log"

net session >nul 2>&1
if !errorlevel! EQU 0 (
  echo %date% %time% CONTEXT: ELEVATED(ADMIN)>> "%ROOT%task_stdout.log"
) else (
  echo %date% %time% CONTEXT: NORMAL(USER)>> "%ROOT%task_stdout.log"
)

REM Håll datorn vaken + håll skärmen PÅ under körning (AC + DC)
powercfg -change -monitor-timeout-ac 0 >nul 2>&1
powercfg -change -monitor-timeout-dc 0 >nul 2>&1
powercfg -change -standby-timeout-ac 0 >nul 2>&1
powercfg -change -standby-timeout-dc 0 >nul 2>&1
powercfg -change -hibernate-timeout-ac 0 >nul 2>&1
powercfg -change -hibernate-timeout-dc 0 >nul 2>&1

REM Minimal Chrome-lock cleanup
del /f /q "%ROOT%1_poit\chrome_profile\Singleton*" >nul 2>&1
del /f /q "%ROOT%1_poit\chrome_profile\Lockfile" >nul 2>&1

echo %date% %time% Running main.py (max %MAX_SECS%s)>> "%ROOT%task_stdout.log"

REM Kör python med timeout i samma process (ingen detached failsafe!)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$root = '%ROOT%';" ^
  "$runId = Get-Date -Format 'yyyyMMdd_HHmmss';" ^
  "$pylog = Join-Path $root ('python_stdout_' + $runId + '.log');" ^
  "Set-Content -Encoding ascii -Path (Join-Path $root 'last_python_log.txt') -Value $pylog;" ^
  "$args = @('-3','-u', (Join-Path $root 'main.py'));" ^
  "$p = Start-Process -FilePath 'py' -ArgumentList $args -PassThru -NoNewWindow -RedirectStandardOutput $pylog -RedirectStandardError $pylog;" ^
  "if ($p.WaitForExit(%MAX_MS%)) { exit $p.ExitCode }" ^
  "taskkill /PID $p.Id /T >$null 2>&1; Start-Sleep -Seconds 3;" ^
  "taskkill /PID $p.Id /T /F >$null 2>&1; exit 1460"

set "EC=%ERRORLEVEL%"

if exist "%ROOT%last_python_log.txt" (
  for /f "usebackq delims=" %%L in ("%ROOT%last_python_log.txt") do (
    echo %date% %time% Python log: %%L>> "%ROOT%task_stdout.log"
  )
)

if "%EC%"=="1460" (
  echo %date% %time% TIMEOUT: main.py killed after 3.5h>> "%ROOT%task_stdout.log"
  set "EC=0"
) else (
  echo %date% %time% main.py EXITCODE=%EC%>> "%ROOT%task_stdout.log"
)

REM Cleanup: Kill Flask server (port 51234) and related windows.
REM This is a safety net in case main.py was killed before stop_server() ran.
echo %date% %time% Cleanup: killing server and orphan processes>> "%ROOT%task_stdout.log"
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":51234" ^| findstr "LISTENING"') do (
  echo %date% %time% Killing server PID %%a>> "%ROOT%task_stdout.log"
  taskkill /PID %%a /T /F >nul 2>&1
)
taskkill /FI "WINDOWTITLE eq Flask Server*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Flask Server - *" /F >nul 2>&1

REM Återställ energitider (AC + DC)
REM VIKTIGT: hibernate-timeout sätts till 0 (aldrig) så datorn stannar i S3-sleep.
REM Om hibernate aktiveras (45 min) övergår datorn till viloläge och
REM Task Scheduler kan INTE väcka den kl 07:02 (kräver BIOS RTC-stöd).
powercfg -change -monitor-timeout-ac 30 >nul 2>&1
powercfg -change -monitor-timeout-dc 30 >nul 2>&1
powercfg -change -standby-timeout-ac 30 >nul 2>&1
powercfg -change -standby-timeout-dc 30 >nul 2>&1
powercfg -change -hibernate-timeout-ac 0 >nul 2>&1
powercfg -change -hibernate-timeout-dc 0 >nul 2>&1

if not "%EC%"=="0" (
  echo %date% %time% NOT sleeping because main failed.>> "%ROOT%task_stdout.log"
  exit /b %EC%
)

echo %date% %time% SLEEP now>> "%ROOT%task_stdout.log"
rundll32.exe powrprof.dll,SetSuspendState 0,1,0

endlocal
exit
