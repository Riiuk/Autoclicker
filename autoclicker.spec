# -*- mode: python ; coding: utf-8 -*-
"""Empaquetado con PyInstaller.

`--onedir`, no `--onefile`, y a propósito: un único ejecutable autoextraíble que además
instala un hook global de teclado es exactamente la firma heurística de dropper + keylogger,
y acaba en cuarentena de Defender casi seguro. Sin UPX y sin `uac_admin` por lo mismo.
"""

analisis = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets/autoclicker.ico', 'assets')],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    # Lista corta y conservadora: excluir de más provoca ModuleNotFoundError en el .exe,
    # que es justo lo que comprueba el primer paso del humo.
    excludes=['test', 'tests', 'unittest', 'pydoc_data', 'lib2to3', 'distutils',
              'setuptools', 'pip', 'numpy', 'PIL', 'matplotlib', 'pytest'],
    noarchive=False,
    optimize=2,
)

pyz = PYZ(analisis.pure)

exe = EXE(
    pyz,
    analisis.scripts,
    [],
    exclude_binaries=True,
    name='Autoclicker',
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
    icon='assets/autoclicker.ico',
    version='version_info.txt',
    uac_admin=False,
    # En PyInstaller 6 esto va en EXE, no en COLLECT: COLLECT lo lee del EXE que recibe.
    # Sin esto la carpeta interna se llama `_internal`.
    contents_directory='lib',
)

coleccion = COLLECT(
    exe,
    analisis.binaries,
    analisis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Autoclicker',
)
