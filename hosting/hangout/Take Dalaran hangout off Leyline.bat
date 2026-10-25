@echo off
rem Takes the Dalaran Hangout off Leyline (stops its agent, removes it from the realm lists). The realm itself keeps
rem running as always, and the hangout's key stays on the server: "Deploy Dalaran hangout.bat" brings the same one back.
call "%~dp0Deploy Dalaran hangout.bat" remove
