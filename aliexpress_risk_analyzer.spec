# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for AliExpress Risk Analyzer
Build: pyinstaller aliexpress_risk_analyzer.spec
"""

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Collect hidden imports for dynamic imports in app.py
hidden_imports = [
    'detectors', 'detectors.text_prohibited', 'detectors.text_contact_leak',
    'detectors.html_structure', 'detectors.brand_check', 'detectors.search_cheating',
    'detectors.image_analysis', 'detectors.category_mismatch', 'detectors.fda_claims',
    'utils', 'utils.html_parser', 'utils.text_utils', 'utils.json_utils',
    'utils.image_fetch', 'utils.excel_io', 'utils.ai_client', 'utils.category_loader',
    'rule_index', 'risk_evaluator', 'output_writer',
    'openpyxl', 'bs4', 'lxml', 'urllib3',
]

# Data files to bundle (templates, static, data, Clippings rules, batch launcher)
datas = [
    ('templates', 'templates'),
    ('static', 'static'),
    ('data', 'data'),
    ('Clippings', 'Clippings'),
    ('启动批量分析.bat', '.'),
]

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='aliexpress_risk_analyzer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
