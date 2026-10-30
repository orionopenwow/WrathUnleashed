@echo off
title Leyline - close the Goldshire Inn guest pass
rem Switches the guest pass off: every open pass ends and guests are logged out. The accounts stay for next time.
ssh -i "%USERPROFILE%\.ssh\openwow" -o StrictHostKeyChecking=accept-new root@play.openvanilla.app "cd /srv/wrath/stream && bash demo-pool.sh off"
pause
