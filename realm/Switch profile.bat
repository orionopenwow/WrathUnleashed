@echo off
setlocal
rem Picks the realm's rules (profiles\*.env) and restarts the world server.
rem   brawl        level 80 starts in Dalaran, everything unlocked (the default)
rem   progression  blizzlike 1x from level 1; Vanilla, then TBC, then Wrath per character
rem   casual       3x XP from level 1, all expansions open, free .ov boost to 70
rem Usage: "Switch profile.bat" progression    (no argument: asks)
cd /d "%~dp0"
set "P=%~1"
if "%P%"=="" set /p "P=Profile (brawl / progression / casual): "
if not exist "profiles\%P%.env" (echo No profile "%P%". & pause & exit /b 1)
docker version >nul 2>&1 || (echo Docker Desktop is not running. & pause & exit /b 1)
powershell -NoProfile -ExecutionPolicy Bypass -File custom\setenv.ps1 OV_PROFILE %P%
docker compose up -d ac-worldserver
echo Profile is now %P%. Existing characters keep their level; new ones follow the new rules.
pause
