# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['maple_route_ui.py'],
    pathex=[],
    binaries=[],
    datas=[('config', 'config'), ('data', 'data')],
    hiddenimports=['cv2', 'mss', 'numpy', 'win32gui', 'win32api', 'win32con', 'win32ui', 'PIL'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MapleBot_v41',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MapleBot_v41',
)
