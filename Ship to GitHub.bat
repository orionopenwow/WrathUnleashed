@echo off
setlocal EnableDelayedExpansion
title Leyline - ship to GitHub
rem One double-click, no questions: saves the whole Leyline workspace to the PRIVATE GitHub repo
rem (orionopenwow/leyline-workspace), on main. Never: game data, slices, Forever UI art, builds, secrets (.gitignore).
rem   1. brings in GitHub's main (stops, changing nothing, if both sides changed the same lines);
rem   2. stages everything (git add -A) and checks it for secrets and game data (stops, saving nothing, if any);
rem   3. commits as "Leyline update YYYY-MM-DD HH:MM" with the short stat (or the note in LEYLINE_SHIP_MSG / WU_SHIP_MSG);
rem   4. pushes to main. Success closes by itself after 5 seconds; a problem keeps the window open.
rem The control panel and the other steps set LEYLINE_SHIP_AUTO=1 (or the older WU_SHIP_AUTO=1): same run, no wait.
rem Exit code 0 = saved (or nothing new), 1 = stopped.
cd /d "%~dp0"
set GIT_TERMINAL_PROMPT=1
set "AUTO="
if "%WU_SHIP_AUTO%"=="1" set "AUTO=1"
if "%LEYLINE_SHIP_AUTO%"=="1" set "AUTO=1"
set "MSG=%LEYLINE_SHIP_MSG%"
if not defined MSG set "MSG=%WU_SHIP_MSG%"
where git >nul 2>&1 || (echo Git is not installed: https://git-scm.com/download/win & goto fail)
if not exist .git (
  git init -q -b main || (echo git init failed. & goto fail)
  echo New local repo made here.
)
git remote get-url origin >nul 2>&1 || (
  git remote add origin "https://github.com/orionopenwow/leyline-workspace.git" || (echo Could not set the remote. & goto fail)
  echo Remote set to https://github.com/orionopenwow/leyline-workspace.git
)

echo [1/4] Bringing in GitHub's commits, if any...
git fetch -q origin 2>nul
git rev-parse -q --verify origin/main >nul 2>&1 && (
  git merge-base --is-ancestor origin/main HEAD 2>nul || git merge -q --no-edit origin/main || (
    git merge --abort >nul 2>&1
    echo GitHub's main and this folder changed the same lines. Nothing was changed here. Ask Claude.
    goto fail
  )
)

echo [2/4] What will be saved:
rem Machine state (control window, logs) stays on this PC: older copies of the repo still tracked these.
git rm -r -q --cached --ignore-unmatch -- control/autopilot.json control/claude-status.json control/last-run.json logs >nul 2>&1
git add -A || (echo git add failed. & goto fail)
git diff --cached --quiet && (echo   nothing new to save & goto push)
git --no-pager diff --cached --stat > "%TEMP%\leyline-ship-files.txt"
set "STAT="
for /f "delims=" %%L in ('git --no-pager diff --cached --shortstat') do set "STAT=%%L"
echo  !STAT!
echo   ^(full list: %TEMP%\leyline-ship-files.txt^)

echo [3/4] Checking for secrets and game data...
set BAD=0
for /f "delims=" %%F in ('git diff --cached --name-only --diff-filter=AM') do if /i not "%%F"=="Ship to GitHub.bat" (
  findstr /m /r /c:"BEGIN [A-Z]* PRIVATE KEY" /c:"SOAP_PASS=[^$ ]" /c:"MYSQL_ROOT_PASSWORD=[^$ ]" /c:"GM_TOKEN=[A-Za-z0-9]" /c:"client_secret" "%%F" >nul 2>&1 && (echo   SECRET? %%F & set BAD=1)
  echo %%F| findstr /i /r "\.mpq$ \.blp$ \.m2$ \.wmo$ \.adt$ \.dbc$ \.exe$" >nul && (echo   GAME DATA / BINARY? %%F & set BAD=1)
)
if "!BAD!"=="1" (git reset -q & echo. & echo Stopped: the files above look like secrets or game data. Nothing was saved. Ask Claude. & goto fail)
echo   clean
if not defined MSG (
  set "NOW="
  for /f "delims=" %%T in ('powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd HH:mm'" 2^>nul') do set "NOW=%%T"
  if not defined NOW set "NOW=%date% %time:~0,5%"
  set "MSG=Leyline update !NOW!"
)
git commit -q -m "!MSG!" -m "!STAT!" || (echo Commit failed ^(set git user.name / user.email once^). & goto fail)
echo   committed: !MSG!

:push
echo [4/4] Pushing to GitHub (main)...
git push -q -u origin HEAD:main || (echo Push failed: check that you are signed in to GitHub. & goto fail)
echo.
echo DONE. Saved to GitHub (orionopenwow/leyline-workspace, main).
if not defined AUTO timeout /t 5
exit /b 0

:fail
echo.
echo Stopped. Nothing was pushed. Send Claude a screenshot of this window.
pause
exit /b 1
