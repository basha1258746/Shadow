@echo off
rem Shadow terminal commands, run from any folder.
rem   Shadow status   - is she running, is her brain online, what did she last hear
rem   Shadow log      - her last 40 log lines (Shadow log 100 for more)
rem   Shadow start    - wake her now (same as laptop boot)
rem   Shadow stop     - put her to sleep
rem Prefer her exact interpreter; fall back to
rem whatever 'python' is on PATH.
set "PY=python"
if exist "C:\Users\us448\AppData\Local\Python\pythoncore-3.14-64\python.exe" set "PY=C:\Users\us448\AppData\Local\Python\pythoncore-3.14-64\python.exe"

if /i "%~1"=="status" %PY% "C:\Users\us448\Shadow\Shadow.py" status & goto :done
if /i "%~1"=="log" %PY% "C:\Users\us448\Shadow\Shadow.py" log %~2 & goto :done
if /i "%~1"=="mic" %PY% "C:\Users\us448\Shadow\Shadow.py" mic %~2 & goto :done
if /i "%~1"=="skills" %PY% "C:\Users\us448\Shadow\Shadow.py" skills & goto :done
if /i "%~1"=="update" %PY% "C:\Users\us448\Shadow\Shadow.py" update %~2 & goto :done
if /i "%~1"=="start" (
    cscript //nologo "C:\Users\us448\Shadow\start_Shadow_autostart.vbs"
    echo Shadow is waking up - give her about 20 seconds to warm her ears.
    goto :done
)
if /i "%~1"=="stop" (
    powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'pythonw.exe' -and $_.CommandLine -like '*Shadow.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
    echo Shadow is asleep.
    goto :done
)
echo Shadow terminal commands:
echo   Shadow status    health check: process, brain, last heard, errors
echo   Shadow log [N]   last N log lines of the current session (default 40)
echo   Shadow start     wake her now
echo   Shadow stop      put her to sleep
echo   Shadow skills    list her drop-in skills
echo   Shadow mic       list microphones she can reach
echo   Shadow mic N     pin device N as her ear and restart her
echo   Shadow update    pull her latest code and restart her
echo   Shadow update check   just report what is new, pull nothing
:done
