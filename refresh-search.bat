@echo off
REM One-click: pull the latest archive, rebuild the offline search page, open it.
REM Double-click this file (or a desktop shortcut to it). Nothing leaves your PC.
setlocal
cd /d "%~dp0"
set ARCHIVE=%~dp0..\podcast-archive

echo.
echo  Fetching the latest transcripts and news...
git -C "%ARCHIVE%" pull --quiet
if errorlevel 1 (
  echo  Could not reach GitHub - building from what is already on this PC.
)

echo  Building the search page ^(this takes a few seconds^)...
".venv\Scripts\python.exe" "src\build_search.py" --archive "%ARCHIVE%"
if errorlevel 1 goto failed

echo  Opening it in your browser.
start "" "%ARCHIVE%\search.html"
exit /b 0

:failed
echo.
echo  Something went wrong above. Copy the message and ask Claude about it.
echo.
pause
exit /b 1
