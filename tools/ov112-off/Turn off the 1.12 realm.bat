@echo off
setlocal
title Leyline - 1.12 realm off
rem Stops vr-mangosd and vr-realmd again (kept, not removed: Turn on the 1.12 realm.bat starts them again).
rem Refuses while Vanilla Remastered is still on Leyline: run the vr-beacon-off step first.
cd /d "%~dp0..\.."
if not exist "tools\ov112-off\start-112-realm.sh" (echo tools\ov112-off\start-112-realm.sh is missing. & pause & exit /b 1)
where tar >nul 2>&1 || (echo tar.exe is missing ^(Windows 10 1803 or later has it^). & pause & exit /b 1)
set "TGZ=%TEMP%\wu-ov112-realm-src.tgz"
if exist "%TGZ%" del /q "%TGZ%"
tar -czf "%TGZ%" --exclude=__pycache__ --exclude=*.pyc tools/ov112-off/start-112-realm.sh hosting/vanilla-remastered/probe112.py hosting/kit/tools/wunet || (echo Packing failed. & pause & exit /b 1)
ssh -i "%USERPROFILE%\.ssh\openwow" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 root@play.openvanilla.app "T=$(mktemp -d) && tar -xzf - -C $T && sed 's/\r$//' $T/tools/ov112-off/start-112-realm.sh > $T/start-112-realm.sh && bash $T/start-112-realm.sh $T --off 2>&1 | tee /tmp/ov112-realm.log; rm -rf $T; grep -q '^OV112 REALM OFF' /tmp/ov112-realm.log" < "%TGZ%"
set "RC=%ERRORLEVEL%"
del /q "%TGZ%" >nul 2>&1
if not "%RC%"=="0" (echo. & echo It did not finish; see above. & pause & exit /b 1)
exit /b 0
