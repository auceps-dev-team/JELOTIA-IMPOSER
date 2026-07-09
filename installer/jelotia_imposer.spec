# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file — JELOTIA IMPOSER
# Usage: pyinstaller installer/jelotia_imposer.spec

import sys
from pathlib import Path

block_cipher = None

# Collect hidden imports required by PySide6 and engines
hidden_imports = [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtCharts",
    "pyqtgraph",
    "fitz",
    "pikepdf",
    "reportlab",
    "reportlab.pdfgen",
    "reportlab.lib",
    "PIL",
    "PIL.Image",
    "rectpack",
    "shapely",
    "qrcode",
    "qrcode.image.pil",
    "watchdog",
    "watchdog.observers",
    "watchdog.events",
    "sqlalchemy",
    "sqlalchemy.dialects.sqlite",
    "alembic",
    "pydantic",
    "loguru",
    "cv2",
    "colour",
]

a = Analysis(
    ["../main.py"],
    pathex=[str(Path(SPECPATH).parent)],
    binaries=[],
    datas=[
        ("../config.json", "."),
        ("../src/database/migrations", "src/database/migrations"),
    ],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "notebook", "IPython"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="JelotiaImposer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # GUI app — no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="jelotia.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="JelotiaImposer",
)
