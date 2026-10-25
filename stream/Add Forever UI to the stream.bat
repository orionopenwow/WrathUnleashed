@echo off
setlocal EnableDelayedExpansion
title WrathUnleashed - add Forever UI to the streamed browser client
rem Puts Forever UI (github.com/Adrestie/mod-forever-ui, GPL-2.0, by Adrestie) into the streamed
rem "mini" slice at wrath.openvanilla.app, so browser players get the same look as your own install.
rem Its art comes from the modern WoW client: it goes ONLY into the gated stream (served by wu-play
rem behind the sign-in, like the slice itself), never anywhere public.
rem
rem   "Add Forever UI to the stream.bat"                      from your WoW folder (Install Forever UI.bat)
rem   "Add Forever UI to the stream.bat" D:\path\mod-forever-ui-main.zip   or a repo zip / .tgz / folder
rem
rem Where it takes Forever UI from, first found:
rem   1 the folder or zip you give it
rem   2 your WoW folder (foreverui-installed.txt, wow-folder.txt), as Install Forever UI.bat put it there
rem   3 fui-src.tgz in the WrathUnleashed folder
rem   4 its author's current version from GitHub
rem Only Forever UI's own files go up: Interface\AddOns\ForeverUI, its art (Interface\ForeverUI), its
rem login-screen files (Interface\GlueXML\ForeverUI*). The server adds its one line to GlueXML.toc
rem itself, from the slice's own copy. ONE SSH connection (the server pauses SSH after many logins).
rem Run it again any time (a newer Forever UI replaces the old). Undo: "Remove Forever UI from the stream.bat".
rem Players who want the stock look add ?foreverui=0 to the page address.
cd /d "%~dp0"
set "KEY=%USERPROFILE%\.ssh\openwow"
set "HOST=root@play.openvanilla.app"
set "SSH=ssh -i "%KEY%" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 %HOST%"
set "KIT=%~dp0server"
for %%f in (fui-install.sh fui-overlay.py slice-install.sh patch-index.sh) do if not exist "%KIT%\%%f" (echo server\%%f is missing next to this file. & goto fail)

rem The WrathUnleashed folder (where Install Forever UI.bat keeps foreverui-installed.txt).
set "WU="
for %%d in ("%~dp0." "%~dp0.." "%~dp0..\.." "%USERPROFILE%\Desktop\WrathUnleashed") do (
  if not defined WU if exist "%%~fd\foreverui-installed.txt" set "WU=%%~fd"
)
for %%d in ("%~dp0." "%~dp0.." "%~dp0..\.." "%USERPROFILE%\Desktop\WrathUnleashed") do (
  if not defined WU if exist "%%~fd\Install Forever UI.bat" set "WU=%%~fd"
)

set "TMPD=%TEMP%\fui-stream-src"
set "STG=%TEMP%\fui-stream-up"
if exist "!TMPD!" rmdir /s /q "!TMPD!"
mkdir "!TMPD!"

rem 1. Find Forever UI.
set "SRC=%~1"
set "MODE="
if not "!SRC!"=="" (
  call :unpack "!SRC!" || goto fail
  if not defined MODE if exist "!SRC!\data\addon\ForeverUI\ForeverUI.toc" set "MODE=repo"
  if not defined MODE if exist "!SRC!\Interface\AddOns\ForeverUI\ForeverUI.toc" set "MODE=wow"
  if not defined MODE (echo !SRC! is neither a mod-forever-ui folder or zip nor a WoW folder with Forever UI installed. & goto fail)
)
if not defined MODE if defined WU (
  for %%t in ("!WU!\foreverui-installed.txt" "!WU!\wow-folder.txt" "!WU!\players\wow-folder.txt") do (
    if not defined MODE if exist "%%~t" (
      set "W="
      set /p W=<"%%~t"
      if defined W if exist "!W!\Interface\AddOns\ForeverUI\ForeverUI.toc" (set "SRC=!W!" & set "MODE=wow")
    )
  )
)
if not defined MODE (
  for %%t in ("!WU!\fui-src.tgz" "%USERPROFILE%\Desktop\WrathUnleashed\fui-src.tgz") do (
    if not defined MODE if exist "%%~t" (
      call :unpack "%%~t" || echo   ^(not Forever UI: trying the next place^)
    )
  )
)
if not defined MODE (
  echo Downloading Forever UI from github.com/Adrestie/mod-forever-ui ...
  powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing 'https://github.com/Adrestie/mod-forever-ui/archive/refs/heads/main.zip' -OutFile '!TMPD!\fui.zip'" || (echo The download failed. Download the repository as a zip and pass it to this file. & goto fail)
  call :unpack "!TMPD!\fui.zip" || goto fail
)
if not defined MODE (echo Could not find Forever UI anywhere. & goto fail)
echo Forever UI from: !SRC!

