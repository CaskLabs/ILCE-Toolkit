"""One JSON request per worker process; sessions keep USB ownership until exit.

Only this process imports the USB backend. JSON events use the original stdout,
while legacy PMCA print calls become log events. Tokens travel over stdin.
"""
import builtins
import contextlib
import io
import json
import os
from pathlib import Path
import re
import socket
import sys
import tempfile
import threading
import traceback

from .catalog import BY_KEY, validate


class Protocol:
    def __init__(self, output):
        self.output = output
        self.lock = threading.Lock()

    def emit(self, event, **data):
        with self.lock:
            self.output.write(json.dumps(dict(event=event, **data), ensure_ascii=True) + '\n')
            self.output.flush()


class LogStream(io.TextIOBase):
    def __init__(self, protocol):
        self.protocol = protocol
        self.pending = ''
        self.command_errors = []

    def write(self, text):
        self.pending += text.replace('\r', '\n')
        while '\n' in self.pending:
            line, self.pending = self.pending.split('\n', 1)
            self.protocol.emit('log', text=line)
            if line.startswith(('Error:', 'Fail:', 'Operation timed out.')):
                self.command_errors.append(line)
            match = re.fullmatch(r'(.*?)\s*(\d+)%', line)
            if match:
                self.protocol.emit('progress', phase=match[1].strip(), percent=min(100, int(match[2])))
        return len(text)

    def flush(self):
        if self.pending:
            self.protocol.emit('log', text=self.pending)
            self.pending = ''


class OutputFiles:
    """Commit local output files only after a successful operation."""
    def __init__(self):
        self.stack = contextlib.ExitStack()
        self.outputs = []

    def read(self, path, mode='rb'):
        return self.stack.enter_context(open(path, mode, **({'encoding': 'utf-8'} if 'b' not in mode else {})))

    def write(self, path, mode='wb'):
        if not path:
            return None
        target = Path(path)
        fd, temporary = tempfile.mkstemp(prefix='.' + target.name + '-', dir=str(target.parent))
        file = os.fdopen(fd, mode, **({'encoding': 'utf-8'} if 'b' not in mode else {}))
        self.stack.enter_context(file)
        self.outputs.append((temporary, target))
        return file

    def close(self, success):
        self.stack.close()
        try:
            if success:
                for temporary, target in self.outputs:
                    os.replace(temporary, target)
        finally:
            for temporary, target in self.outputs:
                if os.path.exists(temporary):
                    os.unlink(temporary)


def inspect_apk(path):
    from ..apk import ApkParser
    with open(path, 'rb') as file:
        apk = ApkParser(file)
        result = dict(package=apk.getPackageName(), version=apk.getVersionName(),
                      version_code=apk.getVersionCode(), min_sdk=apk.getMinSdkVersion())
        try:
            apk.getCert()
            result['signed'] = True
        except Exception:
            result['signed'] = False
        result['compatible_sdk'] = result['min_sdk'] <= 10
        return result


def configure_usb(protocol):
    if getattr(sys, 'frozen', False):
        import usb.backend.libusb1
        # ctypes discovery does not reliably search inside a macOS .app bundle.
        libraries = list(Path(sys._MEIPASS).glob('libusb-1.0*.dylib'))
        if libraries:
            usb.backend.libusb1.get_backend(find_library=lambda name: str(libraries[0]))
    from ..commands import usb
    original_get_device = usb.getDevice

    def get_device(driver):
        device = original_get_device(driver)
        if device is None:
            raise RuntimeError('Keine eindeutige Sony-Kamera gefunden. USB-Verbindung und Kameramodus prüfen.')
        return device

    usb.getDevice = get_device
    usb.printStatus = lambda status: protocol.emit('progress', phase=status.message, percent=status.percent)
    return usb


def terminal(backend, protocol):
    """Bridge the camera's existing socket terminal into the JSON transport."""
    camera_socket, ui_socket = socket.socketpair()
    ended = threading.Event()

    def output_loop():
        try:
            while True:
                data = ui_socket.recv(4096)
                if not data:
                    break
                protocol.emit('terminal', text=data.decode('latin1'))
        except OSError:
            pass
        finally:
            ended.set()

    def input_loop():
        try:
            while True:
                message = read_message()
                if message is None or message.get('action') == 'terminal_stop':
                    break
                if message.get('action') == 'terminal_input':
                    ui_socket.sendall(message.get('text', '').encode('latin1', 'replace'))
        except (OSError, ValueError):
            pass
        finally:
            try:
                ui_socket.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    protocol.emit('terminal_ready')
    reader = threading.Thread(target=output_loop, daemon=True)
    writer = threading.Thread(target=input_loop, daemon=True)
    reader.start()
    writer.start()
    try:
        backend.interactiveShell(camera_socket)
    finally:
        camera_socket.close()
        # Require the input pump to acknowledge stop before another stdin reader starts.
        protocol.emit('terminal_ended')
        writer.join()
        ui_socket.close()
        reader.join(timeout=2)


