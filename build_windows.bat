@echo off
title ReDrive Rider — Windows Build
echo.
echo  ╔══════════════════════════════════════╗
echo  ║   ReDrive Rider — Windows Builder    ║
echo  ╚══════════════════════════════════════╝
echo.

:: ── Check Python ─────────────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found. Install Python 3.11+ from python.org
    pause & exit /b 1
)

:: ── Install / upgrade build deps ─────────────────────────────────────────────
echo  [1/4] Installing dependencies...
pip install --quiet --upgrade pyinstaller aiohttp aiosignal frozenlist multidict yarl
if errorlevel 1 ( echo  [ERROR] pip install failed. & pause & exit /b 1 )

:: ── Clean previous build ─────────────────────────────────────────────────────
echo  [2/4] Cleaning previous build...
if exist build\ReDriveRider  rmdir /s /q build\ReDriveRider
if exist dist\ReDriveRider.exe del /q dist\ReDriveRider.exe

:: ── PyInstaller ───────────────────────────────────────────────────────────────
echo  [3/4] Building executable (this takes ~60 seconds)...
pyinstaller rider.spec --noconfirm
if errorlevel 1 ( echo  [ERROR] PyInstaller failed. & pause & exit /b 1 )

if not exist dist\ReDriveRider.exe (
    echo  [ERROR] dist\ReDriveRider.exe not found after build.
    pause & exit /b 1
)

:: ── Inno Setup ───────────────────────────────────────────────────────────────
echo  [4/4] Building installer...
mkdir dist\installer 2>nul

:: Try common Inno Setup locations
set ISCC=
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe
if exist "C:\Program Files\Inno Setup 6\ISCC.exe"       set ISCC=C:\Program Files\Inno Setup 6\ISCC.exe

if "%ISCC%"=="" (
    echo.
    echo  [SKIP] Inno Setup not found — skipping installer packaging.
    echo  Install Inno Setup 6 from https://jrsoftware.org/isinfo.php
    echo  then re-run this script, or open installer.iss manually.
    echo.
    echo  Standalone exe is ready at: dist\ReDriveRider.exe
) else (
    "%ISCC%" installer.iss
    if errorlevel 1 ( echo  [ERROR] Inno Setup failed. & pause & exit /b 1 )
    echo.
    echo  ╔══════════════════════════════════════╗
    echo  ║  Installer ready:                    ║
    echo  ║  dist\installer\ReDriveRider-Setup   ║
    echo  ╚══════════════════════════════════════╝
)

echo.
pause
