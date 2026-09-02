# -*- mode: python ; coding: utf-8 -*-
# v68 console鐗堬紝鎹㈠悕閬垮紑鏉€姣掕蒋浠舵爣璁?
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
    [],
    exclude_binaries=True,
    name='MapleBot_v90',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
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
    upx=False,
    upx_exclude=[],
    name='MapleBot_v90',
)











