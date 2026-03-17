# rider.spec — PyInstaller spec for ReDrive Rider
# Build:  pyinstaller rider.spec

from PyInstaller.building.api import PYZ, EXE
from PyInstaller.building.build_main import Analysis

block_cipher = None

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
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter.test'],
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
    console=False,   # no console window
    icon=None,
)
