# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['cleave_cli.py'],
    pathex=[],
    binaries=[],
    datas=[('attention/model', 'attention/model')],
    hiddenimports=['encodings', 'cleavedb_server', 'cleavedb3_storage', 'cleaveql', 'cleaveql.interpreter', 'cleaveql.parser', 'cleaveql.lexer', 'cleaveql.tokens', 'cleaveql.security'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'cv2', 'PySide6', 'shiboken6', 'scipy', 'pandas', 'pyarrow', 'matplotlib', 'tkinter', 'tensorflow', 'tensorboard', 'keras', 'sklearn', 'grpc'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='cleaveshell',
    icon='cleavedb.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
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
    upx=True,
    upx_exclude=[],
    name='cleaveshell',
)
