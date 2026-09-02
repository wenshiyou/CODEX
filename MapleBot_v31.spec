# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['maple_route_ui.py'],
    pathex=[],
    binaries=[],
    datas=[('C:\\Users\\PC\\Doubao\\chats\\2026-08-15\\new-chat-4\\maple_bot\\config', 'config'),
           ('C:\\Users\\PC\\Doubao\\chats\\2026-08-15\\new-chat-4\\maple_bot\\data', 'data')],
    hiddenimports=['ultralytics', 'cv2', 'mss', 'sklearn'],
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
    a.binaries,
    a.datas,
    [],
    name='MapleBot_v31',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
