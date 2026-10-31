@echo off
rem Takes Vanilla Remastered off Leyline (stops its agent, removes it from the realm lists, puts the 1.12 realm list
rem address back). The 1.12 game servers keep running (the ov112-realm-off step stops them); the key stays on the
rem server: "Put Vanilla Remastered on Leyline.bat" brings the same realm back.
call "%~dp0Put Vanilla Remastered on Leyline.bat" remove
