@echo off
rem The launcher Home gallery's in-game screenshots, from site-art\home\ on this PC to the website (the Autopilot step
rem "homeart"). Put screenshots named by slide in site-art\home\ (hangout.png, browser.png, host.png, den.png,
rem news.png; hangout-2.png for a second one that takes turns; optional captions.json). This makes each a 1600 px
rem wide WebP with no metadata plus home.json, uploads them (one upload, one SSH login) to /srv/wrath/portal/art/home,
rem served at https://play.openvanilla.app/wrath/art/home/, keeps a backup of what was there and puts it back if the
rem site does not answer with the new list. Nothing goes into the repo. Needs Python 3 and Pillow. Safe to run again.
setlocal
cd /d "%~dp0..\.."
set "KEY=%USERPROFILE%\.ssh\openwow"
set "HOST=root@play.openvanilla.app"
set "OPTS=-i "%KEY%" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30"
if not exist "%KEY%" (echo SSH key %KEY% not found. & exit /b 1)
if not exist "site-art\home" (echo Make the folder site-art\home here and put the screenshots in it: hangout.png, browser.png, host.png, den.png, news.png. & exit /b 1)
set PY=py -3
where py >nul 2>&1 || set PY=python
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>&1 || (echo Python 3.9 or newer is needed: https://www.python.org/downloads/ & exit /b 1)
%PY% -c "import PIL" >nul 2>&1
if errorlevel 1 (
  echo Installing Pillow (makes the WebP pictures^)...
  %PY% -m pip install --user --quiet --disable-pip-version-check pillow || (echo Could not install Pillow: run "%PY% -m pip install pillow" and try again. & exit /b 1)
)
set "OUT=%TEMP%\leyline-home-art"
if exist "%OUT%" rmdir /s /q "%OUT%"
echo [1/3] Making the pictures...
rem Not -I: Pillow may be in the user's site-packages, which -I would hide. The script's own folder has only our files.
%PY% -E "tools\site-art\publish_home_art.py" build --src "site-art\home" --out "%OUT%"
if errorlevel 1 (echo Nothing was uploaded: see the lines above. & exit /b 1)
set "T=%TEMP%\leyline-home-art.tgz"
if exist "%T%" del /q "%T%"
copy /y "tools\site-art\install-home-art.sh" "%OUT%\install-home-art.sh" >nul || (echo tools\site-art\install-home-art.sh is missing. & exit /b 1)
mkdir "%OUT%\art" >nul 2>&1
move /y "%OUT%\*.webp" "%OUT%\art\" >nul
move /y "%OUT%\home.json" "%OUT%\art\" >nul
tar -czf "%T%" -C "%OUT%" install-home-art.sh art || (echo Packing failed. & exit /b 1)

echo [2/3] Uploading...
scp %OPTS% "%T%" %HOST%:/tmp/leyline-home-art.tgz || (echo Upload failed. If it says "timed out", wait 2 minutes and run this again. & exit /b 1)

echo [3/3] Putting them on the site (backup first)...
ssh %OPTS% %HOST% "rm -rf /tmp/leyline-home-art && mkdir -p /tmp/leyline-home-art && tar -xzf /tmp/leyline-home-art.tgz -C /tmp/leyline-home-art && rm -f /tmp/leyline-home-art.tgz && sed -i 's/\r$//' /tmp/leyline-home-art/install-home-art.sh && sh /tmp/leyline-home-art/install-home-art.sh; r=$?; rm -rf /tmp/leyline-home-art; exit $r"
if errorlevel 1 (
  echo.
  echo It did not report success; see the lines above. The site keeps the screenshots it had.
  del /q "%T%" 2>nul
  exit /b 1
)
del /q "%T%" 2>nul
echo.
echo Done: https://play.openvanilla.app/wrath/art/home/home.json lists them; the launcher shows them on Home next time it opens.
exit /b 0
