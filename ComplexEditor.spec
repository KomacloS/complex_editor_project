# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_submodules

datas = [('src/complex_editor/assets/Empty_mdb.mdb', 'complex_editor/assets'), ('src/complex_editor/assets/empty_template.mdb', 'complex_editor/assets'), ('src/complex_editor/assets/MAIN_DB.mdb', 'complex_editor/assets'), ('src/complex_editor/assets/MAIN_DB_OLD.mdb', 'complex_editor/assets'), ('src/complex_editor/resources/functions_ref.txt', 'complex_editor/resources'), ('src/complex_editor/resources/default_config.yaml', 'complex_editor/resources'), ('src/complex_editor/resources/function_param_allowed.yaml', 'complex_editor/resources'), ('src/complex_editor/resources/function_param_allowed_old.yaml', 'complex_editor/resources'), ('src/complex_editor/resources/macro_aliases.yaml', 'complex_editor/resources'), ('src/complex_editor/data/learned_rules.json', 'complex_editor/data'), ('src/complex_editor/resources/functions_ref.txt', 'complex_editor/resources')]
hiddenimports = []
datas += collect_data_files('complex_editor')
hiddenimports += collect_submodules('complex_editor')


a = Analysis(
    ['src\\complex_editor\\__main__.py'],
    pathex=['src'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=True,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ComplexEditor',
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
    name='ComplexEditor',
)
