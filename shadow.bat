@echo off
rem SHADOW terminal commands, run from any folder.
rem   shadow status   - is he running, is his brain online, what did he last hear
rem   shadow log      - his last 40 log lines (shadow log 100 for more)
rem   shadow start    - wake him now (same as laptop boot)
rem   shadow stop     - put him to sleep
rem Prefer his exact interpreter; fall back to
rem whatever 'python' is on PATH.
set "PY=python"
if exist "C:\Users\us448\AppData\Local\Python\pythoncore-3.14-64\python.exe" set "PY=C:\Users\us448\AppData\Local\Python\pythoncore-3.14-64\python.exe"

if /i "%~1"=="status" %PY% "C:\Users\us448\JARVIS\shadow.py" status & goto :done
if /i "%~1"=="log" %PY% "C:\Users\us448\JARVIS\shadow.py" log %~2 & goto :done
if /i "%~1"=="mic" %PY% "C:\Users\us448\JARVIS\shadow.py" mic %~2 & goto :done
if /i "%~1"=="skills" %PY% "C:\Users\us448\JARVIS\shadow.py" skills & goto :done
if /i "%~1"=="train" %PY% "C:\Users\us448\JARVIS\shadow.py" train & goto :done
if /i "%~1"=="update" %PY% "C:\Users\us448\JARVIS\shadow.py" update %~2 & goto :done
if /i "%~1"=="start" (
    cscript //nologo "C:\Users\us448\JARVIS\start_shadow_autostart.vbs"
    echo SHADOW is waking up - give him about 20 seconds to warm his ears.
    goto :done
)
if /i "%~1"=="stop" (
    powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'pythonw.exe' -and $_.CommandLine -like '*shadow.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
    echo SHADOW is asleep.
    goto :done
)
echo SHADOW terminal commands:
echo   shadow status    health check: process, brain, last heard, errors
echo   shadow log [N]   last N log lines of the current session (default 40)
echo   shadow start     wake him now
echo   shadow stop      put him to sleep
echo   shadow skills    list his drop-in skills
echo   shadow train     export chats + training status
echo   shadow mic       list microphones he can reach
echo   shadow mic N     pin device N as his ear and restart him
echo   shadow update    pull his latest code and restart him
echo   shadow update check   just report what is new, pull nothing
:done
