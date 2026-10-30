@echo off
setlocal
title Leyline - game page only
rem Sends only the browser game's page layer (www-files: wrath-early.js, wrath-page.js, tab.html,
rem leyline-look.css, the loading art...) and puts it into the client that is already live, with
rem www-patch.py. The game build itself (the wasm) is NOT changed, so an untested build in ..\play
rem stays on this PC. Backs up the live page files first; to undo, the last lines say how.
cd /d "%~dp0"
set "KEY=%USERPROFILE%\.ssh\openwow"
set "HOST=root@play.openvanilla.app"
set "OPTS=-i "%KEY%" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30"
for %%f in (server\www-patch.py www-files\wrath-early.js www-files\wrath-page.js www-files\tab.html) do if not exist "%%f" (echo %%f is missing next to this file. & pause & exit /b 1)
if not exist "%KEY%" (echo SSH key %KEY% not found. & pause & exit /b 1)
set "W=%TEMP%\wu-page"
if exist "%W%" rmdir /s /q "%W%"
mkdir "%W%" || goto fail
copy /y server\www-patch.py "%W%\" >nul || goto fail
xcopy /e /i /q /y www-files "%W%\www-files" >nul || goto fail
tar -czf "%TEMP%\wu-page.tgz" -C "%W%" . || goto fail
echo Sending the game page (the game build stays as it is)...
ssh %OPTS% %HOST% "set -e; cd /srv/wrath/stream; test -f www/index.html; BK=/root/page-backups/$(date +%%Y%%m%%d-%%H%%M%%S); mkdir -p $BK; tar -czf $BK/www-page.tgz --exclude='*.wasm' --exclude='*.wasm.br' --exclude='*.wasm.gz' -C www .; [ -d www-files ] && cp -a www-files $BK/; [ -f www-patch.py ] && cp -p www-patch.py $BK/; rm -rf page.new; mkdir page.new; tar -xzf - -C page.new; rm -rf www-files; mv page.new/www-files www-files; mv -f page.new/www-patch.py www-patch.py; rm -rf page.new; sed -i 's/\r$//' www-patch.py; python3 -I www-patch.py www www-files; grep -q 'wrath-early.js' www/index.html && echo PAGE OK || { echo 'PAGE CHECK FAILED: putting the old page back'; tar -xzf $BK/www-page.tgz -C www; rm -rf www-files; cp -a $BK/www-files www-files; exit 1; }; echo backup: $BK; echo undo: tar -xzf $BK/www-page.tgz -C /srv/wrath/stream/www" < "%TEMP%\wu-page.tgz" || goto fail
rmdir /s /q "%W%"
del /q "%TEMP%\wu-page.tgz"
echo.
echo Done. Open https://play.openvanilla.app/wrath and press Play.
exit /b 0
:fail
echo.
echo Something failed above; the live game page is as it was (or was put back).
exit /b 1
