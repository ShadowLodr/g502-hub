@echo off
rem Starts G502 Hub without a console window, in UTF-8 mode like on Linux.
cd /d "%~dp0"
start "" pythonw -X utf8 -m g502hub.gui %*
