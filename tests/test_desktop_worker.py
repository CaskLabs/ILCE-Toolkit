import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pmca.desktop import worker


class WorkerTests(unittest.TestCase):
    def invoke(self, request, dispatch=None):
        output = io.StringIO()
        with patch('sys.stdin', io.StringIO(json.dumps(request) + '\n')), patch('sys.stdout', output):
            if dispatch:
                with patch.object(worker, 'dispatch', dispatch):
                    code = worker.run()
            else:
                code = worker.run()
        return code, [json.loads(line) for line in output.getvalue().splitlines()]

    def test_real_spk_round_trip_with_spaces_and_unicode(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'Meine App ä.apk'
            packed = Path(directory) / 'Meine App.spk'
            restored = Path(directory) / 'Meine App zurück.apk'
            source.write_bytes(b'APK test payload\x00\xff' * 9000)
            for operation, input_path, output_path in [('apk2spk', source, packed), ('spk2apk', packed, restored)]:
                code, events = self.invoke(dict(operation=operation, values=dict(input=str(input_path), output=str(output_path))))
                self.assertEqual(code, 0, events)
                self.assertEqual(events[-1], dict(event='done', success=True))
            self.assertEqual(source.read_bytes(), restored.read_bytes())
            self.assertFalse(list(Path(directory).glob('.*')))

    def test_failed_legacy_command_does_not_overwrite_export(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'settings.json'
            target.write_text('original')

            def fail(request, protocol, files):
                files.write(str(target), 'w').write('partial')
                print('Error: Camera rejected write')

            code, events = self.invoke(dict(operation='wifi_read'), fail)
            self.assertEqual(code, 1)
            self.assertEqual(target.read_text(), 'original')
            self.assertEqual(events[-1], dict(event='done', success=False))
            self.assertFalse(list(Path(directory).glob('.*')))

    def test_failed_conversion_keeps_existing_target(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'bad.spk'
            target = Path(directory) / 'existing.apk'
            source.write_bytes(b'not an SPK')
            target.write_bytes(b'keep me')
            code, events = self.invoke(dict(operation='spk2apk', values=dict(input=str(source), output=str(target))))
            self.assertEqual(code, 1)
            self.assertEqual(target.read_bytes(), b'keep me')
            self.assertFalse(list(Path(directory).glob('.*')))

    def test_output_cannot_replace_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'app.apk'
            path.write_bytes(b'original')
            code, events = self.invoke(dict(operation='apk2spk', values=dict(input=str(path), output=str(path))))
            self.assertEqual(code, 1)
            self.assertEqual(path.read_bytes(), b'original')

    def test_install_requires_camera_confirmation(self):
        from pmca.commands import usb
        with patch.object(usb, 'installCommand'), patch.object(usb, 'getDevice'), patch.object(usb, 'installApp'), patch.object(usb, 'printStatus'):
            code, events = self.invoke(dict(operation='install_test', values={}))
        self.assertEqual(code, 1)
        self.assertIn('nicht bestätigt', next(event['message'] for event in events if event['event'] == 'error'))

    def test_install_confirmation_is_a_structured_result(self):
        from pmca.commands import usb
        result = dict(deviceinfo=dict(name='ILCE-5000'), result='ok')

        def install(driver, apk, package, output):
            usb.installApp(object())

        with patch.object(usb, 'installCommand', side_effect=install), patch.object(usb, 'getDevice'), patch.object(usb, 'installApp', return_value=result), patch.object(usb, 'printStatus'):
            code, events = self.invoke(dict(operation='install_test', values={}))
        self.assertEqual(code, 0, events)
        self.assertIn(dict(event='data', kind='installation', value=result), events)

    def test_no_device_is_an_error_even_when_legacy_command_returns_zero(self):
        from pmca.commands import usb

        def info(driver):
            usb.getDevice(object())

        with patch.object(usb, 'getDevice', return_value=None), patch.object(usb, 'infoCommand', side_effect=info), patch.object(usb, 'printStatus'):
            code, events = self.invoke(dict(operation='info', values={}))
        self.assertEqual(code, 1)
        self.assertEqual(events[-1]['success'], False)

    def test_stream_progress_accepts_split_print_writes(self):
        output = io.StringIO()
        stream = worker.LogStream(worker.Protocol(output))
        stream.write('Downloading ')
        stream.write('57%\n')
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertIn(dict(event='progress', phase='Downloading', percent=57), events)

    def test_cancelled_prompt_aborts_instead_of_applying(self):
        output = io.StringIO()
        applied = []

        def interactive(request, protocol, files):
            if input('Enter number (0 to apply): ') == '0':
                applied.append(True)

        messages = [dict(operation='updatershell'), dict(action='prompt_response', text='', cancelled=True)]
        with patch('sys.stdin', io.StringIO(''.join(json.dumps(item) + '\n' for item in messages))), patch('sys.stdout', output), patch.object(worker, 'dispatch', interactive):
            code = worker.run()
        self.assertEqual(code, 1)
        self.assertFalse(applied)
        self.assertIn('Eingabe abgebrochen', output.getvalue())

    def test_session_failure_is_recoverable_and_backend_stops(self):
        from pmca.platform.backend import FilePlatformBackend

        class Backend(FilePlatformBackend):
            stopped = False

            def writeFile(self, path, file):
                raise RuntimeError('write refused')

            def readFile(self, path, file, sizeCb=None):
                file.write(b'camera file')

            def stop(self):
                self.stopped = True

        backend = Backend()
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'file.txt'
            messages = [dict(action='command', command='unknown'), dict(action='command', command='pull /tmp/file "%s"' % target), dict(action='session_exit')]
            with patch.object(worker, 'read_message', side_effect=messages), patch('sys.stdout', io.StringIO()):
                worker.session(backend, worker.Protocol(output))
            self.assertEqual(target.read_bytes(), b'camera file')
        self.assertTrue(backend.stopped)
        actions = [event for event in map(json.loads, output.getvalue().splitlines()) if event['event'] == 'action_done']
        self.assertEqual([event['success'] for event in actions], [False, True])

    def test_terminal_text_transport_and_stop(self):
        class Backend:
            received = b''

            def interactiveShell(self, socket):
                self.received = socket.recv(4096)
                socket.sendall(b'camera output\r\n')

        backend = Backend()
        output = io.StringIO()
        messages = [dict(action='terminal_input', text='uname -a\n'), dict(action='terminal_stop')]
        with patch.object(worker, 'read_message', side_effect=messages):
            worker.terminal(backend, worker.Protocol(output))
        self.assertEqual(backend.received, b'uname -a\n')
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertIn(dict(event='terminal', text='camera output\r\n'), events)
        self.assertEqual(events[0]['event'], 'terminal_ready')
        self.assertIn(dict(event='terminal_ended'), events)


if __name__ == '__main__':
    unittest.main()
