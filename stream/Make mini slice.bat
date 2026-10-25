@echo off
setlocal EnableDelayedExpansion
title WrathUnleashed - make and upload the streamed mini slice
rem Builds the "mini" slice of the game from YOUR 3.3.5a Data folder and uploads it to the server
rem (play.openvanilla.app, /srv/wrath/stream/slices/mini). No playing needed:
rem   1 uploads the streaming kit (scripts, the Linux host, the realm rule, the sign-in gate, the
rem     browser additions in www-files: "Play with my own game files" and "Download this section")
rem   2 asks the server which creatures and objects are spawned in the slice's places
rem   3 wenilla-host --deps   walks the game data: maps, tiles, models, textures, per tier
rem   4 wenilla-host --export copies those files out (item textures "lite"), tier by tier, until
rem     the 3 GB budget, and prints the size of each tier
rem   5 streams the slice and its description (the maxTier that fit) to the server in one go
rem     (no second copy on your disk or the server's)
rem Three SSH connections in all (the server pauses SSH after many quick logins).
rem The tier order is "order" in slices\mini.json: move a key up or down to change what streams first.
rem Then, on the server, once:  bash /srv/wrath/stream/stream-up.sh
rem
rem   "Make mini slice.bat"                         your Data folder below, tiers 0..maxTier of slices\mini.json
rem   "Make mini slice.bat" "D:\WoW 3.3.5a\Data" 4  another Data folder, tiers 0..4
rem Uses your existing SSH key (.ssh\openwow), like "Deploy Wrath to my server.bat".
cd /d "%~dp0"
set "KEY=%USERPROFILE%\.ssh\openwow"
set "HOST=root@play.openvanilla.app"
set "SSH=ssh -i "%KEY%" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 %HOST%"
set "SCP=scp -i "%KEY%""
set "DATA=%~1"
if "%DATA%"=="" set "DATA=C:\Users\campw\Downloads\World of Warcraft 3.3.5a\Data"
set "HOSTEXE=%~dp0bin\wenilla-host.exe"
set "W=%~dp0work"

if not exist "%DATA%\common.MPQ" if not exist "%DATA%\common-2.MPQ" (echo "%DATA%" is not a 3.3.5a Data folder. & pause & exit /b 1)
if not exist "%HOSTEXE%" (echo bin\wenilla-host.exe is missing. & pause & exit /b 1)
for /f %%t in ('powershell -NoProfile -Command "(Get-Content -Raw slices\mini.json | ConvertFrom-Json).maxTier"') do set "MAXTIER=%%t"
if not "%~2"=="" set "MAXTIER=%~2"
if "%MAXTIER%"=="" (echo Could not read maxTier from slices\mini.json. & pause & exit /b 1)
echo Data folder: %DATA%
echo Tiers:       0 to %MAXTIER%  (budget: budgetMB in slices\mini.json)

echo [1/5] Uploading the streaming kit (one connection: the server limits rapid SSH logins)...
if not exist "%W%" mkdir "%W%"
if exist "%W%\kit" rmdir /s /q "%W%\kit"
mkdir "%W%\kit" "%W%\kit\bin" "%W%\kit\lua" "%W%\kit\sql" "%W%\kit\slices" "%W%\kit\www-files"
copy /y server\*.sh "%W%\kit\" >nul || goto fail
copy /y server\displays.py "%W%\kit\" >nul || goto fail
copy /y server\www-patch.py "%W%\kit\" >nul || goto fail
copy /y www-files\*.js "%W%\kit\www-files\" >nul || goto fail
copy /y wrath_portal.py "%W%\kit\" >nul || goto fail
copy /y demo.py "%W%\kit\" >nul || goto fail
copy /y bin\wenilla-host "%W%\kit\bin\" >nul || goto fail
copy /y lua\ov_slices.lua "%W%\kit\lua\" >nul || goto fail
copy /y lua\lfg_ids.py "%W%\kit\lua\" >nul || goto fail
copy /y lua\tiers_lua.py "%W%\kit\lua\" >nul || goto fail
copy /y sql\ov_stream_accounts.sql "%W%\kit\sql\" >nul || goto fail
copy /y slices\mini.json "%W%\kit\slices\" >nul || goto fail
rem No www\ yet: use the newest browser client test build from ..\play (dist-test parts).
if not exist "www\index.html" if exist "..\play\dist-test.tgz.part00" (
  echo        unpacking the browser client from ..\play\dist-test ...
  copy /b "..\play\dist-test.tgz.part00"+"..\play\dist-test.tgz.part01" "%TEMP%\wu-dist-test.tgz" >nul || goto fail
  if exist "%TEMP%\wu-dist-test" rmdir /s /q "%TEMP%\wu-dist-test"
  mkdir "%TEMP%\wu-dist-test"
  tar -xzf "%TEMP%\wu-dist-test.tgz" -C "%TEMP%\wu-dist-test" || goto fail
  move "%TEMP%\wu-dist-test\dist-test" "www" >nul || goto fail
  del "%TEMP%\wu-dist-test.tgz"
)
rem The browser client goes along when it changed (delete www\.uploaded to send it again).
set "WWW=0"
if exist "www\index.html" if not exist "www\.uploaded" (
  echo        including the browser client from www\ ...
  xcopy /e /i /q /y www "%W%\kit\www" >nul || goto fail
  set "WWW=1"
)
tar -czf "%W%\kit.tgz" -C "%W%\kit" . || goto fail
rem The page edits (www-patch.py, via patch-index.sh) run whenever the server has a client build.
%SSH% "mkdir -p /srv/wrath/stream && cd /srv/wrath/stream && tar -xzf - && sed -i 's/\r$//' *.sh && chmod 755 *.sh bin/wenilla-host && if [ -f www/index.html ]; then bash patch-index.sh; fi" < "%W%\kit.tgz" || goto fail
if "%WWW%"=="1" echo uploaded> "www\.uploaded"

echo [2/5] Asking the server what is spawned in the slice...
if not exist "%W%" mkdir "%W%"
%SSH% "cd /srv/wrath/stream && python3 -I displays.py slices/mini.json --tiers 0-%MAXTIER%" > "%W%\displays.tsv" || goto fail
for /f %%n in ('find /c /v "" ^< "%W%\displays.tsv"') do echo        %%n creature and object displays

echo [3/5] Walking the game data (wenilla-host --deps)...
if exist "%W%\names" rmdir /s /q "%W%\names"
"%HOSTEXE%" --data "%DATA%" --deps slices\mini.json --tiers 0-%MAXTIER% --displays "%W%\displays.tsv" --out "%W%\names" || goto fail

echo [4/5] Exporting the slice (wenilla-host --export)...
set "LISTS="
set NBOOT=0
for %%m in (boot-manifest.json world-manifest.json) do if exist "slices\%%m" (set "LISTS=!LISTS! --boot "slices\%%m"" & set /a NBOOT+=1)
set "TIERS="
set NTIER=0
for /l %%i in (0,1,%MAXTIER%) do if exist "%W%\names\tier-%%i.txt" (set "TIERS=!TIERS! "%W%\names\tier-%%i.txt"" & set /a NTIER+=1)
rem Your own --record captures (record\names-*.txt) go last, so whatever the walk missed is added.
if exist "record\*.txt" for %%r in (record\*.txt) do set "TIERS=!TIERS! "%%r""
if exist "%W%\mini" rmdir /s /q "%W%\mini"
"%HOSTEXE%" --data "%DATA%" --slice slices\mini.json !LISTS! --export !TIERS! "%W%\mini" || goto fail
rem The highest tier that fit in the budget becomes the server's maxTier (lists = boot, tiers, records).
for /f %%t in ('powershell -NoProfile -Command "$r = Get-Content -Raw '%W%\mini\.export.json' | ConvertFrom-Json; $fit = @($r.lists | Select-Object -Skip %NBOOT% -First %NTIER% | Where-Object { -not $_.over_budget }).Count - 1; $s = Get-Content -Raw 'slices\mini.json' | ConvertFrom-Json; $s.maxTier = [Math]::Min([int]%MAXTIER%, $fit); [IO.File]::WriteAllText('%W%\mini.json', ($s | ConvertTo-Json -Depth 20)); $s.maxTier"') do set "FITTIER=%%t"
for /f %%b in ('powershell -NoProfile -Command "(Get-Content -Raw '%W%\mini\.export.json' | ConvertFrom-Json).bytes"') do set "BYTES=%%b"
if %FITTIER% LSS 1 (echo The base and Dalaran tiers alone are over the budget: raise budgetMB in slices\mini.json or trim tier 0's prefixes. & goto fail)
echo        tiers 0 to %FITTIER% fit; the server will hold those.

echo [5/5] Uploading the slice (it streams straight into place)...
tar -cf - -C "%W%" mini.json mini | %SSH% "bash /srv/wrath/stream/slice-install.sh mini %BYTES%" || goto fail

echo.
echo The mini slice is on the server (tiers 0 to %FITTIER%).
echo First time: on the server run   bash /srv/wrath/stream/stream-up.sh
echo (after the DNS record wrath.openvanilla.app points at the server).
pause
exit /b 0
:fail
echo.
echo Something failed above. Nothing on the server was switched over: players are not affected.
echo If it says "Connection timed out", the server is pausing SSH after many quick logins:
echo wait 2 minutes, then run this again.
pause
exit /b 1
