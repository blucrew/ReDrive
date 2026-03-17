@echo off
REM ── ReDrive Rider — Windows build script ──────────────────────────────────
REM Requires: pip install pyinstaller
REM           Inno Setup 6 installed at default location

set NAME=ReDriveRider
set VERSION=0.1.0

echo === Building %NAME% v%VERSION% ===

REM Step 1: PyInstaller
pyinstaller --noconfirm --onefile --windowed ^
  --name %NAME% ^
  --icon build\icon.ico ^
  ..\rider_app.py

if errorlevel 1 (
  echo PyInstaller failed.
  exit /b 1
)

REM Step 2: Inno Setup
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" build\installer.iss
if errorlevel 1 (
  echo Inno Setup failed.
  exit /b 1
)

echo.
echo === Done: dist\ReDriveRider-Setup.exe ===