def session(backend, protocol):
    from ..platform import CameraShell
    from ..platform.backend import BackupPlatformBackend
    from ..platform.tweaks import TweakInterface
    from ..shell.parser import ArgParser
    shell = CameraShell(backend)
    backend.start()
    try:
        tweaks = TweakInterface(backend) if isinstance(backend, BackupPlatformBackend) else None

        def send_tweaks():
            protocol.emit('tweaks', items=[dict(id=name, description=desc, enabled=bool(enabled), value=value)
                                          for name, desc, enabled, value in tweaks.getTweaks()] if tweaks else [])

        protocol.emit('session_ready', commands=list(shell.commands._commands), help=shell.commands.help())
        send_tweaks()
        while True:
            message = read_message()
            if message is None or message.get('action') == 'session_exit':
                break
            try:
                action = message.get('action')
                if action == 'tweaks_read':
                    send_tweaks()
                elif action == 'tweaks_apply':
                    if not tweaks:
                        raise ValueError('Keine Tweaks verfügbar.')
                    settings = message.get('settings', {})
                    available = {item[0] for item in tweaks.getTweaks()}
                    if not set(settings).issubset(available):
                        raise ValueError('Nicht unterstützter Tweak.')
                    try:
                        for name, enabled in settings.items():
                            if not isinstance(enabled, bool):
                                raise ValueError('Ungültiger Tweak-Wert.')
                            tweaks.setEnabled(name, enabled)
                        tweaks.apply()
                    finally:
                        # Discard cached patches after both successful and failed writes.
                        tweaks = TweakInterface(backend)
                    send_tweaks()
                elif action == 'terminal_start':
                    terminal(backend, protocol)
                elif action == 'command':
                    command = message.get('command', '').strip()
                    if command == 'exit':
                        break
                    if command == 'shell':
                        terminal(backend, protocol)
                    else:
                        shell.commands.run(ArgParser(command))
                else:
                    raise ValueError('Unbekannte Sitzungsaktion.')
                protocol.emit('action_done', success=True)
            except Exception as error:
                protocol.emit('action_done', success=False, message=str(error))
    finally:
        backend.stop()


