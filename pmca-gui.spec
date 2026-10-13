# macOS/Apple Silicon: python tools/build_macos.py
# Other platforms: python -m PyInstaller pmca-gui.spec
from ctypes.util import find_library
from pathlib import Path
import platform
import sys

root = Path(SPECPATH)
mac = sys.platform == 'darwin'
if mac and platform.machine() != 'arm64':
    raise SystemExit('Build the macOS app with native arm64 Python on Apple Silicon.')

binaries = []
if mac:
    library = find_library('usb-1.0')
    if not library or not Path(library).is_file():
        raise SystemExit('libusb not found. Run: brew install libusb')
    binaries.append((library, '.'))

a = Analysis(
    [str(root / 'pmca-gui.py')],
    pathex=[str(root)],
    binaries=binaries,
    datas=[(str(root / 'certs'), 'certs'),
           (str(root / 'updatershell' / 'fdat'), 'updatershell/fdat')],
    hiddenimports=['usb.backend.libusb1', 'usb.backend.libusb0',
                   'pmca.usb.driver.generic.qemu'],
    excludes=['tkinter', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets'],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name='ILCE Toolkit', console=False,
    target_arch='arm64' if mac else None,
    icon=str(root / 'build' / 'ILCEToolkit.icns') if mac and (root / 'build' / 'ILCEToolkit.icns').exists() else None,
)
collection = COLLECT(exe, a.binaries, a.datas, name='ILCE Toolkit')
if mac:
    app = BUNDLE(
        collection, name='ILCE Toolkit.app',
        icon=str(root / 'build' / 'ILCEToolkit.icns') if (root / 'build' / 'ILCEToolkit.icns').exists() else None,
        bundle_identifier='com.casklabs.ilce-toolkit',
        info_plist={
            'CFBundleName': 'ILCE Toolkit',
            'CFBundleDisplayName': 'ILCE Toolkit',
            'CFBundleShortVersionString': '0.1.0',
            'CFBundleVersion': '1',
            'LSMinimumSystemVersion': '14.0',
            'NSHighResolutionCapable': True,
            'NSHumanReadableCopyright': 'CaskLabs; Sony-PMCA-RE contributors',
        },
    )
