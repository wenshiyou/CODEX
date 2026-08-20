# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['maple_route_ui.py'],
    pathex=[],
    binaries=[],
    datas=[('ui_bg_blank.png', '.'), ('ui_tab_fight.png', '.'), ('ui_tab_potion.png', '.'), ('ui_tab_chat.png', '.'), ('ui_tab_lie.png', '.'), ('data/templates', 'data/templates'), ('data/char_templates', 'data/char_templates'), ('data/ui_run.png', 'data'), ('data/ui_stop.png', 'data'), ('data/ui_platform.png', 'data'), ('data/ui_ladder.png', 'data'), ('data/ui_save.png', 'data'), ('data/ui_plan.png', 'data'), ('data/ui_platform_clear.png', 'data'), ('data/ui_ladder_clear.png', 'data'), ('data/ui_mode.png', 'data'), ('data/ui_plan_clear.png', 'data'), ('data/ui_char_btn.png', 'data'), ('data/ui_offset_label.png', 'data'), ('data/ui_monster_data.png', 'data'), ('data/ui_winbind_bg.png', 'data'), ('data/ui_crosshair.png', 'data'), ('data/ui_log_bg.png', 'data'), ('data/ui_refresh.png', 'data'), ('data/ui_manual.png', 'data'), ('data/ui_plan_toolbar.png', 'data'), ('data/ui_bound_dropdown.png', 'data'), ('best.onnx', '.'), ('config', 'config')],
    hiddenimports=['tkinter', 'tkinter.filedialog', 'ctypes', 'ctypes.wintypes'],
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
