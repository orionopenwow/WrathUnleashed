@echo off
setlocal EnableDelayedExpansion
title Leyline - update the public Leyline repo (github.com/orionopenwow/Leyline)
rem Copies Leyline's parts of WrathUnleashed (the relay, the host kit and its tools, the Discord bridge, the
rem hosting tests, the in-game Leyline window, share links, the Leyline art) into .repos\leyline-public
rem with export.py (an allow-list; it refuses game data, secrets, logs and brand words), then commits and
rem pushes that folder to the PUBLIC repo orionopenwow/Leyline. First run: makes the folder a git repo and
rem creates the GitHub repo with gh if it isn't there yet.
rem Never force-pushes. Never touches the WrathUnleashed folder's own git (it only reads its commit id).
rem Safe to run again: nothing changed = nothing committed. The Autopilot step "leyline" runs this.
set "WU=%~dp0..\.."
for %%I in ("%WU%") do set "WU=%%~fI"
rem The public repo's working copy: .repos\leyline-public inside the workspace (since "Move to Leyline.bat");
rem before the move it is still the separate Desktop\Leyline clone. Never the workspace itself.
set "LY=%WU%\.repos\leyline-public"
if not exist "%LY%\.git" if exist "%USERPROFILE%\Desktop\Leyline\.git" if /i not "%USERPROFILE%\Desktop\Leyline"=="%WU%" set "LY=%USERPROFILE%\Desktop\Leyline"
if not "%LEYLINE_REPO_DIR%"=="" set "LY=%LEYLINE_REPO_DIR%"
set "SLUG=orionopenwow/Leyline"
set "URL=https://github.com/%SLUG%.git"
set GIT_TERMINAL_PROMPT=0

set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (echo Python 3 is needed: https://www.python.org/downloads/ & goto :fail)
where git >nul 2>&1 || (echo Git is not installed: https://git-scm.com/download/win & goto :fail)
where gh >nul 2>&1 || (echo The GitHub CLI is not installed: winget install GitHub.cli  ^(then: gh auth login^) & goto :fail)

echo [1/5] GitHub sign-in...
set "WHO="
for /f "delims=" %%U in ('gh api user --jq .login 2^>nul') do set "WHO=%%U"
if not defined WHO (echo   Not signed in to the GitHub CLI. Run once: gh auth login  ^(as orionopenwow^) & goto :fail)
if /i "!WHO!"=="Chumpton" (echo   The GitHub CLI is signed in as !WHO!. Leyline is published as orionopenwow only: gh auth switch & goto :fail)
echo   signed in as !WHO!

echo [2/5] The Leyline folder: %LY%
if not exist "%LY%" mkdir "%LY%" || (echo   Could not make %LY% & goto :fail)
cd /d "%LY%" || goto :fail
if exist ".git" goto :have_git
git init -q -b main || (echo   git init failed. & goto :fail)
echo   new local repo made here
:have_git
rem Commit as the owner: the identity this PC's git already uses, or the one the WrathUnleashed folder uses (read only).
set "GNAME=" & set "GMAIL="
for /f "delims=" %%A in ('git config user.name 2^>nul') do set "GNAME=%%A"
for /f "delims=" %%A in ('git config user.email 2^>nul') do set "GMAIL=%%A"
if not defined GNAME for /f "delims=" %%A in ('git -C "%WU%" config user.name 2^>nul') do (set "GNAME=%%A" & git config user.name "%%A")
if not defined GMAIL for /f "delims=" %%A in ('git -C "%WU%" config user.email 2^>nul') do (set "GMAIL=%%A" & git config user.email "%%A")
if not defined GMAIL (echo   git has no user.email on this PC: git config --global user.email you@example.com & goto :fail)
echo !GNAME! !GMAIL! | findstr /i "chumpton" >nul && (echo   git is set to commit as !GNAME! / !GMAIL!. Leyline commits are the owner's only. & goto :fail)

rem The GitHub repo: create it once (public), or point origin at it.
gh repo view %SLUG% --json name >nul 2>&1 && goto :repo_ok
echo   %SLUG% is not on GitHub yet: creating it ^(public^)
git remote remove origin >nul 2>&1
gh repo create %SLUG% --public --source . --remote origin --description "Leyline: an open network for hosting, joining and modding community realms" || (echo   gh repo create failed: see above. & goto :fail)
:repo_ok
set "ORIGIN="
for /f "delims=" %%O in ('git remote get-url origin 2^>nul') do set "ORIGIN=%%O"
if defined ORIGIN goto :check_origin
git remote add origin "%URL%" || (echo   Could not set the remote. & goto :fail)
set "ORIGIN=%URL%"
:check_origin
echo !ORIGIN! | findstr /i /c:"github.com/%SLUG%" /c:"github.com:%SLUG%" >nul || (echo   origin is !ORIGIN!, not %SLUG%. Nothing was pushed. Ask Claude. & goto :fail)

echo [3/5] Bringing in GitHub's commits, if any...
git fetch -q origin 2>nul
git rev-parse -q --verify origin/main >nul 2>&1 || goto :export
git rev-parse -q --verify HEAD >nul 2>&1 || (git reset -q origin/main & goto :export)
git merge-base --is-ancestor origin/main HEAD 2>nul && goto :export
git merge -q --no-edit origin/main || (
  git merge --abort >nul 2>&1
  echo   GitHub's Leyline and this folder changed the same lines. Nothing was pushed. Ask Claude.
  goto :fail
)

:export
echo [4/5] Copying Leyline's parts from %WU%
%PY% "%WU%\tools\leyline-repo\export.py" "%LY%" --source "%WU%" || (echo   The export stopped ^(see above^). Nothing was committed. & goto :fail)
git add -A || (echo   git add failed. & goto :fail)
for /f "delims=" %%X in ('%PY% "%WU%\tools\leyline-repo\export.py" --list-exec --source "%WU%"') do git update-index --chmod=+x -- "%%X" >nul 2>&1
git diff --cached --quiet && (echo   nothing changed since the last copy) && goto :push
for /f "delims=" %%L in ('git --no-pager diff --cached --shortstat') do echo   %%L
set "REV="
for /f "delims=" %%R in ('git -C "%WU%" rev-parse --short HEAD 2^>nul') do set "REV=%%R"
if defined REV (set "MSG=Copy from WrathUnleashed !REV!") else set "MSG=Copy from WrathUnleashed"
git commit -q -m "!MSG!" || (echo   Commit failed. & goto :fail)
echo   committed: !MSG!

:push
git rev-parse -q --verify HEAD >nul 2>&1 || (echo   Nothing to push yet. & goto :ok)
echo [5/5] Pushing to GitHub (%SLUG%, public)...
git push -q -u origin HEAD:main || (echo   Push failed: check the sign-in ^(gh auth status^). Nothing was forced. & goto :fail)

:ok
echo.
echo LEYLINE OK: https://github.com/%SLUG%
pause
exit /b 0

:fail
echo.
echo LEYLINE FAILED
pause
exit /b 1
