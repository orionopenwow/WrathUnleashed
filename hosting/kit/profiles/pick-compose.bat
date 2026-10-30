@echo off
rem Sets CF to the compose file of the realm this kit folder hosts: profiles\<id>\docker-compose.<id>.yml when
rem state\host.json names a profile for another client (host any client), else the kit's docker-compose.host.yml.
rem Called by "Check my realm.bat", "Stop my realm.bat" and "Realm tools.bat" (call "%~dp0profiles\pick-compose.bat").
set "CF=%~dp0..\docker-compose.host.yml"
for /d %%P in ("%~dp0*") do (
  if exist "%%P\profile.lock" findstr /c:"\"profile\": \"%%~nxP\"" "%~dp0..\state\host.json" >nul 2>&1 && (
    for %%F in ("%%P\docker-compose.*.yml") do set "CF=%%~fF"
  )
)
exit /b 0
