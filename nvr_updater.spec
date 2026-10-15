# -*- mode: python ; coding: utf-8 -*-

import os


project_root = os.path.abspath(os.path.dirname(SPEC))
icon_path = os.path.join(project_root, "image", "NvrAssistantLogo.ico")
version_info_path = os.path.join(
    project_root,
    "nvr_updater_version_info.txt",
)

a = Analysis(
    ["nvr_updater.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PySide6",
        "matplotlib",
        "numpy",
        "openpyxl",
        "pandas",
        "PIL",
        "requests",
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="NVRUpdater",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
    version=version_info_path,
)
