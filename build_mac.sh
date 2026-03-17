#!/bin/bash
echo "Building ReDrive Rider for macOS..."
pip3 install pyinstaller aiohttp
pyinstaller --onefile --windowed --name ReDriveRider rider_app.py
echo "Done. App bundle at dist/ReDriveRider"
