@echo off
rem The Leyline Sample Hangout's streamed slice (slices\sampler.json: mini.json less the capitals and the Goldshire
rem inn; Dalaran, the starting areas and every dungeon, raid, arena and battleground). Same steps and the same
rem 30-60 minutes as "Make mini slice.bat"; the server keeps the mini slice beside it and then serves this one
rem (slice-serve.sh sampler). Back to mini without rebuilding: on the server, bash /srv/wrath/stream/slice-serve.sh mini
rem (realm\sampler.sh off does it too).
rem   "Make sampler slice.bat" ["D:\Games\3.3.5a\Data"]
setlocal
set "WU_SLICE=sampler"
set "WU_SLICE_SERVE=1"
call "%~dp0Make mini slice.bat" %*
