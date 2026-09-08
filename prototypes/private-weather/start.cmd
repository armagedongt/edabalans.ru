@echo off
setlocal
cd /d "%~dp0"
start "Weather server" /min py -m http.server 8765
start "" http://127.0.0.1:8765
