@echo off
rem Sends portal\wrath_portal.py (the play.openvanilla.app/wrath page) to the server and restarts it.
rem One SSH connection. Players in game are not affected.
cd /d "%~dp0"
ssh -i "%USERPROFILE%\.ssh\openwow" -o StrictHostKeyChecking=accept-new root@play.openvanilla.app "cat > /srv/wrath/portal/wrath_portal.py.new && python3 -m py_compile /srv/wrath/portal/wrath_portal.py.new && mv /srv/wrath/portal/wrath_portal.py.new /srv/wrath/portal/wrath_portal.py && docker restart wu-portal >/dev/null && echo The sign-in page is updated." < portal\wrath_portal.py || (echo The update failed; the old page is still running. & pause & exit /b 1)
start "" https://play.openvanilla.app/wrath
pause
