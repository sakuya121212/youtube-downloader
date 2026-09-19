@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3.14 -m venv .venv
  if errorlevel 1 goto failed
)
.venv\Scripts\python.exe -c "import sys; sys.exit(sys.version_info[:2] != (3, 14) or sys.version_info < (3, 14, 7))"
if errorlevel 1 (
  echo Python 3.14.7+ in the 3.14 series is required. Rename the old .venv folder and run start.bat again.
  goto failed
)
.venv\Scripts\python.exe -m pip install --require-hashes --only-binary=:all: -r requirements.txt
if errorlevel 1 goto failed
.venv\Scripts\python.exe prepare_ffmpeg.py
if errorlevel 1 goto failed
.venv\Scripts\python.exe app.py
if errorlevel 1 goto failed
exit /b
:failed
echo Application failed. See the error above.
pause
