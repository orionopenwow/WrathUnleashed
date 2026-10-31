@echo off
setlocal
title Leyline - set up automatic deploys (one time)
rem One time: lets GitHub deploy realm scripts to the live realm after the tests pass (your standing rule).
rem   1. makes a new SSH key just for deploys (this PC, a temp folder),
rem   2. adds its public half to the server, marked restrict,command="/srv/wrath/luaup-ci.sh": the key can do ONE thing,
rem      hand realm scripts the realm already runs to luaup-ci.sh (server\luaup-ci.sh), which reloads them live.
rem      No shell, no port forwarding, no agent. An older deploy key line (wu-deploy-github-actions) is replaced.
rem   3. stores the private half as the GitHub secret WU_DEPLOY_SSH_KEY (plus the server's host key),
rem   4. deletes the temp copy. The key never leaves your PC except into GitHub's secret store.
rem Two SSH logins with your usual key. Needs: GitHub CLI signed in (winget install GitHub.cli, then: gh auth login), your usual server key.
rem In setup\ since 2026-10-30: everything below runs from the workspace folder one level up.
cd /d "%~dp0.."
set "ROOT=%CD%"
rem The private repo: leyline-workspace since the move to Leyline renamed it (was WrathUnleashed).
set "REPO=orionopenwow/leyline-workspace"
set "KEY=%USERPROFILE%\.ssh\openwow"
where gh >nul 2>&1 || (echo GitHub CLI is missing. Install it: winget install GitHub.cli   then: gh auth login & pause & exit /b 1)
gh auth status >nul 2>&1 || (echo GitHub CLI is not signed in. Run: gh auth login & pause & exit /b 1)
gh repo view %REPO% --json name >nul 2>&1 || set "REPO=orionopenwow/WrathUnleashed"
where ssh-keygen >nul 2>&1 || (echo ssh-keygen is missing (Windows OpenSSH client). & pause & exit /b 1)
set "T=%TEMP%\wu-deploykey"
if exist "%T%" rmdir /s /q "%T%"
mkdir "%T%"
ssh-keygen -q -t ed25519 -N "" -C "wu-deploy-github-actions" -f "%T%\deploy" || (echo Could not make the key. & pause & exit /b 1)
for %%f in (server\luaup-ci.sh realm\luaup.sh) do if not exist "%%f" (echo %%f is missing. & rmdir /s /q "%T%" & pause & exit /b 1)
echo Installing the deploy command on the server (luaup-ci.sh, luaup.sh)...
tar -cf - -C server luaup-ci.sh -C ..\realm luaup.sh | ssh -i "%KEY%" -o StrictHostKeyChecking=accept-new root@play.openvanilla.app "T=$(mktemp -d) && tar -x -C $T -f - && sed -i 's/\r$//' $T/luaup-ci.sh $T/luaup.sh && install -m 755 $T/luaup-ci.sh /srv/wrath/luaup-ci.sh && install -m 755 $T/luaup.sh /srv/wrath/luaup.sh && rm -rf $T && echo CMD OK" | findstr /c:"CMD OK" >nul || (echo Could not install luaup-ci.sh on the server. & rmdir /s /q "%T%" & pause & exit /b 1)
echo Adding the deploy key to the server (one SSH login)...
ssh -i "%KEY%" -o StrictHostKeyChecking=accept-new root@play.openvanilla.app "mkdir -p ~/.ssh && chmod 700 ~/.ssh && read -r k && (cp -p ~/.ssh/authorized_keys ~/.ssh/authorized_keys.before-ci 2>/dev/null; sed -i '/ wu-deploy-github-actions$/d' ~/.ssh/authorized_keys 2>/dev/null; true) && echo 'restrict,command=\"/srv/wrath/luaup-ci.sh\" '\"$k\" >> ~/.ssh/authorized_keys; chmod 600 ~/.ssh/authorized_keys; echo KEY OK" < "%T%\deploy.pub" | findstr /c:"KEY OK" >nul || (echo The server did not take the key. & rmdir /s /q "%T%" & pause & exit /b 1)
ssh-keyscan -t ed25519,rsa play.openvanilla.app > "%T%\known_hosts" 2>nul
gh secret set WU_DEPLOY_SSH_KEY -R %REPO% < "%T%\deploy" || (echo Could not set the GitHub secret. & rmdir /s /q "%T%" & pause & exit /b 1)
gh secret set WU_KNOWN_HOSTS -R %REPO% < "%T%\known_hosts" || (echo Could not set WU_KNOWN_HOSTS. & rmdir /s /q "%T%" & pause & exit /b 1)
rmdir /s /q "%T%"
echo.
echo Done. GitHub can now deploy realm scripts after the tests pass (Actions tab: "realm scripts").
echo Its key can only hand scripts to /srv/wrath/luaup-ci.sh: no shell on the server.
echo To turn it off: delete the WU_DEPLOY_SSH_KEY secret on GitHub, or remove the "wu-deploy-github-actions" line
echo from /root/.ssh/authorized_keys on the server.
pause
exit /b 0
