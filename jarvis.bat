@echo off
rem Shadow terminal commands, run from any folder.
rem   Shadow status   - is he running, is his brain online, what did he last hear
rem   Shadow log      - his last 40 log lines (Shadow log 100 for more)
rem   Shadow start    - wake him now (same as laptop boot)
rem   Shadow stop     - put him to sleep
rem Prefer his exact interpreter; fall back to
rem whatever 'python' is on PATH.
set "PY=python"
if exist "C:\Users\us448\AppData\Local\Python\pythoncore-3.14-64\python.exe" set "PY=C:\Users\us448\AppData\Local\Python\pythoncore-3.14-64\python.exe"

if /i "%~1"=="status" %PY% "C:\Users\us448\Shadow\Shadow.py" status & goto :done
if /i "%~1"=="log" %PY% "C:\Users\us448\Shadow\Shadow.py" log %~2 & goto :done
if /i "%~1"=="mic" %PY% "C:\Users\us448\Shadow\Shadow.py" mic %~2 & goto :done
if /i "%~1"=="skills" %PY% "C:\Users\us448\Shadow\Shadow.py" skills & goto :done
if /i "%~1"=="train" %PY% "C:\Users\us448\Shadow\Shadow.py" train & goto :done
if /i "%~1"=="update" %PY% "C:\Users\us448\Shadow\Shadow.py" update %~2 & goto :done
if /i "%~1"=="start" (
    cscript //nologo "C:\Users\us448\Shadow\start_Shadow_autostart.vbs"
    echo Shadow is waking up - give him about 20 seconds to warm his ears.
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
echo   Shadow start     wake him now
echo   Shadow stop      put him to sleep
echo   Shadow skills    list his drop-in skills
echo   Shadow train     export chats + training status
echo   Shadow mic       list microphones he can reach
echo   Shadow mic N     pin device N as his ear and restart him
echo   Shadow update    pull his latest code and restart him
echo   Shadow update check   just report what is new, pull nothing
:done
