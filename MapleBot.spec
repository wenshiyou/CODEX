# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['maple_route_ui.py'],
    pathex=[],
    binaries=[],
    datas=[('data', 'data'), ('ui_bg_blank.png', '.'), ('ui_tab_fight.png', '.'), ('ui_tab_potion.png', '.'), ('ui_tab_chat.png', '.'), ('ui_tab_lie.png', '.')],
    hiddenimports=[],
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
    name='MapleBot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
