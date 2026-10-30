@echo off
setlocal
title WrathUnleashed - upload a mini slice
rem Uploads a slice folder you exported yourself (wenilla-host --export ... <folder>) to the server,
rem in place of /srv/wrath/stream/slices/mini, packed on the fly (no second copy anywhere).
rem "Make mini slice.bat" does this for you; use this one after a --record capture by hand.
rem   "Upload a mini slice.bat"                  uploads work\mini
rem   "Upload a mini slice.bat" "D:\my-slice"    uploads that folder
rem Uses your existing SSH key (.ssh\openwow), like "Deploy Wrath to my server.bat". One SSH
rem connection: the slice description (work\mini.json, else slices\mini.json) travels in the same tar.
cd /d "%~dp0"
set "KEY=%USERPROFILE%\.ssh\openwow"
set "HOST=root@play.openvanilla.app"
set "SSH=ssh -i "%KEY%" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 %HOST%"
set "SCP=scp -i "%KEY%""
set "SRC=%~1"
if "%SRC%"=="" set "SRC=%~dp0work\mini"
if not exist "%SRC%\DBFilesClient" (echo "%SRC%" is not an exported slice: it has no DBFilesClient folder. & pause & exit /b 1)
for %%I in ("%SRC%") do (set "PARENT=%%~dpI" & set "LEAF=%%~nxI")
set BYTES=0
for /f %%b in ('powershell -NoProfile -Command "(Get-ChildItem -Recurse -File -LiteralPath '%SRC%' | Measure-Object -Sum Length).Sum"') do set "BYTES=%%b"
echo Uploading %SRC% (%BYTES% bytes) as the "mini" slice...
if exist "%~dp0work\mini.json" (set "DESCDIR=%~dp0work") else (set "DESCDIR=%~dp0slices")
tar -cf - -C "%DESCDIR%" mini.json -C "%PARENT:~0,-1%" "%LEAF%" | %SSH% "if [ ! -f /srv/wrath/stream/slice-install.sh ]; then echo 'The streaming kit is not on the server yet: run Make mini slice.bat once.' >&2; exit 3; fi; mkdir -p /srv/wrath/stream/slices && bash /srv/wrath/stream/slice-install.sh mini %BYTES%" || goto fail
echo.
echo Done. If streaming is not up yet, on the server: bash /srv/wrath/stream/stream-up.sh
pause
exit /b 0
:fail
echo.
echo The upload failed. The slice on the server is unchanged unless the output above says otherwise.
pause
exit /b 1
