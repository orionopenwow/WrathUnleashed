@echo off
setlocal
title Leyline - restrict the GitHub deploy key (DRAFT)
rem DRAFT, not on the Autopilot list: the GitHub deploy key on the server becomes a one-command key
rem (restrict,command="/srv/wrath/luaup-ci.sh"), keeping the same key (no new GitHub secret). See ci-key-migrate.sh.
rem Dry run unless you add --apply:   "CI key - restrict (draft).bat" --apply
rem One SSH login with your usual key (root@play.openvanilla.app, %USERPROFILE%\.ssh\openwow).
cd /d "%~dp0"
for %%f in (ci-key-migrate.sh ..\..\server\luaup-ci.sh ..\..\realm\luaup.sh) do if not exist "%%f" (echo %%f is missing. & pause & exit /b 1)
set "ARG=%~1"
tar -cf - ci-key-migrate.sh -C ..\..\server luaup-ci.sh -C ..\realm luaup.sh | ssh -i "%USERPROFILE%\.ssh\openwow" -o StrictHostKeyChecking=accept-new root@play.openvanilla.app "rm -rf /tmp/wu-ci && mkdir -p /tmp/wu-ci && tar -x -C /tmp/wu-ci -f - && sed -i 's/\r$//' /tmp/wu-ci/*.sh && bash /tmp/wu-ci/ci-key-migrate.sh %ARG% 2>&1 | tee /tmp/wu-ci.log; rm -rf /tmp/wu-ci; grep -qE '^CI KEY (OK|DRY)' /tmp/wu-ci.log"
if errorlevel 1 (echo. & echo It did not finish; see above. & pause & exit /b 1)
pause
exit /b 0
