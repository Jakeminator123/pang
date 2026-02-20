@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT=%~dp0"
cd /d "%ROOT%"

set "MAX_SECS=12600"
set /a "MAX_MS=MAX_SECS * 1000"
REM 3.5 timmar = 12600 s = 12600000 ms

set "LOG=%ROOT%task_stdout.log"

echo ==================================================>> "%LOG%"
echo %date% %time% START run_main_task.bat>> "%LOG%"
echo Working dir: %CD%>> "%LOG%"

net session >nul 2>&1
if !errorlevel! EQU 0 (
  echo %date% %time% CONTEXT: ELEVATED(ADMIN)>> "%LOG%"
) else (
  echo %date% %time% CONTEXT: NORMAL(USER)>> "%LOG%"
)

REM Håll datorn vaken + håll skärmen PÅ under körning (AC + DC)
powercfg -change -monitor-timeout-ac 0 >nul 2>&1
powercfg -change -monitor-timeout-dc 0 >nul 2>&1
powercfg -change -standby-timeout-ac 0 >nul 2>&1
powercfg -change -standby-timeout-dc 0 >nul 2>&1
powercfg -change -hibernate-timeout-ac 0 >nul 2>&1
powercfg -change -hibernate-timeout-dc 0 >nul 2>&1

REM Kill any running Chrome before starting (prevents exit=0 delegation to existing instance)
echo %date% %time% Killing existing Chrome processes before startup>> "%LOG%"
taskkill /IM chrome.exe /F >nul 2>&1
timeout /t 2 /nobreak >nul 2>&1

REM Chrome-lock cleanup
del /f /q "%ROOT%1_poit\chrome_profile\Singleton*" >nul 2>&1
del /f /q "%ROOT%1_poit\chrome_profile\Lockfile" >nul 2>&1

REM ================================================================
REM FIND PYTHON: Try multiple methods with fallback and logging
REM ================================================================
set "PYTHON_EXE="
set "PYTHON_METHOD="

REM --- Method 1: py launcher (Python Launcher for Windows) ---
where py >nul 2>&1
if !errorlevel! EQU 0 (
  echo %date% %time% [FIND_PYTHON] Method 1: py launcher found in PATH>> "%LOG%"
  REM Verify it actually runs
  py -3 --version >nul 2>&1
  if !errorlevel! EQU 0 (
    for /f "delims=" %%V in ('py -3 --version 2^>^&1') do (
      echo %date% %time% [FIND_PYTHON] Method 1 OK: %%V>> "%LOG%"
    )
    set "PYTHON_EXE=py"
    set "PYTHON_ARGS=-3 -u"
    set "PYTHON_METHOD=py_launcher"
  ) else (
    echo %date% %time% [FIND_PYTHON] Method 1 FAIL: py found but 'py -3 --version' failed>> "%LOG%"
  )
) else (
  echo %date% %time% [FIND_PYTHON] Method 1 FAIL: py not found in PATH>> "%LOG%"
)

REM --- Method 2: python in PATH ---
if not defined PYTHON_EXE (
  where python >nul 2>&1
  if !errorlevel! EQU 0 (
    echo %date% %time% [FIND_PYTHON] Method 2: python found in PATH>> "%LOG%"
    python --version >nul 2>&1
    if !errorlevel! EQU 0 (
      for /f "delims=" %%V in ('python --version 2^>^&1') do (
        echo %date% %time% [FIND_PYTHON] Method 2 OK: %%V>> "%LOG%"
      )
      set "PYTHON_EXE=python"
      set "PYTHON_ARGS=-u"
      set "PYTHON_METHOD=python_path"
    ) else (
      echo %date% %time% [FIND_PYTHON] Method 2 FAIL: python found but '--version' failed>> "%LOG%"
    )
  ) else (
    echo %date% %time% [FIND_PYTHON] Method 2 FAIL: python not found in PATH>> "%LOG%"
  )
)