rem 2. Only Forever UI's files, in game-path layout (Interface\...), plus the server scripts.
if exist "!STG!" rmdir /s /q "!STG!"
mkdir "!STG!\kit" "!STG!\foreverui\Interface\AddOns\ForeverUI" "!STG!\foreverui\Interface\ForeverUI" "!STG!\foreverui\Interface\GlueXML"
for %%f in (fui-install.sh fui-overlay.py slice-install.sh patch-index.sh) do copy /y "%KIT%\%%f" "!STG!\kit\" >nul || goto fail
set "F=!STG!\foreverui\Interface"
if "!MODE!"=="repo" (
  xcopy /e /i /y /q "!SRC!\data\addon\ForeverUI" "!F!\AddOns\ForeverUI\" >nul || goto fail
  xcopy /e /i /y /q "!SRC!\data\art\interface\foreverui" "!F!\ForeverUI\" >nul || goto fail
  copy /y "!SRC!\data\glue\Interface\GlueXML\ForeverUI*.*" "!F!\GlueXML\" >nul || goto fail
  copy /y "!SRC!\data\glue\Interface\GlueXML\GlueXML.toc" "!F!\GlueXML\" >nul
  if exist "!SRC!\LICENSE" copy /y "!SRC!\LICENSE" "!F!\AddOns\ForeverUI\LICENSE-GPL-2.0.txt" >nul
) else (
  xcopy /e /i /y /q "!SRC!\Interface\AddOns\ForeverUI" "!F!\AddOns\ForeverUI\" >nul || goto fail
  if not exist "!SRC!\Interface\ForeverUI" (echo !SRC!\Interface\ForeverUI ^(its art^) is missing: run Install Forever UI.bat again, or pass the repo zip. & goto fail)
  xcopy /e /i /y /q "!SRC!\Interface\ForeverUI" "!F!\ForeverUI\" >nul || goto fail
  copy /y "!SRC!\Interface\GlueXML\ForeverUI*.*" "!F!\GlueXML\" >nul || goto fail
  if defined WU if exist "!WU!\patch\Interface\GlueXML\GlueXML.toc" copy /y "!WU!\patch\Interface\GlueXML\GlueXML.toc" "!F!\GlueXML\" >nul
)
rem WrathUnleashed (fui-glue): its own fixes to the login screens (no logo, top bar, character
rem select layout), from stream\fui-web next to this file. fui-overlay.py lists
rem ForeverUIGlueWeb.xml in GlueXML.toc right after ForeverUIGlue.xml.
if exist "%~dp0fui-web\Interface\GlueXML\ForeverUIGlueWeb.xml" copy /y "%~dp0fui-web\Interface\GlueXML\ForeverUIGlueWeb.*" "!F!\GlueXML\" >nul || goto fail
rem WrathUnleashedUI (fui-web\Interface\AddOns): our in-game defaults (every action bar on, a level 80's bars filled).
if exist "%~dp0fui-web\Interface\AddOns\WrathUnleashedUI\WrathUnleashedUI.toc" xcopy /e /i /y /q "%~dp0fui-web\Interface\AddOns\WrathUnleashedUI" "!F!\AddOns\WrathUnleashedUI\" >nul || goto fail
if not exist "!F!\GlueXML\ForeverUIGlue.xml" (echo Forever UI's login screens ^(ForeverUIGlue.xml^) are missing from !SRC!. & goto fail)
for /f %%b in ('powershell -NoProfile -Command "(Get-ChildItem -Recurse -File '!STG!' | Measure-Object Length -Sum).Sum"') do set "BYTES=%%b"
for /f %%n in ('powershell -NoProfile -Command "(Get-ChildItem -Recurse -File '!STG!\foreverui').Count"') do set "NFILES=%%n"
for /f %%m in ('powershell -NoProfile -Command "[math]::Round(!BYTES! / 1MB)"') do set "MB=%%m"
echo Packing !NFILES! files ^(about !MB! MB^)...

rem 3. One SSH: the tar goes in on stdin; the server checks its disk, unpacks, backs up and lays it over.
set "REMOTE=set -e; ST=/srv/wrath/stream; test -f $ST/stream-lib.sh || { echo The streaming kit is not on the server yet: run Make mini slice.bat first.; exit 1; }; mkdir -p $ST/overlays; need=$((!BYTES! + 2147483648)); avail=$(( $(df --output=avail -k $ST/overlays | tail -1) * 1024 )); if [ $avail -lt $need ]; then echo Not enough disk on the server: $((avail/1048576)) MB free, $((need/1048576)) MB needed.; exit 1; fi; U=$(mktemp -d $ST/overlays/.upload.XXXXXX); trap 'rm -rf $U' EXIT; tar -x -C $U -f - --no-same-owner --no-same-permissions; sed -i 's/\r$//' $U/kit/*.sh; bash $U/kit/fui-install.sh install $U"
echo Uploading to the stream (one connection)...
rem (%%-expansion here, not !: the two sides of a pipe run in new cmd instances without delayed expansion)
tar -cf - -C "%STG%" kit foreverui | %SSH% "%REMOTE%" || goto fail

if exist "!STG!" rmdir /s /q "!STG!"
if exist "!TMPD!" rmdir /s /q "!TMPD!"
echo.
echo Done. Forever UI is in the streamed client: reload https://wrath.openvanilla.app
echo (stock look for one visit: add ?foreverui=0 to the address).
echo Keep server\slice-install.sh and server\patch-index.sh from this kit in your stream folder:
echo "Make mini slice.bat" uploads them, and they put Forever UI back over every new slice.
pause
exit /b 0

rem Unpack a .zip / .tgz into TMPD and point SRC at the mod-forever-ui folder in it (MODE=repo).
rem A folder is left alone.
:unpack
set "A=%~1"
if not exist "!A!" (echo !A! does not exist. & exit /b 1)
set "X="
if /i "!A:~-4!"==".zip" set "X=1"
if /i "!A:~-4!"==".tgz" set "X=1"
if /i "!A:~-7!"==".tar.gz" set "X=1"
if not defined X exit /b 0
if exist "!TMPD!\x" rmdir /s /q "!TMPD!\x"
mkdir "!TMPD!\x"
tar -xf "!A!" -C "!TMPD!\x" 2>nul || powershell -NoProfile -Command "Expand-Archive -Force '!A!' '!TMPD!\x'" || (echo Could not unpack !A!. & exit /b 1)
if exist "!TMPD!\x\data\addon\ForeverUI\ForeverUI.toc" (set "SRC=!TMPD!\x" & set "MODE=repo" & exit /b 0)
for /d %%d in ("!TMPD!\x\*") do if not defined MODE if exist "%%~d\data\addon\ForeverUI\ForeverUI.toc" (set "SRC=%%~d" & set "MODE=repo")
if not defined MODE (echo !A! holds no mod-forever-ui folder ^(data\addon\ForeverUI^). & exit /b 1)
exit /b 0

:fail
if exist "%TEMP%\fui-stream-up" rmdir /s /q "%TEMP%\fui-stream-up"
if exist "%TEMP%\fui-stream-src" rmdir /s /q "%TEMP%\fui-stream-src"
echo.
echo Forever UI was not added. The stream is unchanged.
echo If it says "Connection timed out", the server is pausing SSH after many quick logins:
echo wait 2 minutes, then run this again.
pause
exit /b 1
