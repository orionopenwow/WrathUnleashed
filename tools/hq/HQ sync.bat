@echo off
rem Leyline HQ sync: the Autopilot steps hq-sync, hqnote and hq-inbox (Leyline Control also runs it after every run).
rem  1. Builds the recent changes (step names and outcomes, never log lines) and Claude's notes (control\hq-notes.json).
rem  2. Uploads both to the website's HQ folder (/srv/wrath/portal-data/hq), one atomic rename each.
rem  3. Downloads the owner's notes to Claude into control\notes-from-owner.json.
rem One upload and one SSH login. Changes nothing else on the server.
setlocal
cd /d "%~dp0..\.."
set PY=py -3
where py >nul 2>&1 || set PY=python
set "KEY=%USERPROFILE%\.ssh\openwow"
set "HOST=root@play.openvanilla.app"
set "OPTS=-i "%KEY%" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ConnectTimeout=20"
set "OUT=%TEMP%\leyline-hq"
set "TAG=lhq-%RANDOM%%RANDOM%"
if not exist "%KEY%" (echo SSH key %KEY% not found. & exit /b 1)
%PY% "tools\hq\hq_sync.py" build "%OUT%" || exit /b 1
echo [1/2] Uploading to Leyline HQ...
scp %OPTS% "%OUT%\changes.json" %HOST%:/tmp/%TAG%-changes.json || (echo Upload failed. & exit /b 1)
scp %OPTS% "%OUT%\claude-notes.json" %HOST%:/tmp/%TAG%-notes.json || (echo Upload failed. & exit /b 1)
echo [2/2] Placing it and fetching the owner's notes...
ssh %OPTS% %HOST% "set -e; D=/srv/wrath/portal-data/hq; install -d -m 755 $D; python3 -I -c 'import json,sys;[json.load(open(p)) for p in sys.argv[1:]]' /tmp/%TAG%-changes.json /tmp/%TAG%-notes.json; install -m 644 /tmp/%TAG%-changes.json $D/.changes.json; mv -f $D/.changes.json $D/changes.json; install -m 644 /tmp/%TAG%-notes.json $D/.claude-notes.json; mv -f $D/.claude-notes.json $D/claude-notes.json; rm -f /tmp/%TAG%-changes.json /tmp/%TAG%-notes.json; cat $D/owner-notes.jsonl 2>/dev/null || true; date -u +%%Y-%%m-%%dT%%H:%%M:%%SZ > $D/picked-up-at" > "%OUT%\owner-notes.jsonl" || (echo The server did not take it. & exit /b 1)
%PY% "tools\hq\hq_sync.py" inbox "%OUT%\owner-notes.jsonl" || exit /b 1
del /q "%OUT%\owner-notes.jsonl" 2>nul
echo HQ sync: done.
exit /b 0