REM --- Method 3: python3 in PATH ---
if not defined PYTHON_EXE (
  where python3 >nul 2>&1
  if !errorlevel! EQU 0 (
    echo %date% %time% [FIND_PYTHON] Method 3: python3 found in PATH>> "%LOG%"
    python3 --version >nul 2>&1
    if !errorlevel! EQU 0 (
      for /f "delims=" %%V in ('python3 --version 2^>^&1') do (
        echo %date% %time% [FIND_PYTHON] Method 3 OK: %%V>> "%LOG%"
      )
      set "PYTHON_EXE=python3"
      set "PYTHON_ARGS=-u"
      set "PYTHON_METHOD=python3_path"
    ) else (
      echo %date% %time% [FIND_PYTHON] Method 3 FAIL: python3 found but '--version' failed>> "%LOG%"
    )
  ) else (
    echo %date% %time% [FIND_PYTHON] Method 3 FAIL: python3 not found in PATH>> "%LOG%"
  )
)

REM --- Method 4: Common install locations ---
if not defined PYTHON_EXE (
  echo %date% %time% [FIND_PYTHON] Method 4: Scanning common install paths...>> "%LOG%"
  for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "C:\Python314\python.exe"
    "C:\Python313\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
    "%PROGRAMFILES%\Python314\python.exe"
    "%PROGRAMFILES%\Python313\python.exe"
    "%PROGRAMFILES%\Python312\python.exe"
  ) do (
    if not defined PYTHON_EXE (
      if exist %%~P (
        echo %date% %time% [FIND_PYTHON] Method 4 OK: Found %%~P>> "%LOG%"
        set "PYTHON_EXE=%%~P"
        set "PYTHON_ARGS=-u"
        set "PYTHON_METHOD=hardcoded_path"
      )
    )
  )
  if not defined PYTHON_EXE (
    echo %date% %time% [FIND_PYTHON] Method 4 FAIL: No python.exe in common paths>> "%LOG%"
  )
)

REM --- Method 5: .venv in project ---
if not defined PYTHON_EXE (
  if exist "%ROOT%.venv\Scripts\python.exe" (
    echo %date% %time% [FIND_PYTHON] Method 5 OK: Found .venv\Scripts\python.exe>> "%LOG%"
    set "PYTHON_EXE=%ROOT%.venv\Scripts\python.exe"
    set "PYTHON_ARGS=-u"
    set "PYTHON_METHOD=project_venv"
  ) else (
    echo %date% %time% [FIND_PYTHON] Method 5 FAIL: No .venv in project root>> "%LOG%"
  )
)

REM --- No Python found at all ---
if not defined PYTHON_EXE (
  echo %date% %time% [FIND_PYTHON] FATAL: No working Python found! Tried 5 methods.>> "%LOG%"
  echo %date% %time% [FIND_PYTHON] PATH was: %PATH%>> "%LOG%"
  set "EC=1"
  goto :cleanup
)

echo %date% %time% [FIND_PYTHON] USING: %PYTHON_EXE% %PYTHON_ARGS% (method: %PYTHON_METHOD%)>> "%LOG%"

REM ================================================================
REM RUN MAIN.PY: Try PowerShell method first, fallback to direct CMD
REM ================================================================
set "RUN_ID="
for /f "delims=" %%D in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_ID=%%D"
if not defined RUN_ID set "RUN_ID=unknown"
set "PYLOG=%ROOT%python_stdout_%RUN_ID%.log"
echo %PYLOG%> "%ROOT%last_python_log.txt"

echo %date% %time% Running main.py (max %MAX_SECS%s, log: %PYLOG%)>> "%LOG%"

REM --- Run method A: PowerShell with timeout (preferred) ---
echo %date% %time% [RUN] Method A: PowerShell with timeout wrapper...>> "%LOG%"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$pyExe = '%PYTHON_EXE%';" ^
  "$pyArgs = '%PYTHON_ARGS%';" ^
  "$mainPy = '%ROOT%main.py';" ^
  "$pylog = '%PYLOG%';" ^
  "$maxMs = %MAX_MS%;" ^
  "$allArgs = ($pyArgs + ' \"' + $mainPy + '\"');" ^
  "try {" ^
  "  $p = Start-Process -FilePath $pyExe -ArgumentList $allArgs -PassThru -NoNewWindow -RedirectStandardOutput $pylog -RedirectStandardError ($pylog + '.err') -ErrorAction Stop;" ^
  "  Add-Content -Path '%LOG%' -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' [RUN] Method A: Started PID ' + $p.Id);" ^
  "  if ($p.WaitForExit($maxMs)) {" ^
  "    Add-Content -Path '%LOG%' -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' [RUN] Method A: Finished with exit code ' + $p.ExitCode);" ^
  "    exit $p.ExitCode" ^
  "  } else {" ^
  "    Add-Content -Path '%LOG%' -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' [RUN] Method A: TIMEOUT after ' + $maxMs + 'ms - killing');" ^
  "    taskkill /PID $p.Id /T 2>$null; Start-Sleep -Seconds 3;" ^
  "    taskkill /PID $p.Id /T /F 2>$null; exit 1460" ^
  "  }" ^
  "} catch {" ^
  "  Add-Content -Path '%LOG%' -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' [RUN] Method A FAIL: ' + $_.Exception.Message);" ^
  "  exit 9999" ^
  "}"

