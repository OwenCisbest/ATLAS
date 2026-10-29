# Build on Windows: python -m PyInstaller --noconfirm --clean ATLAS.spec
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = Path(SPECPATH)
data = collect_data_files('app')
if (root / 'assets').is_dir():
    data.append((str(root / 'assets'), 'assets'))
# PyInstaller's PySide6 hooks collect the matching Qt DLLs, plugins, WebEngine
# helper process, .pak resources, ICU data and locales. Do not copy Qt from PATH.
hidden = collect_submodules('keyring.backends') + [
    'keyring.backends.Windows', 'PySide6.QtWebEngineCore',
    'PySide6.QtWebEngineWidgets', 'PySide6.QtWebChannel',
]
a = Analysis([str(root / 'app' / 'main.py')], pathex=[str(root)],
             binaries=[], datas=data, hiddenimports=hidden,
             hookspath=[], runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ATLAS',
          debug=False, bootloader_ignore_signals=False, strip=False,
          upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='ATLAS')
