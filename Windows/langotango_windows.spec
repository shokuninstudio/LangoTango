# -*- mode: python ; coding: utf-8 -*-
import sys
import os
from PyInstaller.utils.hooks import collect_data_files

# Get spellchecker data files
spellcheck_datas = collect_data_files('spellchecker')

a = Analysis(
    ['langotango_windows.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Add your splash image
        ('langotango_splash.png', '.'),
	# Add icon for taskbar
	('langotango.ico', '.'),
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
    a.binaries,
    a.datas,
    [],
    name='LangoTango',
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
    icon=['langotango.ico'],
)
