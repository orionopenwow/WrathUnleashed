@echo off
setlocal
title Leyline - 1.12 realm on (dry run, read-only)
rem Read-only: checks what turning the 1.12 realm on would do, and reports how players reach the 1.12 site today
rem (routes, the browser game's address settings, the game data killswitch). Runs start-112-realm.sh on the server
rem over SSH (root@play.openvanilla.app, %USERPROFILE%\.ssh\openwow). One SSH login. Changes nothing.
cd /d "%~dp0..\.."
if not exist "tools\ov112-off\start-112-realm.sh" (echo tools\ov112-off\start-112-realm.sh is missing. & pause & exit /b 1)
where tar >nul 2>&1 || (echo tar.exe is missing ^(Windows 10 1803 or later has it^). & pause & exit /b 1)
set "TGZ=%TEMP%\wu-ov112-realm-src.tgz"
if exist "%TGZ%" del /q "%TGZ%"
tar -czf "%TGZ%" --exclude=__pycache__ --exclude=*.pyc tools/ov112-off/start-112-realm.sh hosting/vanilla-remastered/probe112.py hosting/kit/tools/wunet || (echo Packing failed. & pause & exit /b 1)
ssh -i "%USERPROFILE%\.ssh\openwow" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 root@play.openvanilla.app "T=$(mktemp -d) && tar -xzf - -C $T && sed 's/\r$//' $T/tools/ov112-off/start-112-realm.sh > $T/start-112-realm.sh && bash $T/start-112-realm.sh $T --check 2>&1 | tee /tmp/ov112-realm.log; rm -rf $T; grep -q '^OV112 REALM DRY' /tmp/ov112-realm.log" < "%TGZ%"
set "RC=%ERRORLEVEL%"
del /q "%TGZ%" >nul 2>&1
if not "%RC%"=="0" (echo. & echo It did not finish; see above. & pause & exit /b 1)
exit /b 0
