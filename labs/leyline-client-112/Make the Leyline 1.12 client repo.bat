@echo off
setlocal EnableDelayedExpansion
title Leyline - make the Leyline 1.12 client repo (our maintained wenilla)
rem One double-click, run by the owner (never by Autopilot: GitHub sign-in needs you).
rem   1. checks the GitHub CLI is signed in as orionopenwow (never Chumpton);
rem   2. makes the PRIVATE repo orionopenwow/leyline-client-112 (never a public fork), starting from
rem      Arnesen/wenilla's main;
rem   3. reads the merged branch out of wenilla-sync.bundle (made by Claude: wenilla + 212 benilla
rem      commits, the char-create fix and server profiles) and pushes it as branch
rem      leyline-sync-2026-10-29, then offers to open the pull request into that repo's main.
rem Never force-pushes. Never pushes to Arnesen/wenilla. Safe to run again.
rem Log: logs\leyline-client-112.log in the WrathUnleashed folder. (In labs/ since 2026-10-30: same depth as tools/, so %~dp0..\.. is still the repo.)
set "WU=%~dp0..\.."
for %%I in ("%WU%") do set "WU=%%~fI"
if not exist "%WU%\logs" mkdir "%WU%\logs"
set "LOG=%WU%\logs\leyline-client-112.log"
set "BRANCH=leyline-sync-2026-10-29"
set "WORK=%USERPROFILE%\leyline-client-112-work"
set GIT_TERMINAL_PROMPT=0
>>"%LOG%" echo %date% %time% started

where git >nul 2>&1 || (echo Git is needed: https://git-scm.com/download/win & goto :fail)
where gh >nul 2>&1 || (echo The GitHub CLI is needed: winget install GitHub.cli  ^(then run this again^) & goto :fail)

echo [1/5] GitHub sign-in...
set "WHO="
for /f "delims=" %%U in ('gh api user --jq .login 2^>nul') do set "WHO=%%U"
if not defined WHO (
  echo   Signing in to GitHub in your browser ^(as orionopenwow^)...
  gh auth login --web --git-protocol https --hostname github.com
  for /f "delims=" %%U in ('gh api user --jq .login 2^>nul') do set "WHO=%%U"
)
if not defined WHO (echo   GitHub sign-in did not finish. & goto :fail)
if /i "!WHO!"=="Chumpton" (echo   Signed in as !WHO!. This repo is orionopenwow's only: run  gh auth switch  and try again. & goto :fail)
if /i not "!WHO!"=="orionopenwow" (echo   Signed in as !WHO!, not orionopenwow. Run  gh auth switch  and try again. & goto :fail)
gh auth setup-git >>"%LOG%" 2>&1
echo   signed in as !WHO!

echo [2/5] The bundle...
set "BUNDLE="
if exist "%~dp0wenilla-sync.bundle" set "BUNDLE=%~dp0wenilla-sync.bundle"
if not defined BUNDLE if exist "%USERPROFILE%\Downloads\wenilla-sync.bundle" set "BUNDLE=%USERPROFILE%\Downloads\wenilla-sync.bundle"
if not defined BUNDLE (
  echo   wenilla-sync.bundle is not next to this file or in Downloads.
  set /p "BUNDLE=  Drag the file here and press Enter: "
  set "BUNDLE=!BUNDLE:"=!"
)
if not exist "!BUNDLE!" (echo   No bundle at !BUNDLE! & goto :fail)
echo   !BUNDLE!

echo [3/5] The private repo orionopenwow/leyline-client-112...
rem Owner decision 2026-10-29: the 1.12 client stays PRIVATE for now (benilla's upstream code cites the original
rem game binary; nothing new goes public until the legal picture is clearer). A GitHub fork of a public repo is
rem always public, so this never forks: it makes a new private repo and refuses to use one that is public.
set "SLUG=orionopenwow/leyline-client-112"
set "PICK=2"
>>"%LOG%" echo %date% %time% target !SLUG! (private)
set "VIS="
for /f "delims=" %%V in ('gh repo view !SLUG! --json visibility --jq .visibility 2^>nul') do set "VIS=%%V"
if defined VIS (
  if /i not "!VIS!"=="PRIVATE" (echo   !SLUG! exists and is !VIS!. It must be private: make it private on GitHub first. & goto :fail)
  echo   !SLUG! is already on GitHub ^(private^): using it
  goto :have_repo
)
gh repo create !SLUG! --private --description "Leyline 1.12 client (private): wenilla tracking benilla, with per-server profiles" >>"%LOG%" 2>&1 || (echo   Creating the repo failed: see %LOG% & goto :fail)
echo   made !SLUG! ^(private^)
:have_repo

echo [4/5] Reading the branch out of the bundle...
if not exist "%WORK%\.git" (
  git clone -q --filter=blob:none https://github.com/Arnesen/wenilla "%WORK%" >>"%LOG%" 2>&1 || (echo   Cloning Arnesen/wenilla failed: see %LOG% & goto :fail)
)
cd /d "%WORK%" || goto :fail
git fetch -q origin >>"%LOG%" 2>&1
git config user.name "Orion"
git config user.email "orionopenwow@users.noreply.github.com"
git bundle verify "!BUNDLE!" >>"%LOG%" 2>&1 || (echo   The bundle does not fit this clone: see %LOG%. Ask Claude. & goto :fail)
git fetch -q "!BUNDLE!" "%BRANCH%:refs/heads/%BRANCH%" >>"%LOG%" 2>&1 || (echo   Could not read %BRANCH% from the bundle: see %LOG% & goto :fail)
for /f "delims=" %%H in ('git rev-parse --short %BRANCH%') do echo   %BRANCH% is %%H

echo [5/5] Pushing to !SLUG! ...
set "URL=https://github.com/!SLUG!.git"
if "!PICK!"=="2" (
  rem A new repo starts from upstream wenilla's main, so the branch has its history to stand on.
  git ls-remote --exit-code "!URL!" refs/heads/main >nul 2>&1 || (
    git push -q "!URL!" origin/main:refs/heads/main >>"%LOG%" 2>&1 || (echo   Pushing main failed: see %LOG% & goto :fail)
    echo   main = Arnesen/wenilla main
  )
)
git push -q "!URL!" "%BRANCH%:refs/heads/%BRANCH%" >>"%LOG%" 2>&1 || (echo   The push was refused ^(nothing was forced^): see %LOG% & goto :fail)
echo   pushed %BRANCH%
set "PR="
set /p "PR=  Open the pull request into !SLUG!'s main now? (merge it with a MERGE COMMIT, not squash) [y/N]: "
if /i "!PR!"=="y" (
  gh pr create -R !SLUG! --base main --head %BRANCH% --title "Merge upstream benilla (212 commits); Leyline 1.12 client" --body "See docs/SERVER-PROFILES.md and the merge commit message. Merge with a merge commit." >>"%LOG%" 2>&1 && echo   pull request opened || echo   Could not open the pull request: see %LOG%
)

:ok
>>"%LOG%" echo %date% %time% done !SLUG!
echo.
echo LEYLINE CLIENT OK: https://github.com/!SLUG!/tree/%BRANCH%
pause
exit /b 0

:fail
>>"%LOG%" echo %date% %time% FAILED
echo.
echo LEYLINE CLIENT FAILED
pause
exit /b 1
