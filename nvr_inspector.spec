# -*- mode: python ; coding: utf-8 -*-

import os

import PySide6


project_root = os.path.abspath(os.path.dirname(SPEC))
icon_path = os.path.join(project_root, "image", "NvrAssistantLogo.ico")
version_info_path = os.path.join(project_root, "version_info.txt")

excluded_modules = [
    "bcrypt",
    "cffi",
    "cryptography",
    "_cffi_backend",
    "matplotlib",
    "numpy",
    "pandas",
    "PIL",
    "scipy",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtDesigner",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets",
]

a = Analysis(
    ["nvr_assistant.py"],
    pathex=[],
    binaries=[],
    datas=[(icon_path, "image")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules,
    noarchive=False,
    optimize=1,
)

# PyInstaller may collect the older VC runtime installed with Python and the
# build machine's UCRT alongside PySide6's newer runtime.  That mix can make
# QtGui fail on another Windows machine with "specified procedure not found".
# Keep one consistent runtime set and let the target OS provide UCRT.
runtime_dll_names = (
    "msvcp140.dll",
    "msvcp140_1.dll",
    "msvcp140_2.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
)
remove_binary_names = set(runtime_dll_names) | {"ucrtbase.dll"}

a.binaries = [
    entry
    for entry in a.binaries
    if os.path.basename(entry[0]).lower() not in remove_binary_names
    and not os.path.basename(entry[0]).lower().startswith("api-ms-win-crt-")
]

pyside_dir = os.path.dirname(PySide6.__file__)
for dll_name in runtime_dll_names:
    source = os.path.join(pyside_dir, dll_name)
    if os.path.exists(source):
        a.binaries.append((dll_name, source, "BINARY"))

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NVRInspector",
    debug=False,
    icon=icon_path,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=version_info_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="NVRInspector",
)

