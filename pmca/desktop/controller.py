"""Asynchronous, exclusive process transport for desktop operations."""
import json
from pathlib import Path
import sys
import hmac
import os
import secrets
import shlex
import tempfile

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal
from PySide6.QtNetwork import QLocalServer
from .catalog import CAMERA_OPERATIONS


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
        self.elevated = False
        self.server = self.connection = self.ipc_directory = None
        self.authenticated = False

    @property
    def busy(self):
        return self.process is not None

    def start(self, operation, values=None, driver=None, elevated=False):
        if self.busy:
            raise RuntimeError('Eine Aktion läuft bereits.')
        if elevated and (sys.platform != 'darwin' or operation not in CAMERA_OPERATIONS):
            raise ValueError('Administratorfreigabe ist nur für macOS-Kameraaktionen vorgesehen.')
        self.request = dict(operation=operation, values=values or {}, driver=driver)
        self.buffer = b''
        self.stderr_buffer = b''
        self.completed = False
        self.elevated = elevated
        self.authenticated = False
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
        if elevated:
            try:
                self._prepare_admin_process(process, root)
            except Exception:
                self._cleanup()
                raise
        else:
            process.started.connect(lambda: self.send(self.request))
        process.readyReadStandardOutput.connect(self._read_output)
        process.readyReadStandardError.connect(self._read_error)
        process.finished.connect(self._finished)
        process.errorOccurred.connect(self._process_error)
        self.busy_changed.emit(True)
        process.start()

    def send(self, message):
        if self.elevated:
            if self.connection is not None and self.authenticated:
                self.connection.write((json.dumps(message) + '\n').encode('utf-8'))
        elif self.process is not None:
            self.process.write((json.dumps(message) + '\n').encode('utf-8'))

    def _prepare_admin_process(self, process, root):
        self.ipc_directory = tempfile.TemporaryDirectory(prefix='ilce-', dir='/tmp')
        directory = Path(self.ipc_directory.name)
        self.token = secrets.token_hex(32)
        auth = directory / 'auth.json'
        from .macos import audit_session
        auth.write_text(json.dumps(dict(token=self.token, operation=self.request['operation'],
                                       audit_session=audit_session())), encoding='utf-8')
        auth.chmod(0o600)
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._accept_connection)
        path = str(directory / 'worker.sock')
        if not self.server.listen(path):
            raise RuntimeError('Lokale Kameraverbindung konnte nicht vorbereitet werden.')
        arguments = [sys.executable]
        if not getattr(sys, 'frozen', False):
            arguments += ['-u', str(root / 'pmca-gui.py')]
        arguments += ['--worker-connect', path]
        command = shlex.join(['/usr/bin/env', 'PYINSTALLER_RESET_ENVIRONMENT=1', 'PYTHONUNBUFFERED=1'] + arguments)
        process.setProgram('/usr/bin/osascript')
        process.setArguments(['-e', 'on run argv\n do shell script (item 1 of argv) with administrator privileges\nend run', command])

    def _accept_connection(self):
        connection = self.server.nextPendingConnection()
        if self.connection is not None:
            connection.close()
            connection.deleteLater()
            return
        self.connection = connection
        connection.readyRead.connect(self._read_socket)
        QTimer.singleShot(5000, lambda: self._expire_connection(connection))

    def _expire_connection(self, connection):
        if self.connection is connection and not self.authenticated:
            connection.close()
            connection.deleteLater()
            self.connection = None

    def _read_socket(self):
        if self.connection is not None:
            self._feed(bytes(self.connection.readAll()))

    def _read_output(self):
        output = bytes(self.process.readAllStandardOutput())
        if self.elevated:
            if output:
                self.event.emit(dict(event='log', text=output.decode('utf-8', 'replace')))
        else:
            self._feed(output)

    def _feed(self, output):
        self.buffer += output
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            if not line:
                continue
            try:
                event = json.loads(line)
                if not isinstance(event, dict) or 'event' not in event:
                    raise ValueError('Missing event')
                if self.elevated and not self.authenticated:
                    if event.get('event') != 'hello' or not hmac.compare_digest(str(event.get('token', '')), self.token):
                        self.buffer = b''
                        self.connection.close()
                        self.connection.deleteLater()
                        self.connection = None
                        return
                    self.authenticated = True
                    self.server.close()
                    self.send(self.request)
                    continue
                if event['event'] == 'done':
                    self.completed = True
                self.event.emit(event)
            except (ValueError, UnicodeError):
                if self.elevated and not self.authenticated:
                    self.buffer = b''
                    self._expire_connection(self.connection)
                    return
                else:
                    self.event.emit(dict(event='log', text=line.decode('utf-8', 'replace')))

    def _read_error(self):
        self.stderr_buffer += bytes(self.process.readAllStandardError())

    def _process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.event.emit(dict(event='error', message='Kameraprozess konnte nicht gestartet werden.', detail=self.process.errorString()))
            self.event.emit(dict(event='done', success=False))
            self._cleanup()

    def _finished(self, exit_code, exit_status):
        self._read_socket()
        self._read_output()
        self._read_error()
        if self.buffer:
            self.event.emit(dict(event='log', text=self.buffer.decode('utf-8', 'replace')))
        if self.stderr_buffer:
            self.event.emit(dict(event='log', text=self.stderr_buffer.decode('utf-8', 'replace')))
        if not self.completed:
            message = 'Administratorfreigabe wurde abgebrochen oder der Kameraprozess konnte nicht gestartet werden.' if self.elevated and not self.authenticated else 'Kameraprozess wurde unerwartet beendet.'
            self.event.emit(dict(event='error', message=message, detail='Exit code: %s' % exit_code))
            self.event.emit(dict(event='done', success=False))
        self._cleanup()

    def _cleanup(self):
        if self.process:
            self.process.deleteLater()
        self.process = None
        if self.connection is not None:
            self.connection.close()
            self.connection.deleteLater()
            self.connection = None
        if self.server is not None:
            self.server.close()
            self.server.deleteLater()
            self.server = None
        if self.ipc_directory is not None:
            self.ipc_directory.cleanup()
            self.ipc_directory = None
        self.token = ''
        self.request = None
        self.busy_changed.emit(False)
