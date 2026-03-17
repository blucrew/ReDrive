@echo off
echo Building ReDrive Rider for Windows...
pip install pyinstaller aiohttp
pyinstaller rider.spec
echo Done. Installer input ready at dist\ReDriveRider.exe
echo Now run Inno Setup on installer.iss to create the installer.
pause
