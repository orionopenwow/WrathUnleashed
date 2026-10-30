@echo off
setlocal
title WrathUnleashed - fix the bots' database and finish the deploy
rem The world server stopped at "Could not populate the playerbots database": the bots module
rem builds its own database from SQL files that aren't inside the server image. This sends those
rem files (from your realm source) plus the updated compose file and deploy script in ONE upload,
rem then runs the deploy again on the server. Already-loaded images and game data are reused.
rem   "Fix bots and finish deploy.bat"          main realm (default)
rem   "Fix bots and finish deploy.bat" brawl    Brawl instead
cd /d "%~dp0"
set "KEY=%USERPROFILE%\.ssh\openwow"
set "HOST=root@play.openvanilla.app"
set "SSH=ssh -i "%KEY%" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 %HOST%"
set "R=%~dp0..\realm"
set "PROFILE=%~1"
if "%PROFILE%"=="" set "PROFILE=main"
set "W=%TEMP%\wu-fix"
set "BOTSQL=%R%\custom\acore\modules\mod-playerbots\data\sql"
if not exist "%BOTSQL%\playerbots\base" (echo Can't find the bots' SQL folder at %BOTSQL%. & pause & exit /b 1)

if exist "%W%" rmdir /s /q "%W%"
mkdir "%W%\kit\modules-sql" "%W%\kit\custom"
copy /y docker-compose.prod.yml "%W%\kit\" >nul || goto fail
copy /y deploy.sh "%W%\kit\" >nul || goto fail
copy /y rollback.sh "%W%\kit\" >nul || goto fail
xcopy /e /i /q /y "%BOTSQL%" "%W%\kit\modules-sql\mod-playerbots" >nul || goto fail
xcopy /e /i /q /y "%R%\custom\lua_scripts" "%W%\kit\custom\lua_scripts" >nul || goto fail
xcopy /e /i /q /y "%R%\profiles" "%W%\kit\profiles" >nul || goto fail
mkdir "%W%\kit\sql"
for %%f in (brawl_world.sql brawl_world_2.sql modern_combos.sql main_unbrawl.sql main_world.sql) do copy /y "%R%\%%f" "%W%\kit\sql\" >nul || goto fail
tar -czf "%W%\kit.tgz" -C "%W%\kit" . || goto fail

echo Uploading the fix and running the deploy again (the world server's first start can take 10-25 minutes)...
%SSH% "cd /srv/wrath && tar -xzf - && sed -i 's/\r$//' deploy.sh rollback.sh && (WU_PROFILE=%PROFILE% setsid nohup bash deploy.sh > deploy.log 2>&1 < /dev/null & echo $! > deploy.pid) && sleep 1 && tail -n +1 -f --pid=$(cat deploy.pid) deploy.log" < "%W%\kit.tgz"
timeout /t 5 >nul
%SSH% "grep -q ' is up. ' /srv/wrath/deploy.log" || (echo The switch did not finish. & echo   ssh in and run: tail -f /srv/wrath/deploy.log & goto fail)
rmdir /s /q "%W%"
echo.
echo WrathUnleashed is live. Sign in at https://play.openvanilla.app/wrath with Google or your Hero Key.
start "" https://play.openvanilla.app/wrath
pause
exit /b 0
:fail
echo.
echo Something failed above. "Rollback to vanilla.bat" brings vanilla back at any time.
pause
exit /b 1
