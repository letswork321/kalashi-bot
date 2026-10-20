@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
rem Optional override: full path to any working Python 3.12 executable.
if defined KALSHI_PYTHON goto custom_python
rem Prefer the user's official NuGet package. Keep the full tools directory intact.
set "botPython=%USERPROFILE%\Downloads\python.3.12.10\tools\python.exe"
if exist "%botPython%" goto found_python
rem Also support Python 3.12 installations without requiring the py launcher.
set "botPython=%LocalAppData%\Programs\Python\Python312\python.exe"
if exist "%botPython%" goto found_python
set "botPython=%ProgramFiles%\Python312\python.exe"
if exist "%botPython%" goto found_python
echo Python 3.12 was not found. Expected NuGet location:
echo "%USERPROFILE%\Downloads\python.3.12.10\tools\python.exe"
echo Keep the complete NuGet tools folder there, or set KALSHI_PYTHON to python.exe.
goto failed
:custom_python
set "botPython=%KALSHI_PYTHON%"
if exist "%botPython%" goto found_python
echo KALSHI_PYTHON points to a missing file. Set it to the full python.exe path.
goto failed
:found_python
"%botPython%" "%~dp0windows_v5.py"
if errorlevel 1 goto failed
exit /b 0
:failed
echo Setup or dashboard stopped with an error. Read the message above.
pause
exit /b 1
