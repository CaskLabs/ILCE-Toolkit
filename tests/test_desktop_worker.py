import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pmca.desktop import worker
from pmca.desktop.i18n import get_language, german_translations, set_language


class WorkerTests(unittest.TestCase):
    def setUp(self):
        set_language('en')

    def invoke(self, request, dispatch=None):
        output = io.StringIO()
        with patch('sys.stdin', io.StringIO(json.dumps(request) + '\n')), patch('sys.stdout', output):
            if dispatch:
                with patch.object(worker, 'dispatch', dispatch):
                    code = worker.run()
            else:
                code = worker.run()
        return code, [json.loads(line) for line in output.getvalue().splitlines()]

    def test_worker_uses_requested_language_and_restores_parent_context(self):
        message = 'The camera does not support this command for its model or current USB mode.'

        def unsupported(request, protocol, files):
            from pmca.usb import InvalidCommandException
            raise InvalidCommandException('Unsupported command')

        for language in ('en', 'de'):
            with self.subTest(language=language):
                code, events = self.invoke(dict(operation='wifi_read', language=language), unsupported)
                self.assertEqual(code, 1)
                error = next(event for event in events if event['event'] == 'error')
                self.assertEqual(error['message'], german_translations()[message] if language == 'de' else message)
                self.assertFalse(error['requires_admin'])
                self.assertEqual(get_language(), 'en')

    def test_validation_errors_translate_field_labels_in_german(self):
        code, events = self.invoke(dict(operation='install', language='de'))
        self.assertEqual(code, 1)
        error = next(event for event in events if event['event'] == 'error')
        self.assertEqual(error['message'], german_translations()['%s is required.'] % german_translations()['APK file'])

    def test_real_spk_round_trip_with_spaces_and_unicode(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'My app \u00e4.apk'
            packed = Path(directory) / 'Meine App.spk'
            restored = Path(directory) / 'My restored app \u00e4.apk'
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
        self.assertIn('did not confirm', next(event['message'] for event in events if event['event'] == 'error'))

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

    def test_service_session_rejects_mtp_with_camera_menu_instructions(self):
        from pmca.commands import usb

        def service(driver, complete):
            self.assertEqual(driver, 'libusb')
            usb.getDevice(object())
            self.fail('Must reject MTP before authentication')

        with patch.object(usb, 'getDevice', return_value=object()), patch.object(usb, 'senserShellCommand', side_effect=service), patch.object(usb, 'printStatus'):
            code, events = self.invoke(dict(operation='serviceshell', values={}))
        self.assertEqual(code, 1)
        message = next(event['message'] for event in events if event['event'] == 'error')
        self.assertIn('USB Connection settings', message)

    def test_service_session_requires_libusb_driver(self):
        from pmca.commands import usb
        with patch.object(usb, 'senserShellCommand') as start:
            code, events = self.invoke(dict(operation='serviceshell', values={}, driver='native'))
        self.assertEqual(code, 1)
        start.assert_not_called()
        self.assertIn('libusb', next(event['message'] for event in events if event['event'] == 'error'))

    def test_service_preflight_accepts_mass_storage_and_already_service_mode(self):
        from pmca.commands import usb
        for device_type in (usb.SonyMscExtCmdDevice, usb.SonySenserDevice):
            with self.subTest(device_type=device_type):
                device = object.__new__(device_type)
                with patch.object(usb, 'getDevice', return_value=device), patch.object(usb, 'printStatus'):
                    configured = worker.configure_usb(worker.Protocol(io.StringIO()), 'serviceshell')
                    self.assertIs(configured.getDevice(object()), device)

    def test_mass_storage_capture_error_offers_admin_restart(self):
        from pmca.usb.driver.generic.libusb import UsbCaptureRequired

        def blocked(request, protocol, files):
            raise UsbCaptureRequired('Mass-storage driver', errno=13)

        for key in ('serviceshell', 'updatershell', 'wifi_read', 'wifi_write', 'stream_read', 'stream_write'):
            with self.subTest(operation=key):
                code, events = self.invoke(dict(operation=key), blocked)
                self.assertEqual(code, 1)
                error = next(event for event in events if event['event'] == 'error')
                self.assertTrue(error['requires_admin'])
                self.assertIn('Administrator access', error['message'])
                self.assertNotIn('service session', error['message'])

    def test_connected_helper_rejects_other_operations_before_dispatch(self):
        output = io.StringIO()
        with patch('sys.stdin', io.StringIO(json.dumps(dict(operation='info')) + '\n')), patch('sys.stdout', output), patch.object(worker, 'dispatch') as dispatch:
            code = worker.run(allowed_operation='serviceshell')
        self.assertEqual(code, 1)
        dispatch.assert_not_called()

    def test_authorization_is_bound_to_each_updater_or_network_action(self):
        for allowed in ('updatershell', 'wifi_read', 'wifi_write', 'stream_read', 'stream_write'):
            for requested in (allowed, 'info'):
                output = io.StringIO()
                with self.subTest(allowed=allowed, requested=requested), patch('sys.stdin', io.StringIO(json.dumps(dict(operation=requested)) + '\n')), patch('sys.stdout', output), patch.object(worker, 'dispatch') as dispatch:
                    code = worker.run(allowed_operation=allowed)
                if requested == allowed:
                    self.assertEqual(code, 0)
                    dispatch.assert_called_once()
                else:
                    self.assertEqual(code, 1)
                    dispatch.assert_not_called()

    def test_privileged_helper_rejects_non_camera_authorization(self):
        with tempfile.TemporaryDirectory() as directory:
            auth = Path(directory) / 'auth.json'
            auth.write_text(json.dumps(dict(token='test', operation='apk2spk')))
            with self.assertRaises(ValueError):
                worker.run_connected(str(Path(directory) / 'worker.sock'))

    def test_privacy_block_after_capture_has_separate_gui_action(self):
        from pmca.usb.driver.generic.libusb import UsbCaptureBlocked

        def blocked(request, protocol, files):
            raise UsbCaptureBlocked('Capture refused')

        code, events = self.invoke(dict(operation='serviceshell'), blocked)
        self.assertEqual(code, 1)
        error = next(event for event in events if event['event'] == 'error')
        self.assertTrue(error['requires_full_disk_access'])
        self.assertFalse(error['requires_admin'])
        self.assertIn('Full Disk Access', error['message'])

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
        self.assertIn('Input canceled', output.getvalue())

    def test_unsupported_camera_command_is_not_a_permission_error(self):
        from pmca.usb import InvalidCommandException

        def unsupported(request, protocol, files):
            raise InvalidCommandException('MTP error 0x2006')

        code, events = self.invoke(dict(operation='wifi_read'), unsupported)
        self.assertEqual(code, 1)
        message = next(event['message'] for event in events if event['event'] == 'error')
        self.assertIn('current USB mode', message)
        self.assertNotIn('verweigert', message)

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
