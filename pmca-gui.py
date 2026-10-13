#!/usr/bin/env python3
"""ILCE Toolkit desktop launcher (and frozen worker entry point)."""
import sys


if __name__ == '__main__':
    if '--worker-connect' in sys.argv:
        from pmca.desktop.worker import run_connected
        raise SystemExit(run_connected(sys.argv[sys.argv.index('--worker-connect') + 1]))
    if '--worker' in sys.argv:
        from pmca.desktop.worker import run
        raise SystemExit(run())
    try:
        from pmca.desktop.window import main
    except ModuleNotFoundError as error:
        if error.name == 'PySide6':
            raise SystemExit('GUI dependencies are missing. Run: python -m pip install -r requirements-gui.txt')
        raise
    raise SystemExit(main())
