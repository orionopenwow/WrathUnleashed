@echo off
rem Step 2: start the realm (database, auth on 127.0.0.1:3724, world on 127.0.0.1:8085).
rem The first start imports the databases and takes a few minutes.
cd /d "%~dp0"
docker version >nul 2>&1 || (echo Docker Desktop is not running. Start it, then run this again. & pause & exit /b 1)
docker compose up -d || (echo. & echo The realm did not start. Run collect-logs.bat and send logs.txt. & pause & exit /b 1)
echo.
echo Waiting for the world server (first start: several minutes)...
:wait
timeout /t 10 >nul
docker logs ov-ac-worldserver 2>&1 | findstr /c:"ready..." >nul || goto wait
echo The realm is up. Next: add-account.bat, then "Play 3.3.5a in browser.bat".
pause
