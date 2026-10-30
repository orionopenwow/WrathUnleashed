@echo off
title WrathUnleashed - start the control window at sign-in
rem One time. Puts a small launcher in your Windows Startup folder, so the control window (with Autopilot)
rem starts minimised every time you sign in to this PC. Claude's updates then go live without you pressing
rem anything. To undo: delete "WrathUnleashed Control.bat" from the Startup folder this opens at the end.
cd /d "%~dp0"
set "SU=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "L=%SU%\WrathUnleashed Control.bat"
set "PYEXE=python"
where py >nul 2>&1 && set "PYEXE=py -3"
> "%L%" echo @echo off
>> "%L%" echo cd /d "%~dp0"
>> "%L%" echo start "WrathUnleashed Control" /min %PYEXE% tools\control\control.py --quiet
echo {"on": true, "changed": "set by Start with Windows"}> control\autopilot.json
rem Close the old control window (it has no Autopilot) so the new one can take its place.
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:"127.0.0.1:8097 .*LISTENING"') do taskkill /f /pid %%p >nul 2>&1
echo Done. The control window now starts with Windows, with Autopilot on.
start "WrathUnleashed Control" /min %PYEXE% tools\control\control.py --quiet
explorer "%SU%"
pause
