@echo off
setlocal
title WrathUnleashed - deploy to play.openvanilla.app
rem Replaces the vanilla game servers on your Hetzner box with the WrathUnleashed realm (Brawl,
rem Warden off for the first test batch). Backs up the vanilla databases first; the website stays
rem up. Undo with "Rollback to vanilla.bat". Uses your existing SSH key (.ssh\openwow).
rem Needs: "Build custom realm.bat" finished on this PC, and the realm's game data extracted.
cd /d "%~dp0"
set "KEY=%USERPROFILE%\.ssh\openwow"
set "HOST=root@play.openvanilla.app"
set "SSH=ssh -i "%KEY%" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 %HOST%"
set "SCP=scp -i "%KEY%""
set "UP=%TEMP%\wu-upload"
set "R=%~dp0..\realm"
rem Realm rules: main (default) or brawl:  "Deploy Wrath to my server.bat" brawl
set "PROFILE=%~1"
if "%PROFILE%"=="" set "PROFILE=main"
if not exist "%R%\profiles\%PROFILE%.env" (echo No profile "%PROFILE%". & pause & exit /b 1)

echo This stops the vanilla realms on play.openvanilla.app (after backing up their databases)
echo and starts WrathUnleashed (%PROFILE%) in their place. The website keeps running, and its sign-in
echo (Google or Hero Key) becomes the Wrath sign-in at https://play.openvanilla.app/wrath
set /p OK=Type YES to go ahead: 
if /i not "%OK%"=="YES" (echo Cancelled. & pause & exit /b 1)

docker version >nul 2>&1 || (echo Start Docker Desktop first. & pause & exit /b 1)
docker image inspect ov/ac-wotlk-worldserver:custom >nul 2>&1 || (echo The custom realm build is not finished yet. & pause & exit /b 1)
%SSH% "mkdir -p /srv/wrath/upload && echo connected" || (echo Cannot reach the server over SSH. If it says "timed out", wait 2 minutes and try again. & pause & exit /b 1)

if exist "%UP%" rmdir /s /q "%UP%"
mkdir "%UP%"
echo [1/4] Packing the server's game data (from your own install; it stays on the server)...
docker run --rm -v ov-client-data:/d:ro -v "%UP%:/out" alpine:3.20 sh -c "tar -C /d -czf /out/client-data.tgz dbc maps $(cd /d && ls -d Cameras 2>/dev/null)" || (echo Packing the game data failed. & pause & exit /b 1)
echo [2/4] Packing the realm images (a few minutes)...
docker save -o "%UP%\wu-images.tar" ov/ac-wotlk-db-import:custom ov/ac-wotlk-authserver:custom ov/ac-wotlk-worldserver:custom || (echo docker save failed. & pause & exit /b 1)
docker run --rm -v "%UP%:/u" alpine:3.20 gzip -1 /u/wu-images.tar || (echo Compressing failed. & pause & exit /b 1)
dir "%UP%" | findstr /r "client-data wu-images"

echo [3/4] Uploading (the big files can take 10-40 minutes on a home connection)...
rem Everything small goes in one kit, and everything in one scp: the server pauses SSH after many quick logins.
if exist "%UP%\kit" rmdir /s /q "%UP%\kit"
mkdir "%UP%\kit" "%UP%\kit\sql" "%UP%\kit\custom"
for %%f in (docker-compose.prod.yml deploy.sh rollback.sh set-realm-address.sh backup.sh restore.sh soap-cmd.sh) do copy /y "%%f" "%UP%\kit\" >nul || goto fail
xcopy /e /i /q /y portal "%UP%\kit\portal" >nul || goto fail
copy /y "%R%\modules.env" "%UP%\kit\" >nul || goto fail
xcopy /e /i /q /y "%R%\profiles" "%UP%\kit\profiles" >nul || goto fail
xcopy /e /i /q /y "%R%\custom\lua_scripts" "%UP%\kit\custom\lua_scripts" >nul || goto fail
xcopy /e /i /q /y "%R%\custom\acore\modules\mod-playerbots\data\sql" "%UP%\kit\modules-sql\mod-playerbots" >nul || goto fail
for %%f in (brawl_world.sql brawl_world_2.sql modern_combos.sql main_unbrawl.sql main_world.sql charfix_world.sql) do copy /y "%R%\%%f" "%UP%\kit\sql\" >nul || goto fail
tar -czf "%UP%\kit.tgz" -C "%UP%\kit" . || goto fail
%SCP% "%UP%\client-data.tgz" "%UP%\wu-images.tar.gz" "%UP%\kit.tgz" %HOST%:/srv/wrath/upload/ || goto fail

echo [4/4] Switching the server over (5-20 minutes; the first start builds the databases)...
rem The switch runs on the server by itself (deploy.log), so a dropped connection can't stop it halfway.
%SSH% "cd /srv/wrath && tar -xzf upload/kit.tgz && rm -f upload/kit.tgz && sed -i 's/\r$//' deploy.sh rollback.sh && (WU_PROFILE=%PROFILE% setsid nohup bash deploy.sh > deploy.log 2>&1 < /dev/null & echo $! > deploy.pid) && sleep 1 && tail -n +1 -f --pid=$(cat deploy.pid) deploy.log"
timeout /t 5 >nul
%SSH% "grep -q ' is up. ' /srv/wrath/deploy.log" || (echo The switch did not finish. If the connection dropped, it may still be running: & echo   ssh in and run: tail -f /srv/wrath/deploy.log & goto fail)
rmdir /s /q "%UP%"
echo.
echo WrathUnleashed is live. Sign in at https://play.openvanilla.app/wrath with Google or your Hero Key:
echo it shows your Wrath login. Then "Make GM.bat" with that account name.
start "" https://play.openvanilla.app/wrath
pause
exit /b 0
:fail
echo.
echo Something failed above. Nothing is lost: the vanilla backups are in /root/vanilla-backups,
echo and "Rollback to vanilla.bat" brings vanilla back.
pause
exit /b 1
