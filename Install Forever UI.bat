@echo off
setlocal EnableDelayedExpansion
title Forever UI for WrathUnleashed
rem One click: puts Forever UI (github.com/Adrestie/mod-forever-ui, GPL-2.0, by Adrestie) into
rem YOUR OWN WoW 3.3.5a folder and turns on its login screens in the browser client.
rem We do not ship Forever UI: its art comes from the modern WoW client, so it is fetched from its
rem author's page (or taken from a copy you already have) onto your PC only.
rem
rem   Install Forever UI.bat [WoW folder] [mod-forever-ui folder or zip]
rem
rem Turn it off any time: add ?foreverui=0 to the page address, or type /console foreverUI 0.
rem Remove it: delete Interface\AddOns\ForeverUI and Interface\ForeverUI in your WoW folder and
rem patch\Interface\GlueXML here.
cd /d "%~dp0"

set "WOW=%~1"
if "!WOW!"=="" if exist wow-folder.txt set /p WOW=<wow-folder.txt
if "!WOW!"=="" if exist players\wow-folder.txt set /p WOW=<players\wow-folder.txt
if not exist "!WOW!\Data\common.MPQ" (
  echo Where is your World of Warcraft 3.3.5a folder? ^(the one with Wow.exe and Data^)
  set /p WOW=Folder: 
  set "WOW=!WOW:"=!"
  if not exist "!WOW!\Data\common.MPQ" (echo That folder has no Data\common.MPQ. & goto fail)
)

rem 1. Find Forever UI: the folder or zip given, else download its author's current version.
set "SRC=%~2"
set "TMPD=%TEMP%\ForeverUI-install"
if exist "!TMPD!" rmdir /s /q "!TMPD!"
mkdir "!TMPD!"
if "!SRC!"=="" (
  echo Downloading Forever UI from github.com/Adrestie/mod-forever-ui ...
  powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing 'https://github.com/Adrestie/mod-forever-ui/archive/refs/heads/main.zip' -OutFile '!TMPD!\fui.zip'" || (echo The download failed. Download the repository as a zip yourself and pass it: "Install Forever UI.bat" "!WOW!" path\to\mod-forever-ui-main.zip & goto fail)
  set "SRC=!TMPD!\fui.zip"
)
if /i "!SRC:~-4!"==".zip" (
  powershell -NoProfile -Command "Expand-Archive -Force '!SRC!' '!TMPD!\x'" || (echo Could not unzip !SRC!. & goto fail)
  for /d %%d in ("!TMPD!\x\*") do if exist "%%d\data\addon\ForeverUI\ForeverUI.toc" set "SRC=%%d"
  if exist "!TMPD!\x\data\addon\ForeverUI\ForeverUI.toc" set "SRC=!TMPD!\x"
)
if not exist "!SRC!\data\addon\ForeverUI\ForeverUI.toc" (echo !SRC! is not a mod-forever-ui folder ^(no data\addon\ForeverUI^). & goto fail)

rem 2. The addon and its art into your WoW folder, where the page host serves them from.
echo Installing into !WOW!\Interface ...
xcopy /e /i /y /q "!SRC!\data\addon\ForeverUI" "!WOW!\Interface\AddOns\ForeverUI\" >nul || goto fail
xcopy /e /i /y /q "!SRC!\data\art\interface" "!WOW!\Interface\" >nul || goto fail
rem The login screens' files and art beside the stock ones (served because the archives lack
rem them; the copy of GlueXML.toc there is never read, the archives' own wins).
xcopy /e /i /y /q "!SRC!\data\glue\Interface" "!WOW!\Interface\" >nul || goto fail

rem 3. The one stock file it changes, GlueXML.toc (one appended line), goes in the patch folder,
rem    which the page host lays over your archives. ?foreverui=0 skips that line again.
if not exist patch\Interface\GlueXML mkdir patch\Interface\GlueXML
copy /y "!SRC!\data\glue\Interface\GlueXML\GlueXML.toc" patch\Interface\GlueXML\GlueXML.toc >nul || goto fail

if exist "!TMPD!" rmdir /s /q "!TMPD!"
>foreverui-installed.txt echo !WOW!
echo.
echo Done. Forever UI is on: reload the page (or start "Play WrathUnleashed.bat").
echo Stock look instead: add ?foreverui=0 to the address, or /console foreverUI 0 then /reload.
exit /b 0

:fail
if exist "!TMPD!" rmdir /s /q "!TMPD!"
echo.
echo Forever UI was not installed.
exit /b 1
