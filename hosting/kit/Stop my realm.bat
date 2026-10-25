@echo off
rem Stops the realm. Characters, accounts and your invite link are kept; "Host a Wrath realm.bat" starts it again.
cd /d "%~dp0"
docker version >nul 2>&1 || (echo Docker Desktop is not running. & pause & exit /b 1)
docker compose -f "%~dp0docker-compose.host.yml" --project-directory "%~dp0." stop
echo Stopped. Your characters and accounts are kept.
pause
