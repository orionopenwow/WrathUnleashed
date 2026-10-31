@echo off
rem The addon marketplace, curated on this PC (Autopilot step "addons-curate"; mods\SPEC.md, "Upstream addons").
rem Every seed in tools\addon-curate\seeds-addons.json: the author's release zip (GitHub API) or the commit archive,
rem checked with the launcher's rules and hashed file by file into mods\upstream.json. New addons and new upstream
rem versions wait for review; nothing is published until someone approves it:
rem   py -3 -I tools\addon-curate\curate.py list
rem   py -3 -I tools\addon-curate\curate.py approve up:skada --by YourName [--works]
rem Then Ship (save to GitHub) and "signin" (puts stream\upstream-addons.json into the site's all.json).
rem Needs Python 3.9+ and git. GITHUB_TOKEN or GH_TOKEN, when set, lifts the GitHub API limits. Safe to run again.
setlocal
cd /d "%~dp0..\.."
set PY=py -3
where py >nul 2>&1 || set PY=python
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>&1 || (echo Python 3.9 or newer is needed: https://www.python.org/downloads/ & exit /b 1)
where git >nul 2>&1 || (echo git is needed: https://git-scm.com/download/win & exit /b 1)
%PY% -I "tools\addon-curate\curate.py" run
if errorlevel 1 (echo Curation stopped: see the lines above. & exit /b 1)
%PY% -I "tools\addon-curate\curate.py" list
echo.
echo Done. Changed: mods\upstream.json (pending review) and stream\upstream-addons.json (approved only).
echo Approve with: %PY% -I tools\addon-curate\curate.py approve up:ID --by YourName
exit /b 0
