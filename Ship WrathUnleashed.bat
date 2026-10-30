@echo off
setlocal EnableDelayedExpansion
title Leyline workspace - save work to GitHub (private repo)
rem Saves the whole WrathUnleashed folder (our scripts, realm Lua/SQL, server kit, GM console, hosting kit,
rem the client patch, docs) to your PRIVATE GitHub repo. Never: game data, slices, Forever UI art, builds,
rem secrets (.gitignore). Shows what changes, scans for secrets, asks yes, commits, pushes.
rem First run: asks for the repo URL (create an EMPTY private repo on GitHub first, e.g. WrathUnleashed).
rem Hands-free (the control panel): WU_SHIP_AUTO=1 answers yes after the secret scan, WU_SHIP_MSG is the note.
rem A cancel exits with code 2, so the panel never marks a cancelled save as done.
cd /d "%~dp0"
set GIT_TERMINAL_PROMPT=1
where git >nul 2>&1 || (echo Git is not installed: https://git-scm.com/download/win & pause & exit /b 1)
if not exist .git (
  git init -q -b main || (echo git init failed. & pause & exit /b 1)
  echo New local repo made here.
)
git remote get-url origin >nul 2>&1 || (
  echo.
  echo Paste the URL of your EMPTY PRIVATE GitHub repo, e.g. https://github.com/orionopenwow/leyline-workspace.git
  set "URL=https://github.com/orionopenwow/leyline-workspace.git"
  echo Using !URL!  ^(press Enter to accept, or paste another^)
  set /p URL=Repo URL: 
  git remote add origin "!URL!" || (echo Could not set the remote. & pause & exit /b 1)
)
echo [1/4] Bringing in GitHub's commits, if any...
git fetch -q origin 2>nul
git rev-parse -q --verify origin/main >nul 2>&1 && (
  git merge-base --is-ancestor origin/main HEAD 2>nul || git merge -q --no-edit origin/main || (
    git merge --abort >nul 2>&1
    echo GitHub's main and this folder changed the same lines. Nothing was changed here. Ask Claude.
    pause & exit /b 1
  )
)
echo [2/4] What will be saved:
git add -A || (echo git add failed. & pause & exit /b 1)
git diff --cached --quiet && goto :push
git --no-pager diff --cached --stat > "%TEMP%\wu-ship-files.txt"
for /f "delims=" %%L in ('git --no-pager diff --cached --shortstat') do echo   %%L
echo   ^(full list: %TEMP%\wu-ship-files.txt^)
echo [3/4] Checking for secrets and game data...
set BAD=0
for /f "delims=" %%F in ('git diff --cached --name-only --diff-filter=AM') do if /i not "%%F"=="Ship WrathUnleashed.bat" (
  findstr /m /r /c:"BEGIN [A-Z]* PRIVATE KEY" /c:"SOAP_PASS=[^$ ]" /c:"MYSQL_ROOT_PASSWORD=[^$ ]" /c:"GM_TOKEN=[A-Za-z0-9]" /c:"client_secret" "%%F" >nul 2>&1 && (echo   SECRET? %%F & set BAD=1)
  echo %%F| findstr /i /r "\.mpq$ \.blp$ \.m2$ \.wmo$ \.adt$ \.dbc$ \.exe$" >nul && (echo   GAME DATA / BINARY? %%F & set BAD=1)
)
if "!BAD!"=="1" (git reset -q & echo. & echo Stopped: the files above look like secrets or game data. Nothing was saved. Ask Claude. & pause & exit /b 1)
echo   clean
set "OK="
if "%WU_SHIP_AUTO%"=="1" (
  set "OK=yes"
  echo   saving ^(hands-free from the control panel^)
) else (
  set /p OK=Type yes to save these changes ^(anything else cancels^): 
)
if /i not "!OK!"=="yes" (git reset -q & echo Cancelled. Nothing was saved. & pause & exit /b 2)
set "MSG=%WU_SHIP_MSG%"
if not "%WU_SHIP_AUTO%"=="1" set /p MSG=One line describing this change: 
if not defined MSG set "MSG=WrathUnleashed update"
git commit -q -m "!MSG!" || (echo Commit failed ^(set git user.name / user.email once^). & pause & exit /b 1)
:push
echo [4/4] Pushing to GitHub (private repo)...
git push -q -u origin HEAD:main || (echo Push failed: check the URL and that you are signed in to GitHub. & pause & exit /b 1)
echo.
echo DONE. Saved to GitHub (main).
pause
exit /b 0
