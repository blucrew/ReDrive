# rider.spec — PyInstaller spec for ReDrive Rider
# Build:  pyinstaller rider.spec

from PyInstaller.building.api import PYZ, EXE
from PyInstaller.building.build_main import Analysis
import os

block_cipher = None

# Icon — place a rider_icon.ico next to this spec to embed it
icon_path = 'rider_icon.ico' if os.path.exists('rider_icon.ico') else None

a = Analysis(
    ['rider_app.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'aiohttp',
        'aiosignal',
        'frozenlist',
        'multidict',
        'yarl',
        'aiohttp.connector',
        'aiohttp.client',
        'aiohttp.client_ws',
        'tkinter',
        'tkinter.ttk',
        'tkinter.filedialog',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter.test', 'unittest', 'email', 'xml', 'pydoc'],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zlib, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name='ReDriveRider',
    debug=False,
    strip=False,
    upx=True,
    console=False,     # no black console window
    icon=icon_path,
    version_info=None,
)
