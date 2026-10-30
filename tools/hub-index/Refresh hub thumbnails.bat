@echo off
rem The Leyline hub's preview thumbnails, made on this PC (the Autopilot step "thumbs"; docs\HUB-INDEX.md).
rem For the top 30 entries of the community index and every new one: each GitHub project's own preview image,
rem fetched only from GitHub, made a small WebP in stream\www-files\art\hub-thumbs, and the entry gets its thumb and
rem credit. Then check the index. Afterwards: Ship (save to GitHub) and "signin" to put them on the site.
rem Needs Python 3 and Pillow (installed here for your user if it's missing). Safe to run again.
setlocal
cd /d "%~dp0..\.."
set PY=py -3
where py >nul 2>&1 || set PY=python
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>&1 || (echo Python 3.9 or newer is needed: https://www.python.org/downloads/ & exit /b 1)
%PY% -c "import PIL" >nul 2>&1
if errorlevel 1 (
  echo Installing Pillow (makes the WebP thumbnails^)...
  %PY% -m pip install --user --quiet --disable-pip-version-check pillow || (echo Could not install Pillow: run "%PY% -m pip install pillow" and try again. & exit /b 1)
)
echo Fetching preview images (top 30 and new entries)...
rem Not -I: Pillow may be in the user's site-packages, which -I would hide. The script's own folder has only our files.
%PY% -E "tools\hub-index\hub_index.py" thumbs --top 30 --new
if errorlevel 1 (echo The thumbnails could not be written: see the lines above. & exit /b 1)
%PY% -E "tools\hub-index\hub_index.py" check
if errorlevel 1 (echo The index check failed: nothing to ship until it passes. & exit /b 1)
echo.
echo Done. New or changed files: stream\www-files\art\hub-thumbs and stream\hub\community-index.json.
echo Next: Ship (save to GitHub), then "signin" puts them on the site.
exit /b 0
