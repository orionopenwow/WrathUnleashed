@echo off
setlocal
title WrathUnleashed - sign-in and warm-up
rem The server half of the faster start (run "Update browser client.bat" first, for the new client):
rem  - play.openvanilla.app/wrath signs in by itself with a Hero Key saved in the browser,
rem  - the realm list downloads the browser client in the background while you read it,
rem  - the client's own files (no game data) skip the sign-in gate so that download can happen.
rem Backs up first and puts things back if anything refuses. One upload and one SSH login.
rem Needs next to this file: wrath_portal.py, fastloop.sh and www-files\art (the pages' art and theme).
rem Optional: docs.py with ..\docs\leyline (the Leyline docs at /wrath/docs).
cd /d "%~dp0"
set "KEY=%USERPROFILE%\.ssh\openwow"
set "HOST=root@play.openvanilla.app"
set "OPTS=-i "%KEY%" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30"
for %%f in (wrath_portal.py fastloop.sh www-files\art\wu-theme.css www-files\art\wu-card.webp) do if not exist "%%f" (echo %%f is missing next to this file. & pause & exit /b 1)
if not exist "%KEY%" (echo SSH key %KEY% not found. & pause & exit /b 1)
set "T=%TEMP%\wu-fastloop.tgz"
if exist "%T%" del /q "%T%"
set "LINKS="
if exist links.py set "LINKS=links.py"
if exist demo.py set "LINKS=%LINKS% demo.py"
if exist armory.py set "LINKS=%LINKS% armory.py"
if exist modes.py if exist modes_data.py set "LINKS=%LINKS% modes.py modes_data.py"
if exist workshop.py set "LINKS=%LINKS% workshop.py"
if exist creations.py set "LINKS=%LINKS% creations.py"
if exist projects.py set "LINKS=%LINKS% projects.py"
rem Leyline flags.json and the Host pack listing (leyline_net.py; hostpack.json from hosting\pack\make-hostpack.py)
if exist leyline_net.py set "LINKS=%LINKS% leyline_net.py"
if exist leyline_net.py if exist hostpack.json set "LINKS=%LINKS% hostpack.json"
rem "+ Your server" (hostflow.py) with the kit's Ed25519, always as a pair
if exist hostflow.py if exist ..\hosting\kit\tools\wunet\ed25519_pure.py copy /y "..\hosting\kit\tools\wunet\ed25519_pure.py" ed25519_pure.py >nul
if exist hostflow.py if exist ed25519_pure.py set "LINKS=%LINKS% hostflow.py ed25519_pure.py"
rem the Leyline docs: docs.py and the pages, which live in the repo's docs\leyline (or docs\leyline next to this file)
set "DOCS="
if exist docs.py if exist docs\leyline\index.md set "DOCS=docs.py docs/leyline"
if exist docs.py if not defined DOCS if exist ..\docs\leyline\index.md set "DOCS=docs.py -C .. docs/leyline"
tar -czf "%T%" wrath_portal.py %LINKS% fastloop.sh www-files/art %DOCS% || (echo Packing failed. & pause & exit /b 1)

echo [1/2] Uploading...
scp %OPTS% "%T%" %HOST%:/tmp/wu-fastloop.tgz || (echo Upload failed. If it says "timed out", wait 2 minutes and run this again. & pause & exit /b 1)

echo [2/2] Applying it on the server (under a minute)...
ssh %OPTS% %HOST% "mkdir -p /srv/wrath/fastloop && rm -rf /srv/wrath/fastloop/www-files /srv/wrath/fastloop/docs && tar -xzf /tmp/wu-fastloop.tgz -C /srv/wrath/fastloop && rm -f /tmp/wu-fastloop.tgz && cd /srv/wrath/fastloop && sed -i 's/\r$//' fastloop.sh wrath_portal.py $(ls links.py demo.py armory.py modes.py modes_data.py workshop.py creations.py hostflow.py ed25519_pure.py projects.py docs.py leyline_net.py 2>/dev/null) && bash fastloop.sh 2>&1 | tee fastloop.log; grep -q '^FASTLOOP OK' fastloop.log"
if errorlevel 1 (
  echo.
  echo It did not report success; see the lines above. Anything it changed was put back.
  del /q "%T%" 2>nul
  pause
  exit /b 1
)
del /q "%T%" 2>nul
echo.
echo Done. Open https://play.openvanilla.app/wrath signed out: a Hero Key saved in this browser signs you in.
pause
exit /b 0
