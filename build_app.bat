@echo off
REM Build a standalone PlayStation Studio.exe (no Python needed to run it).
REM Run this on Windows (PyInstaller does not cross-compile).
setlocal
cd /d "%~dp0"

set PY=.venv\Scripts\python.exe
if not exist "%PY%" (
  echo Creating virtual environment...
  python -m venv .venv
  "%PY%" -m pip install --upgrade pip
  "%PY%" -m pip install -r requirements.txt
  "%PY%" -m pip install .\MkPFS
)

echo Installing build tooling (PyInstaller)...
"%PY%" -m pip install --quiet --upgrade pyinstaller pillow

echo Refreshing icons...
"%PY%" -m playstation_studio.assets.build_icons

echo Cleaning previous build output...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo Building... (first run bundles Qt; takes a few minutes)
"%PY%" -m PyInstaller --noconfirm playstation_studio.spec

echo.
echo Done.  Run:  "dist\PlayStation Studio\PlayStation Studio.exe"
endlocal
