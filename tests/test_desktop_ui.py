import ast
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from pmca.desktop.catalog import OPERATIONS
from pmca.desktop.controller import Controller
from pmca.desktop.window import MainWindow, SHELL_TOOLS


APP = QApplication.instance() or QApplication([])


class UiTests(unittest.TestCase):
    def setUp(self):
        self.window = MainWindow()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()

    def test_every_cli_command_has_an_accessible_gui_operation(self):
        source = Path(__file__).resolve().parents[1] / 'pmca-console.py'
        tree = ast.parse(source.read_text())
        commands = {node.args[0].value for node in ast.walk(tree) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute) and node.func.attr == 'add_parser'}
        aliases = {'install_catalog': 'install', 'install_test': 'install', 'wifi_read': 'wifi',
                   'wifi_write': 'wifi', 'stream_read': 'stream', 'stream_write': 'stream'}
        covered = {aliases.get(operation.key, operation.key) for operation in OPERATIONS}
        self.assertFalse(commands - covered, commands - covered)
        for operation in OPERATIONS:
            self.window.select_key(operation.key)
            self.assertEqual(self.window.form.operation.key, operation.key)
            self.assertEqual(set(self.window.form.inputs), {field.key for field in operation.fields})

    def test_replaced_forms_are_hidden_immediately(self):
        self.window.select_key('install')
        old = self.window.form
        self.window.select_key('apk_inspect')
        self.assertTrue(old.isHidden())
        self.assertEqual(self.window.form.operation.key, 'apk_inspect')

    def test_busy_state_prevents_concurrent_usb_actions(self):
        self.window.set_busy(True)
        self.assertFalse(self.window.run_button.isEnabled())
        self.assertFalse(self.window.driver.isEnabled())
        self.assertFalse(self.window.navigation.isEnabled())
        self.window.set_busy(False)
        self.assertTrue(self.window.run_button.isEnabled())

    def test_catalog_selection_prepares_correct_package(self):
        self.window.show_data('apps', [dict(package='example.app', name='Example', author='Author', description='Desc')])
        self.window.use_result(self.window.results.topLevelItem(0), 0)
        self.assertEqual(self.window.form.operation.key, 'install_catalog')
        self.assertEqual(self.window.form.values()['package'], 'example.app')

    def test_all_platform_shell_features_are_exposed(self):
        from pmca.platform import CameraShell
        from pmca.platform.backend.usb import UsbPlatformBackend
        commands = set(CameraShell(UsbPlatformBackend(None)).commands._commands)
        tools = {command.split()[0] for command, title, fields in SHELL_TOOLS}
        self.assertFalse(commands - tools - {'shell', 'tweak', 'help', 'exit'})

    def test_terminal_stop_is_sent_once(self):
        with patch.object(self.window.controller, 'send') as send:
            self.window.handle_event(dict(event='terminal_ready'))
            self.window.stop_terminal()
            self.window.handle_event(dict(event='terminal_ended'))
        send.assert_called_once_with(dict(action='terminal_stop'))

    def test_natural_terminal_exit_acknowledges_input_pump(self):
        with patch.object(self.window.controller, 'send') as send:
            self.window.handle_event(dict(event='terminal_ready'))
            self.window.handle_event(dict(event='terminal_ended'))
        send.assert_called_once_with(dict(action='terminal_stop'))

    def test_cancelled_prompt_does_not_send_apply_choice(self):
        with patch('pmca.desktop.window.QInputDialog.getText', return_value=('', False)), patch.object(self.window.controller, 'send') as send:
            self.window.handle_event(dict(event='prompt', text='Tweak auswählen'))
        send.assert_called_once_with(dict(action='prompt_response', text='', cancelled=True))

    def test_camera_info_updates_sidebar(self):
        self.window.active_operation = 'info'
        for text in ('Model: ILCE-5000', 'Firmware version: 1.00'):
            self.window.handle_event(dict(event='log', text=text))
        self.assertEqual(self.window.camera_label.text(), 'ILCE-5000\nFirmware 1.00')

    def test_controller_runs_real_worker_without_shell_argument_splitting(self):
        controller = Controller()
        events = []
        loop = QEventLoop()
        controller.event.connect(events.append)
        controller.busy_changed.connect(lambda busy: loop.quit() if not busy else None)
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'App with spaces.apk'
            target = Path(directory) / 'Result with spaces.spk'
            source.write_bytes(b'app contents')
            controller.start('apk2spk', dict(input=str(source), output=str(target)))
            timer.start(15000)
            loop.exec()
            if controller.busy:
                controller.process.kill()
                controller.process.waitForFinished(3000)
                self.fail('Worker timed out')
            self.assertTrue(target.is_file(), events)
            self.assertIn(dict(event='done', success=True), events)


if __name__ == '__main__':
    unittest.main()
