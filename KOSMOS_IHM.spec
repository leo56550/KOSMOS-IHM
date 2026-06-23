# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec pour KOSMOS IHM
# Usage : py -m PyInstaller KOSMOS_IHM.spec
#

import sys
from PyInstaller.utils.hooks import collect_all, collect_data_files

# ── Collecter les dépendances spéciales ────────────────────────────────────
# PyQt6-WebEngine a besoin de tous ses binaires (Chromium)
datas_web, binaries_web, hiddenimports_web = collect_all('PyQt6.QtWebEngineCore')

# pyqtgraph importe dynamiquement des modules de rendement
datas_pg, binaries_pg, hiddenimports_pg = collect_all('pyqtgraph')

# pandas — extensions C + data files
datas_pd, binaries_pd, hiddenimports_pd = collect_all('pandas')

# folium et ses templates HTML
datas_folium = collect_data_files('folium')
datas_branca = collect_data_files('branca')  # dépendance folium

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['C:\\KOSMOS_IHM'],
    binaries=binaries_web + binaries_pg + binaries_pd,
    datas=[
        # ── Fichiers propres au projet ─────────────────────────────────
        ('ihm2.ui',         '.'),          # Interface Qt Designer
        ('img',             'img'),        # Logos et drapeaux
        ('assets',          'assets'),     # Carte Leaflet HTML+JS
        ('template.json',   '.'),          # Template JSON vidéo

        # ── Dépendances collectées ────────────────────────────────────
        *datas_web,
        *datas_pg,
        *datas_pd,
        *datas_folium,
        *datas_branca,
    ],
    hiddenimports=[
        # PyQt6
        'PyQt6.QtWebEngineWidgets',
        'PyQt6.QtWebEngineCore',
        'PyQt6.QtWebChannel',
        'PyQt6.QtMultimedia',
        'PyQt6.QtMultimediaWidgets',
        'PyQt6.QtNetwork',
        'PyQt6.sip',

        # pyqtgraph backends
        *hiddenimports_web,
        *hiddenimports_pg,
        *hiddenimports_pd,

        # Calcul / vision
        'cv2',
        'numpy',
        'matplotlib',
        'matplotlib.backends.backend_qtagg',
        'matplotlib.backends.backend_pdf',
        'matplotlib.backends.backend_agg',
        'matplotlib.offsetbox',
        'matplotlib.gridspec',
        'matplotlib.figure',
        'paramiko',
        'paramiko.transport',
        'cryptography',

        # Bibliothèques réseau et web
        'requests',
        'folium',
        'branca',
        'jinja2',

        # Stdlib parfois manquants
        'pkg_resources',
        'email.mime.text',
        'email.mime.multipart',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'PyQt5',
        'PySide2',
        'PySide6',
        'PyOpenGL',
        'IPython',
        'notebook',
        'scipy',
    ],
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
    name='KOSMOS_IHM',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX casse parfois les DLL Qt — désactivé
    console=True,       # DEBUG — affiche le traceback
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='img\\logo_kosmos.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='KOSMOS_IHM',
)
