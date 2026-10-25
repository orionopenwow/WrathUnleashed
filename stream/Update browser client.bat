@echo off
setlocal
title WrathUnleashed - update the streamed browser client
rem Sends the newest browser client (..\play\dist-test) and the stream scripts/sign-in page to the
rem server in ONE connection, then re-runs stream-up.sh (page edits, compressed copies, Caddy).
rem The slice itself is not re-sent. Players in game are not affected; new page loads get the new client.
cd /d "%~dp0"
set "W=%TEMP%\wu-client"
echo Packing the client...
if not exist "..\play\dist-test.tgz.part00" (echo ..\play\dist-test.tgz.part00 is missing. & pause & exit /b 1)
if exist "%W%" rmdir /s /q "%W%"
mkdir "%W%\kit\www-files" "%W%\kit\lua"
copy /b "..\play\dist-test.tgz.part00"+"..\play\dist-test.tgz.part01" "%W%\dist.tgz" >nul || goto fail
tar -xzf "%W%\dist.tgz" -C "%W%" || goto fail
move "%W%\dist-test" "%W%\kit\www" >nul || goto fail
rem The brotli copy of the client (smaller download), when the build came with one.
if exist "..\play\wenilla_bg.wasm.br" copy /y "..\play\wenilla_bg.wasm.br" "%W%\kit\www\" >nul
copy /y server\*.sh "%W%\kit\" >nul || goto fail
for %%f in (server\www-patch.py server\displays.py wrath_portal.py links.py) do copy /y "%%f" "%W%\kit\" >nul || goto fail
xcopy /e /i /q /y www-files "%W%\kit\www-files" >nul || goto fail
copy /y lua\*.* "%W%\kit\lua\" >nul || goto fail
tar -czf "%W%\kit.tgz" -C "%W%\kit" . || goto fail
echo Uploading the client (about 30 MB) and updating the server...
ssh -i "%USERPROFILE%\.ssh\openwow" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 root@play.openvanilla.app "cd /srv/wrath/stream && rm -rf www.new && mkdir www.new && tar -xzf - -C www.new && (cd www.new && for f in *.sh *.py wrath_portal.py; do [ -f $f ] && mv -f \"$f\" ..; done; rm -rf ../www-files && mv www-files ..; cp -f lua/* ../lua/; rm -rf lua) && rm -rf www.old && mv www www.old && mv www.new/www www && rm -rf www.new && sed -i 's/\r$//' *.sh && bash stream-up.sh" < "%W%\kit.tgz" || goto fail
rmdir /s /q "%W%"
echo.
echo Done. Open https://play.openvanilla.app/wrath and press Play now.
start "" https://play.openvanilla.app/wrath
pause
exit /b 0
:fail
echo.
echo Something failed above; the previous client keeps running.
pause
exit /b 1
