"""Build the native Apple Silicon desktop bundle, including its macOS icon."""
from pathlib import Path
import platform
import subprocess
import sys


def main():
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        raise SystemExit('This build requires native arm64 Python on an Apple Silicon Mac.')
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    root = Path(__file__).resolve().parents[1]
    iconset = root / 'build' / 'ILCEToolkit.iconset'
    iconset.mkdir(parents=True, exist_ok=True)
    app = QGuiApplication([])
    renderer = QSvgRenderer(str(root / 'assets' / 'ilce-toolkit.svg'))
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            pixels = size * scale
            image = QImage(pixels, pixels, QImage.Format.Format_ARGB32)
            image.fill(0)
            painter = QPainter(image)
            renderer.render(painter, QRectF(0, 0, pixels, pixels))
            painter.end()
            name = 'icon_%dx%d%s.png' % (size, size, '@2x' if scale == 2 else '')
            image.save(str(iconset / name))
    subprocess.run(['iconutil', '-c', 'icns', str(iconset), '-o', str(root / 'build' / 'ILCEToolkit.icns')], check=True)
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', str(root / 'pmca-gui.spec')], cwd=root, check=True)
    print('Built: %s' % (root / 'dist' / 'ILCE Toolkit.app'))


if __name__ == '__main__':
    main()
