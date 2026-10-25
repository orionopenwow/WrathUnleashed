@echo off
rem Owner tool: fills realm-files\ from ..\realm (profiles, modules.env, Lua, profile SQL), then makes
rem WrathUnleashed-host-kit.zip next to this folder for players. Leaves out state\, .env and cache\.
cd /d "%~dp0"
if not exist "..\realm\profiles\main.env" (echo Run this from WrathUnleashed\host ^(..\realm must exist^). & pause & exit /b 1)
if exist realm-files rmdir /s /q realm-files
mkdir realm-files\profiles realm-files\sql
for %%P in (main brawl progression casual dalaran) do copy /y "..\realm\profiles\%%P.env" realm-files\profiles\ >nul
copy /y "..\realm\modules.env" realm-files\ >nul
xcopy /e /i /q /y "..\realm\custom\lua_scripts" realm-files\lua_scripts >nul
for %%F in (brawl_world.sql brawl_world_2.sql main_unbrawl.sql main_world.sql modern_combos.sql) do if exist "..\realm\%%F" copy /y "..\realm\%%F" realm-files\sql\ >nul
powershell -NoProfile -Command "$k=(Get-Location).Path; $out=Join-Path (Split-Path $k -Parent) 'WrathUnleashed-host-kit.zip'; if(Test-Path $out){Remove-Item $out}; $tmp=Join-Path $env:TEMP 'wu-host-kit'; if(Test-Path $tmp){Remove-Item -Recurse -Force $tmp}; New-Item -ItemType Directory $tmp | Out-Null; robocopy $k (Join-Path $tmp 'WrathUnleashed host') /E /XD state cache __pycache__ /XF .env | Out-Null; Compress-Archive -Path (Join-Path $tmp '*') -DestinationPath $out; Write-Host ('kit: ' + $out)"
pause
