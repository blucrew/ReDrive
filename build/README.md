# Building ReDrive Rider

## Windows
1. `pip install pyinstaller`
2. Install [Inno Setup 6](https://jrsoftware.org/isdl.php)
3. Run from repo root: `build\build_windows.bat`
4. Output: `build\dist\ReDriveRider-Setup.exe`

## macOS
1. `pip3 install pyinstaller`
2. Optionally: `brew install create-dmg` (nicer DMG, falls back to hdiutil)
3. `chmod +x build/build_mac.sh && bash build/build_mac.sh`
4. Output: `build/dist/ReDriveRider-x.x.x-mac.dmg`

## Linux
No build needed — riders run the script directly:
```bash
pip install aiohttp
python3 rider_app.py ROOMCODE
```