def dispatch(request, protocol, files):
    key = request['operation']
    values = request.get('values', {})
    operation = BY_KEY[key]
    validate(operation, values)
    driver = request.get('driver') or None
    if driver not in (None, 'native', 'libusb', 'qemu'):
        raise ValueError('Ungültiger USB-Treiber.')
    usb = configure_usb(protocol) if operation.camera or key in ('apps', 'install_catalog', 'diagnostics') else None
    output = values.get('output')
    if key == 'diagnostics':
        import platform
        from usb.backend import libusb1
        available = libusb1.get_backend() is not None
        protocol.emit('data', kind='system', value=dict(platform=platform.platform(),
            architecture=platform.machine(), python=platform.python_version(), libusb=available,
            bundled=bool(getattr(sys, 'frozen', False)),
            installer_certificate=(Path(usb.scriptRoot) / 'certs' / 'localtest.me.pem').is_file(),
            updater_models=len(list(usb.getFdats()))))
        if not available:
            raise RuntimeError('libusb fehlt. Auf macOS: brew install libusb.')
    elif key == 'apk_inspect':
        protocol.emit('data', kind='apk', value=inspect_apk(values['apk']))
    elif key == 'info':
        usb.infoCommand(driver)
    elif key in ('install', 'install_catalog', 'install_test'):
        if key == 'install':
            apk = inspect_apk(values['apk'])
            protocol.emit('data', kind='apk', value=apk)
        confirmed = []
        original = usb.installApp

        def install_app(*args, **kwargs):
            result = original(*args, **kwargs)
            confirmed.append(result)
            protocol.emit('data', kind='installation', value=result)
            return result

        usb.installApp = install_app
        usb.installCommand(driver, files.read(values['apk']) if key == 'install' else None,
                           values.get('package') if key == 'install_catalog' else None,
                           files.write(output, 'w'))
        if not confirmed:
            raise RuntimeError('Die Kamera hat die Installation / Verbindung nicht bestätigt.')
    elif key == 'apps':
        protocol.emit('data', kind='apps', value=[dict(package=app.package, name=app.name,
                      description=app.desc or '', author=app.author or '', homepage=app.homepage or '')
                      for app in usb.listApps().values()])
    elif key == 'market':
        from .. import marketclient
        items = []
        for device in marketclient.getDevices(values['token']):
            for app in marketclient.getApps(device.name):
                if not app.price:
                    items.append(dict(device=device.deviceid, model=device.name, app=app.id, name=app.name))
        protocol.emit('data', kind='market', value=items)
    elif key == 'market_download':
        from .. import marketclient, spk
        name, data = marketclient.download(values['token'], values['device'], values['app'])
        files.write(output).write(spk.parse(data))
    elif key == 'updatershell':
        from ..platform.backend.usb import UsbPlatformBackend
        started = []

        def complete(device):
            started.append(True)
            session(UsbPlatformBackend(device), protocol)

        usb.updaterShellCommand(values.get('model') or None,
                               files.read(values['firmware']) if values.get('firmware') else None, driver, complete)
        if not started:
            raise RuntimeError('Updater-Sitzung konnte nicht gestartet werden.')
    elif key == 'serviceshell':
        from ..platform.backend.senser import SenserPlatformBackend
        started = []

        def complete(device):
            started.append(True)
            session(SenserPlatformBackend(device), protocol)

        usb.senserShellCommand(driver, complete)
        if not started:
            raise RuntimeError('Service-Sitzung konnte nicht gestartet werden.')
    elif key == 'firmware':
        usb.firmwareUpdateCommand(files.read(values['firmware']), driver)
    elif key == 'guess_firmware':
        usb.guessFirmwareCommand(files.read(values['archive']), driver)
    elif key == 'gps':
        usb.gpsUpdateCommand(files.read(values['gps']) if values.get('gps') else None, driver)
    elif key in ('wifi_read', 'wifi_write', 'stream_read', 'stream_write'):
        write = files.read(values['settings'], 'r') if key.endswith('_write') else None
        if write:
            data = json.load(write)
            if not isinstance(data, list) or any(not isinstance(item, list) or len(item) != 2 for item in data):
                raise ValueError('Einstellungen müssen eine Liste von Schlüssel/Wert-Paaren enthalten.')
            write.seek(0)
        exported = files.write(output, 'w')
        if key.startswith('wifi'):
            usb.wifiCommand(write, exported, bool(values.get('multi')), driver)
        else:
            usb.streamingCommand(write, exported, driver)
    elif key in ('apk2spk', 'spk2apk'):
        from .. import spk
        data = files.read(values['input']).read()
        files.write(output).write(spk.dump(data) if key == 'apk2spk' else spk.parse(data))
    elif key == 'print_backup':
        from ..commands.backup import printBackupCommand
        printBackupCommand(files.read(values['input']))
    else:
        raise ValueError('Unbekannte Funktion.')


def read_message():
    line = sys.stdin.readline()
    if not line:
        return None
    value = json.loads(line)
    if not isinstance(value, dict):
        raise ValueError('Ungültige Worker-Nachricht.')
    return value


def run():
    protocol = Protocol(sys.stdout)
    logs = LogStream(protocol)
    files = OutputFiles()
    success = False
    original_input = builtins.input

    def prompt(text=''):
        protocol.emit('prompt', text=text)
        response = read_message()
        if response is None or response.get('action') != 'prompt_response' or response.get('cancelled'):
            raise EOFError('Eingabe abgebrochen.')
        return response.get('text', '')

    try:
        builtins.input = prompt
        request = read_message()
        if request is None:
            raise ValueError('Keine Anfrage erhalten.')
        with contextlib.redirect_stdout(logs), contextlib.redirect_stderr(logs):
            dispatch(request, protocol, files)
        logs.flush()
        if logs.command_errors:
            raise RuntimeError(logs.command_errors[-1])
        files.close(True)
        success = True
        protocol.emit('done', success=True)
    except Exception as error:
        logs.flush()
        message = str(error)
        if 'No backend available' in message:
            message = 'libusb fehlt. Auf macOS: brew install libusb. Danach die App erneut starten.'
        elif 'Access denied' in message:
            message = 'USB-Zugriff verweigert. Andere Kamera-Apps schließen und die USB-Verbindung erneut herstellen.'
        protocol.emit('error', message=message, detail=traceback.format_exc())
        protocol.emit('done', success=False)
    finally:
        builtins.input = original_input
        if not success:
            files.close(False)
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(run())