set "EC=!errorlevel!"

REM Check if Method A actually worked (not 9999 = crash, and log file exists with content)
if "!EC!"=="9999" (
  echo %date% %time% [RUN] Method A FAILED - trying fallback Method B>> "%LOG%"
  goto :method_b
)

REM Check if the python log was actually created (Method A might "succeed" but not really run)
if not exist "%PYLOG%" (
  echo %date% %time% [RUN] Method A returned EC=!EC! but NO python log file created - trying Method B>> "%LOG%"
  goto :method_b
)

REM Check if log file has content (more than 0 bytes)
for %%F in ("%PYLOG%") do (
  if %%~zF EQU 0 (
    if "!EC!" NEQ "0" (
      echo %date% %time% [RUN] Method A returned EC=!EC! and python log is EMPTY - trying Method B>> "%LOG%"
      goto :method_b
    )
  )
)

echo %date% %time% [RUN] Method A completed with EC=!EC!>> "%LOG%"
goto :after_run

:method_b
REM --- Run method B: Direct CMD execution (no timeout wrapper, simpler) ---
echo %date% %time% [RUN] Method B: Direct CMD execution (no timeout)...>> "%LOG%"

set "PYLOG=%ROOT%python_stdout_%RUN_ID%_methodB.log"
echo %PYLOG%> "%ROOT%last_python_log.txt"

if "%PYTHON_METHOD%"=="py_launcher" (
  echo %date% %time% [RUN] Method B: Running py -3 -u main.py directly>> "%LOG%"
  py -3 -u "%ROOT%main.py" > "%PYLOG%" 2>&1
) else (
  echo %date% %time% [RUN] Method B: Running %PYTHON_EXE% -u main.py directly>> "%LOG%"
  "%PYTHON_EXE%" -u "%ROOT%main.py" > "%PYLOG%" 2>&1
)

set "EC=!errorlevel!"
echo %date% %time% [RUN] Method B completed with EC=!EC!>> "%LOG%"

:after_run

REM Log which python log file was used
if exist "%ROOT%last_python_log.txt" (
  for /f "usebackq delims=" %%L in ("%ROOT%last_python_log.txt") do (
    echo %date% %time% Python log: %%L>> "%LOG%"
  )
)

REM Merge stderr log if it exists (from Method A)
if exist "%PYLOG%.err" (
  for %%F in ("%PYLOG%.err") do (
    if %%~zF GTR 0 (
      echo %date% %time% Python stderr (appending to main log):>> "%LOG%"
      type "%PYLOG%.err" >> "%PYLOG%" 2>nul
    )
  )
  del /f /q "%PYLOG%.err" >nul 2>&1
)

if "!EC!"=="1460" (
  echo %date% %time% TIMEOUT: main.py killed after 3.5h>> "%LOG%"
  set "EC=0"
) else (
  echo %date% %time% main.py EXITCODE=!EC!>> "%LOG%"
)

:cleanup
REM Cleanup: Kill Flask server (port 51234) and related windows.
REM This is a safety net in case main.py was killed before stop_server() ran.
echo %date% %time% Cleanup: killing server and orphan processes>> "%LOG%"
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":51234" ^| findstr "LISTENING"') do (
  echo %date% %time% Killing server PID %%a>> "%LOG%"
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

if not "!EC!"=="0" (
  echo %date% %time% NOT sleeping because main failed ^(EC=!EC!^).>> "%LOG%"
  endlocal
  exit /b 1
)

echo %date% %time% SLEEP now>> "%LOG%"
rundll32.exe powrprof.dll,SetSuspendState 0,1,0

endlocal
exit /b 0
