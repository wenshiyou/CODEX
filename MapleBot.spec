# -*- mode: python ; coding: utf-8 -*-
# onedir 模式：输出 dist/MapleBot/ 目录，内含 exe 和所有依赖（路径稳定）

a = Analysis(
    ['maple_route_ui.py'],
    pathex=[],
    binaries=[],
    datas=[('config', 'config'),
           ('data', 'data')],
    hiddenimports=['cv2', 'mss'],
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
    name='MapleBot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # v73防灰屏：upx压缩DLL会被Defender解压扫描导致冷启动极慢
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # console模式，避免灰屏，同时显示运行日志
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
    upx=False,  # v73防灰屏：upx压缩DLL会被Defender解压扫描导致冷启动极慢
    upx_exclude=[],
    name='MapleBot',
)
