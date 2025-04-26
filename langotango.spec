# -*- mode: python ; coding: utf-8 -*-
import sys
import os
from PyInstaller.utils.hooks import collect_data_files

# Get spellchecker data files
spellcheck_datas = collect_data_files('spellchecker')

a = Analysis(
    ['langotango.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Add your splash image
        ('langotango_splash.png', '.'),
        # Add spellchecker resources
        *spellcheck_datas,
    ],
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
    [],
    exclude_binaries=True,
    name='LangoTango',
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
    icon=['icon.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='LangoTango',
)
app = BUNDLE(
    coll,
    name='LangoTango.app',
    icon='icon.icns',
    bundle_identifier=None,
)
