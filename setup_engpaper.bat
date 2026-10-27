@echo off
chcp 65001 >nul
setlocal
cd /d %~dp0

echo [1/4] Preparing virtual environment...
if not exist .venv\Scripts\python.exe (
  python -m venv .venv
  if errorlevel 1 (
    echo Python not found. Install Python 3.10+ and add it to PATH.
    pause
    exit /b 1
  )
)

if not exist config.json (
  if exist config.example.json copy /Y config.example.json config.json >nul
)

echo [2/4] Preparing pip...
.venv\Scripts\python.exe -m ensurepip --upgrade >nul 2>nul

echo [3/4] Installing dependencies...
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
  echo Dependency installation failed. Check network or proxy settings.
  pause
  exit /b 1
)

echo [4/4] Installing offline dictionary if available...
if exist data\ecdict-sqlite-28.zip (
  .venv\Scripts\python.exe tools\install_dict.py
) else (
  echo data\ecdict-sqlite-28.zip not found; run tools\install_dict.py later.
)

echo.
echo Setup complete. Double-click start_engpaper.bat to launch.
pause
