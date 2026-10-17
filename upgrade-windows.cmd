@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
set "botPython=%USERPROFILE%\Downloads\python.3.12.10\tools\python.exe"
if defined KALSHI_PYTHON set "botPython=%KALSHI_PYTHON%"
if not exist "%botPython%" goto missing
"%botPython%" "%~dp0install_upgrade.py"
set "upgradeResult=%ERRORLEVEL%"
pause
exit /b %upgradeResult%
:missing
echo NuGet Python was not found. Keep the complete Python tools folder in Downloads.
pause
exit /b 1
