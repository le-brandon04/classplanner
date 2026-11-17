# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build.  Run on Windows:   pyinstaller classplanner.spec

Produces dist/classplanner.exe.

The data/ folder is deliberately NOT bundled. The specification requires the
inputs to be separated from the software, so prereqs.json, offerings.json and
sections.json ship beside the executable where they can be edited. See
base_dir() in planner.py.

Tesseract is a system binary, not a Python package, so it is not bundled
either; the `parse` command needs it installed. `plan` and `check` do not.
"""
import os

import pulp as _pulp
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# PuLP ships the CBC solver as package data. Without collecting it the exe
# builds fine and then fails at solve time with "cbc not found".
#
# CBC then has to go in `binaries`, not `datas`: PyInstaller only marks
# `binaries` entries executable when it unpacks them. On Windows that makes no
# difference (there is no execute bit), but on Linux and macOS a CBC shipped
# as plain data extracts unreadable and every solve dies with
# "PULP_CBC_CMD: Not Available (check permissions on .../cbc)".
_pulp_files = collect_data_files("pulp")
binaries = [(src, dest) for src, dest in _pulp_files if "solverdir" in src]
datas = [(src, dest) for src, dest in _pulp_files if "solverdir" not in src]

# PuLP looks for the solver at  <pulp/apis>/../solverdir/cbc/...  . PyInstaller
# keeps pulp's modules inside the archive rather than on disk, so pulp/apis is
# never created as a real folder and that path cannot resolve - the file is
# there, but os.path.exists() says no because an intermediate component is
# missing. PuLP then reports "PULP_CBC_CMD: Not Available (check permissions)",
# which sends you looking at the wrong thing entirely.
#
# Putting one small file into pulp/apis/ creates the folder and the path
# resolves. Found by building and running the result; the build itself is
# perfectly happy without it.
_pulp_root = os.path.dirname(_pulp.__file__)
datas += [(os.path.join(_pulp_root, "apis", "__init__.py"), "pulp/apis")]

# cli.py reaches these through importlib, which PyInstaller's static analysis
# cannot follow. Without them the build succeeds and every command dies with
# ModuleNotFoundError at run time.
hiddenimports = (
    collect_submodules("pulp")
    + ["planner", "validator", "parse_audit_ocr", "export_excel"]
    + ["openpyxl", "pymupdf", "fitz", "pytesseract", "PIL", "PIL.Image"]
)

a = Analysis(
    ["cli.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="classplanner",
    debug=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)
