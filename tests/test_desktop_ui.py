import ast
import json
import os
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QEventLoop, QTimer, QSettings
from PySide6.QtWidgets import QApplication, QDialog, QComboBox, QPushButton

from pmca.desktop.catalog import OPERATIONS
from pmca.desktop.controller import Controller
from pmca.desktop.window import MainWindow, SHELL_TOOLS
from pmca.desktop.i18n import get_language, german_translations, set_language


APP = QApplication.instance() or QApplication([])


class UiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.settings = QSettings(str(Path(self.directory.name) / 'preferences.ini'), QSettings.Format.IniFormat)
        self.window = MainWindow(self.settings)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()
        self.directory.cleanup()
        set_language('en')

    def test_first_launch_uses_english_and_preferences_are_accessible(self):
        self.assertEqual(get_language(), 'en')
        self.assertEqual(self.window.navigation.item(0).text(), 'Camera')
        self.assertEqual(self.window.run_button.text(), 'Detect camera')
        self.assertEqual(self.window.settings_action.text(), 'Settings')
        self.assertFalse(self.settings.contains('language'))

    def test_language_change_preserves_forms_and_active_session(self):
        self.window.select_key('wifi_read')
        self.window.form.set_value('output', 'Settings')
        self.window.form.set_value('multi', True)
        self.window.driver.setCurrentIndex(self.window.driver.findData('native'))
        self.window.log.setPlainText('Original log')
        self.window.handle_event(dict(event='session_ready', commands=['info', 'exit'], help='Original help'))
        self.window.set_tweaks([dict(id='recLimit', description='Disable video recording limit', value='29m50s', enabled=True)])
        self.window.set_busy(True)
        original_form = self.window.form
        with patch.object(self.window.controller, 'process', Mock()) as process:
            self.window.change_language('de')
            self.assertIs(self.window.controller.process, process)
            self.assertIs(self.window.form, original_form)
            self.assertEqual(self.window.form.values(), dict(multi=True, output='Settings'))
            self.assertEqual(self.window.driver.currentData(), 'native')
            self.assertEqual(self.window.driver.currentText(), german_translations()['Native'])
            self.assertEqual(self.window.log.toPlainText(), 'Original log')
            self.assertEqual(self.window.session_output.toPlainText(), 'Original help\n')
            self.assertTrue(self.window.session_ready)
            self.assertFalse(self.window.run_button.isEnabled())
            self.assertTrue(self.window.exit_session.isEnabled())
            self.assertTrue(self.window.tweak_boxes['recLimit'].isChecked())
            self.assertEqual(self.window.run_button.text(), german_translations()['Read Wi-Fi settings'])
            self.assertEqual(self.window.exit_session.text(), german_translations()['End session'])
            self.window.change_language('en')
            self.assertEqual(self.window.run_button.text(), 'Read Wi-Fi settings')
            self.assertEqual(self.window.exit_session.text(), 'End session')

    def test_language_is_saved_and_restored_on_launch(self):
        self.window.change_language('de')
        self.assertEqual(self.settings.value('language'), 'de')
        self.window.close()
        reopened = MainWindow(QSettings(self.settings.fileName(), QSettings.Format.IniFormat))
        try:
            self.assertEqual(get_language(), 'de')
            self.assertEqual(reopened.run_button.text(), german_translations()['Detect camera'])
        finally:
            reopened.close()
            reopened.deleteLater()

    def test_preferences_dialog_applies_the_selected_language(self):
        def choose_language(dialog):
            combo = dialog.findChild(QComboBox)
            combo.setCurrentIndex(combo.findData('de'))
            self.assertEqual({button.text() for button in dialog.findChildren(QPushButton)}, {'Cancel', 'Apply'})
            return QDialog.DialogCode.Accepted
        with patch.object(QDialog, 'exec', choose_language):
            self.window.show_preferences()
        self.assertEqual(self.settings.value('language'), 'de')

    def test_invalid_saved_language_falls_back_to_english(self):
        self.window.change_language('unsupported')
        self.assertEqual(get_language(), 'en')
        self.assertEqual(self.window.run_button.text(), 'Detect camera')

    def test_worker_error_status_changes_language_without_rewriting_the_log(self):
        message = 'The camera does not support this command for its model or current USB mode.'
        self.window.change_language('de')
        self.window.handle_event(dict(event='error', message=german_translations()[message]))
        original_log = self.window.log.toPlainText()
        self.window.change_language('en')
        self.assertEqual(self.window.status.text(), message)
        self.assertEqual(self.window.log.toPlainText(), original_log)

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
            self.window.handle_event(dict(event='prompt', text='Select tweak'))
        send.assert_called_once_with(dict(action='prompt_response', text='', cancelled=True))

    def test_camera_info_updates_sidebar(self):
        self.window.active_operation = 'info'
        for text in ('Model: ILCE-5000', 'Firmware version: 1.00'):
            self.window.handle_event(dict(event='log', text=text))
        self.assertEqual(self.window.camera_label.text(), 'ILCE-5000\nFirmware 1.00')

    def test_admin_restart_is_only_offered_for_the_failed_camera_action(self):
        self.window.select_key('serviceshell')
        self.window.active_operation = 'serviceshell'
        with patch('pmca.desktop.window.sys.platform', 'darwin'):
            self.window.handle_event(dict(event='error', message='Requires capture', requires_admin=True))
        self.assertFalse(self.window.admin_button.isHidden())
        self.window.select_key('info')
        self.assertTrue(self.window.admin_button.isHidden())

    def test_admin_restart_preserves_updater_and_network_form_values(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / 'Settings with spaces.json'
            settings.write_text('[]')
            export = str(Path(directory) / 'Export.json')
            cases = (
                ('updatershell', dict(model='ILCE-5000', firmware=str(settings))),
                ('wifi_read', dict(multi=True, output=export)),
                ('wifi_write', dict(settings=str(settings), multi=True)),
                ('stream_read', dict(output=export)),
                ('stream_write', dict(settings=str(settings))),
            )
            for key, values in cases:
                with self.subTest(operation=key):
                    self.window.select_key(key)
                    for name, value in values.items():
                        if isinstance(value, bool):
                            self.window.form.inputs[name].setChecked(value)
                        else:
                            self.window.form.set_value(name, value)
                    self.window.active_operation = key
                    with patch('pmca.desktop.window.sys.platform', 'darwin'):
                        self.window.handle_event(dict(event='error', message='Requires capture', requires_admin=True))
                    self.assertFalse(self.window.admin_button.isHidden())
                    with patch.object(self.window.controller, 'start') as start:
                        self.window.admin_button.click()
                    start.assert_called_once_with(key, values, self.window.driver.currentData(), elevated=True)

    def test_offline_tools_cannot_request_admin_authorization(self):
        controller = Controller()
        for key in ('diagnostics', 'apps', 'market_download', 'apk2spk'):
            with self.subTest(operation=key), patch('pmca.desktop.controller.sys.platform', 'darwin'):
                with self.assertRaises(ValueError):
                    controller.start(key, elevated=True)
                self.assertFalse(controller.busy)

    def test_privacy_settings_action_is_separate_from_admin_restart(self):
        self.window.select_key('serviceshell')
        self.window.active_operation = 'serviceshell'
        with patch('pmca.desktop.window.sys.platform', 'darwin'):
            self.window.handle_event(dict(event='error', message='Privacy check required', requires_full_disk_access=True))
        self.assertFalse(self.window.privacy_button.isHidden())
        self.assertTrue(self.window.admin_button.isHidden())

    def test_admin_transport_authenticates_and_keeps_session_bidirectional(self):
        if sys.platform != 'darwin':
            self.skipTest('macOS helper transport')
        controller = Controller()
        events = []
        loop = QEventLoop()
        prepared_directory = []
        original_prepare = controller._prepare_admin_process

        def prepare(process, root):
            original_prepare(process, root)
            prepared_directory.append(controller.ipc_directory.name)
            path = str(Path(controller.ipc_directory.name) / 'worker.sock')
            # Exercise the real connected helper without invoking OS authorization
            # or opening USB: substitute only the PMCA operation in this child.
            code = '''
import sys
from pmca.desktop import worker
def dispatch(request, protocol, files):
    protocol.emit('session_ready', commands=['help', 'exit'], help='Test session')
    assert worker.read_message()['action'] == 'session_exit'
worker.dispatch = dispatch
raise SystemExit(worker.run_connected(sys.argv[1]))
'''
            process.setProgram(sys.executable)
            process.setArguments(['-u', '-c', code, path])

        def receive(event):
            events.append(event)
            if event['event'] == 'session_ready':
                controller.send(dict(action='session_exit'))

        controller.event.connect(receive)
        controller.busy_changed.connect(lambda busy: loop.quit() if not busy else None)
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        with patch.object(controller, '_prepare_admin_process', side_effect=prepare):
            controller.start('serviceshell', elevated=True)
            timer.start(10000)
            loop.exec()
        if controller.busy:
            controller.process.kill()
            controller.process.waitForFinished(3000)
            self.fail('Connected helper timed out')
        self.assertIn(dict(event='done', success=True), events)
        self.assertFalse(any(event['event'] == 'hello' for event in events))
        self.assertFalse(Path(prepared_directory[0]).exists())

    def test_cancelled_admin_start_releases_controller(self):
        controller = Controller()
        controller.elevated = True
        controller.process = Mock()
        controller.process.readAllStandardOutput.return_value = b''
        controller.process.readAllStandardError.return_value = b'User canceled (-128)'
        events = []
        controller.event.connect(events.append)
        controller._finished(1, None)
        self.assertFalse(controller.busy)
        self.assertIn('canceled', next(event['message'] for event in events if event['event'] == 'error'))
        self.assertIn(dict(event='done', success=False), events)

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
