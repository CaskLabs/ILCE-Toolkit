"""Asynchronous, exclusive process transport for desktop operations."""
import json
from pathlib import Path
import sys

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal


class Controller(QObject):
    event = Signal(dict)
    busy_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.buffer = b''
        self.stderr_buffer = b''
        self.completed = False
        self.request = None

    @property
    def busy(self):
        return self.process is not None

    def start(self, operation, values=None, driver=None):
        if self.busy:
            raise RuntimeError('Eine Aktion läuft bereits.')
        self.request = dict(operation=operation, values=values or {}, driver=driver)
        self.buffer = b''
        self.stderr_buffer = b''
        self.completed = False
        process = self.process = QProcess(self)
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert('PYTHONUNBUFFERED', '1')
        if getattr(sys, 'frozen', False):
            environment.insert('PYINSTALLER_RESET_ENVIRONMENT', '1')
        process.setProcessEnvironment(environment)
        root = Path(__file__).resolve().parents[2]
        process.setWorkingDirectory(str(root))
        process.setProgram(sys.executable)
        process.setArguments(['--worker'] if getattr(sys, 'frozen', False) else ['-u', '-m', 'pmca.desktop.worker'])
        process.started.connect(lambda: self.send(self.request))
        process.readyReadStandardOutput.connect(self._read_output)
        process.readyReadStandardError.connect(self._read_error)
        process.finished.connect(self._finished)
        process.errorOccurred.connect(self._process_error)
        self.busy_changed.emit(True)
        process.start()

    def send(self, message):
        if self.process is not None:
            self.process.write((json.dumps(message) + '\n').encode('utf-8'))

    def _read_output(self):
        self.buffer += bytes(self.process.readAllStandardOutput())
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            if not line:
                continue
            try:
                event = json.loads(line)
                if not isinstance(event, dict) or 'event' not in event:
                    raise ValueError('Missing event')
                if event['event'] == 'done':
                    self.completed = True
                self.event.emit(event)
            except (ValueError, UnicodeError):
                self.event.emit(dict(event='log', text=line.decode('utf-8', 'replace')))

    def _read_error(self):
        self.stderr_buffer += bytes(self.process.readAllStandardError())

    def _process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.event.emit(dict(event='error', message='Kameraprozess konnte nicht gestartet werden.', detail=self.process.errorString()))
            self.event.emit(dict(event='done', success=False))
            self._cleanup()

    def _finished(self, exit_code, exit_status):
        self._read_output()
        self._read_error()
        if self.buffer:
            self.event.emit(dict(event='log', text=self.buffer.decode('utf-8', 'replace')))
        if self.stderr_buffer:
            self.event.emit(dict(event='log', text=self.stderr_buffer.decode('utf-8', 'replace')))
        if not self.completed:
            self.event.emit(dict(event='error', message='Kameraprozess wurde unerwartet beendet.', detail='Exit code: %s' % exit_code))
            self.event.emit(dict(event='done', success=False))
        self._cleanup()

    def _cleanup(self):
        if self.process:
            self.process.deleteLater()
        self.process = None
        self.request = None
        self.busy_changed.emit(False)
