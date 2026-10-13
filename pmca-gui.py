#!/usr/bin/env python3
"""ILCE Toolkit desktop launcher (and frozen worker entry point)."""
import sys


if __name__ == '__main__':
    if '--worker' in sys.argv:
        from pmca.desktop.worker import run
        raise SystemExit(run())
    try:
        from pmca.desktop.window import main
    except ModuleNotFoundError as error:
        if error.name == 'PySide6':
            raise SystemExit('GUI-Abhängigkeiten fehlen. Bitte ausführen: python -m pip install -r requirements-gui.txt')
        raise
    raise SystemExit(main())
