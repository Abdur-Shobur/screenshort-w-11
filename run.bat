@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Setting up LightShort...
    py -3 -m venv .venv
    if errorlevel 1 goto fail
    ".venv\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt"
    if errorlevel 1 goto fail
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0main.py"
exit /b 0

:fail
echo Could not set up Python. Install Python 3 from python.org, then run this file again.
pause
exit /b 1
