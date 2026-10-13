"""macOS-first desktop UI; all camera work runs in an isolated process."""
import json
from pathlib import Path
import platform
import sys

from PySide6.QtCore import Qt, QSettings, QUrl, QObject, QLibraryInfo, QTranslator
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QKeySequence, QPalette, QTextCursor
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog,
    QFormLayout, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QDialog,
    QSplitter, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .catalog import BY_KEY, GROUPS, OPERATIONS, Field, Operation, validate
from .controller import Controller
from .i18n import get_language, set_language, tr, set_text, retranslate

DRIVER_OPTIONS = (('Automatic', None), ('libusb', 'libusb'), ('Native', 'native'), ('QEMU', 'qemu'))

STYLE = '''
QMainWindow, QWidget#content { background: #f3f5f8; color: #18253d; }
QWidget { font-size: 13px; }
QFrame#sidebar { background: #15233b; border: 0; }
QFrame#sidebar QLabel { color: #e8eef8; }
QLabel#brand { font-size: 22px; font-weight: 700; }
QLabel#eyebrow { color: #89a0c2; font-size: 11px; }
QListWidget#navigation { background: transparent; border: 0; color: #cad7eb; outline: 0; }
QListWidget#navigation::item { padding: 13px 12px; margin: 3px 0; border-radius: 7px; }
QListWidget#navigation::item:selected { background: #294164; color: white; }
QListWidget#navigation::item:hover { background: #213652; }
QLabel#title { font-size: 28px; font-weight: 700; color: #15233b; }
QLabel#muted { color: #65738b; }
QFrame#card { background: white; border: 1px solid #dce2ec; border-radius: 10px; }
QLabel#cardTitle { font-size: 16px; font-weight: 600; }
QLineEdit, QComboBox, QPlainTextEdit, QTreeWidget { background: white; color: #18253d; border: 1px solid #d6deea; border-radius: 5px; padding: 7px; selection-background-color: #dce9ff; selection-color: #18253d; }
QLineEdit:focus, QComboBox:focus { border-color: #356fd6; }
QPushButton { background: #f6f8fb; color: #263b59; border: 1px solid #d6deea; border-radius: 6px; padding: 9px 14px; }
QPushButton:hover { background: #eaf0f9; }
QPushButton#primary { background: #2d67cf; border-color: #2d67cf; color: white; font-weight: 600; }
QPushButton:disabled { background: #e5e9ef; color: #9aa4b4; border-color: #e5e9ef; }
QProgressBar { border: 0; border-radius: 4px; background: #e4eaf3; height: 8px; }
QProgressBar::chunk { background: #2d67cf; border-radius: 4px; }
QTabWidget::pane { border: 1px solid #d6deea; background: white; border-radius: 6px; }
QTabBar::tab { padding: 9px 15px; }
QScrollArea { border: 0; background: transparent; }
QLabel#status { font-weight: 600; }
'''


def label(text, name=None, wrap=False):
    result = QLabel()
    set_text(result, text)
    if name:
        result.setObjectName(name)
    result.setWordWrap(wrap)
    return result


def make_button(text):
    result = QPushButton()
    set_text(result, text)
    return result


def make_action(text, parent):
    result = QAction(parent)
    set_text(result, text)
    return result


class FileInput(QWidget):
    def __init__(self, field):
        super().__init__()
        self.field = field
        self.setAcceptDrops(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit()
        set_text(self.edit, field.hint or 'Choose a file or drag it here', 'setPlaceholderText')
        self.edit.setAcceptDrops(False)
        set_text(self.edit, field.label, 'setAccessibleName')
        button = make_button('Browse…')
        button.clicked.connect(self.browse)
        layout.addWidget(self.edit, 1)
        layout.addWidget(button)

    def browse(self):
        if self.field.kind == 'directory':
            path = QFileDialog.getExistingDirectory(self, tr(self.field.label), self.edit.text())
        else:
            dialog = QFileDialog.getSaveFileName if self.field.kind == 'output' else QFileDialog.getOpenFileName
            path, _ = dialog(self, tr(self.field.label), self.edit.text())
        if path:
            self.edit.setText(path)

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            self.edit.setText(urls[0].toLocalFile())
            event.acceptProposedAction()

    def value(self):
        return self.edit.text().strip()


class OperationForm(QWidget):
    def __init__(self, operation, packages=()):
        super().__init__()
        self.operation = operation
        self.inputs = {}
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setVerticalSpacing(14)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for field in operation.fields:
            if field.kind in ('file', 'output', 'directory'):
                widget = FileInput(field)
            elif field.kind == 'check':
                widget = QCheckBox()
                set_text(widget, 'Enable')
            elif field.kind == 'package':
                widget = QComboBox()
                widget.setEditable(True)
                widget.addItems(packages)
                widget.setCurrentText('')
                set_text(widget.lineEdit(), field.hint, 'setPlaceholderText')
            else:
                widget = QLineEdit()
                set_text(widget, field.hint, 'setPlaceholderText')
                if field.kind == 'password':
                    widget.setEchoMode(QLineEdit.EchoMode.Password)
            set_text(widget, field.label, 'setAccessibleName')
            self.inputs[field.key] = widget
            layout.addRow(label(field.label + (' *' if field.required else '')), widget)

    def values(self):
        result = {}
        for key, widget in self.inputs.items():
            if isinstance(widget, FileInput):
                result[key] = widget.value()
            elif isinstance(widget, QCheckBox):
                result[key] = widget.isChecked()
            elif isinstance(widget, QComboBox):
                result[key] = widget.currentText().strip()
            else:
                result[key] = widget.text().strip()
        return result

    def set_value(self, key, value):
        widget = self.inputs.get(key)
        if isinstance(widget, FileInput):
            widget.edit.setText(value)
        elif isinstance(widget, QComboBox):
            widget.setCurrentText(value)
        elif isinstance(widget, QLineEdit):
            widget.setText(value)
        elif isinstance(widget, QCheckBox):
            widget.setChecked(bool(value))


SHELL_TOOLS = (
    ('info', 'Device information', ()),
    ('push', 'Copy file to camera', (Field('local', 'Local file', 'file', True), Field('remote', 'Camera path', required=True))),
    ('pull', 'Copy file from camera', (Field('remote', 'Camera path', required=True), Field('local', 'Save as', 'output', True))),
    ('bootloader', 'Dump bootloader', (Field('directory', 'Destination directory', 'directory', True),)),
    ('bootrom', 'Dump boot ROM', (Field('local', 'Save as', 'output', True),)),
    ('install', 'Install APK through shell', (Field('local', 'APK file', 'file', True),)),
    ('bk r', 'Read backup property', (Field('id', 'Property ID (hex)', required=True),)),
    ('bk w', 'Write backup property', (Field('id', 'Property ID (hex)', required=True), Field('data', 'Data (hex bytes)', required=True))),
    ('bk patch', 'Patch backup property', (Field('id', 'Property ID (hex)', required=True), Field('data', 'Data (hex bytes)', required=True))),
    ('bk s', 'Sync backup to camera', ()),
    ('bk lock', 'Enable backup write protection', ()),
    ('bk unlock', 'Disable backup write protection', ()),
)


class MainWindow(QMainWindow):
    def __init__(self, settings=None):
        super().__init__()
        self.setWindowTitle('ILCE Toolkit')
        self.resize(1180, 850)
        self.setMinimumSize(940, 700)
        if sys.platform == 'darwin':
            self.setUnifiedTitleAndToolBarOnMac(True)
        self.settings = settings if settings is not None else QSettings('CaskLabs', 'ILCE Toolkit')
        set_language(self.settings.value('language', 'en'))
        self.qt_translator = None
        self._set_qt_language()
        geometry = self.settings.value('geometry')
        if geometry:
            self.restoreGeometry(geometry)
        self.controller = Controller(self)
        self.controller.event.connect(self.handle_event)
        self.controller.busy_changed.connect(self.set_busy)
        self.active_operation = None
        self.session_ready = self.action_busy = self.terminal_active = False
        self.terminal_stop_sent = False
        self.session_commands = []
        self.packages = []
        self.tweak_boxes = {}
        self.form = self.shell_form = None
        self.market_token = ''
        self.last_result = None
        self.requires_admin = False
        self.requires_privacy = False
        self._build()
        self._menus()
        self.navigation.setCurrentRow(0)

    def _build(self):
        central = QWidget()
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(210)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(20, 30, 20, 24)
        side.addWidget(label('SONY CAMERA UTILITIES', 'eyebrow'))
        side.addWidget(label('ILCE Toolkit', 'brand'))
        side.addWidget(label('Sony PMCA-RE', 'eyebrow'))
        side.addSpacing(28)
        self.navigation = QListWidget()
        self.navigation.setObjectName('navigation')
        self.navigation.addItems([tr(group) for group in GROUPS])
        self.navigation.currentRowChanged.connect(self.select_group)
        side.addWidget(self.navigation, 1)
        self.camera_label = label('No camera checked', wrap=True)
        side.addWidget(self.camera_label)
        side.addSpacing(12)
        side.addWidget(label('macOS · Apple Silicon\nLocal USB connection', 'eyebrow'))
        outer.addWidget(sidebar)
        content = QWidget()
        content.setObjectName('content')
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(16)
        top = QHBoxLayout()
        self.title = label('', 'title')
        top.addWidget(self.title, 1)
        top.addWidget(label('USB driver', 'muted'))
        self.driver = QComboBox()
        self.driver.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        for name, value in DRIVER_OPTIONS:
            self.driver.addItem(tr(name), value)
        top.addWidget(self.driver)
        layout.addLayout(top)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(16)
        card = QFrame()
        card.setObjectName('card')
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        self.selector = QComboBox()
        self.selector.currentIndexChanged.connect(self.select_operation)
        card_layout.addWidget(self.selector)
        self.description = label('', 'muted', True)
        card_layout.addWidget(self.description)
        self.form_layout = QVBoxLayout()
        card_layout.addLayout(self.form_layout)
        buttons = QHBoxLayout()
        self.run_button = make_button('Run')
        self.run_button.setObjectName('primary')
        self.run_button.clicked.connect(self.run_operation)
        buttons.addWidget(self.run_button)
        self.admin_button = make_button('Run with administrator access')
        self.admin_button.clicked.connect(lambda: self.run_operation(elevated=True))
        self.admin_button.hide()
        buttons.addWidget(self.admin_button)
        self.privacy_button = make_button('Open privacy settings')
        self.privacy_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl('x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles')))
        self.privacy_button.hide()
        buttons.addWidget(self.privacy_button)
        buttons.addStretch()
        self.required_label = label('* Required field', 'muted')
        buttons.addWidget(self.required_label)
        card_layout.addLayout(buttons)
        body_layout.addWidget(card)
        self.results = QTreeWidget()
        self.results.setRootIsDecorated(False)
        self.results.setAlternatingRowColors(True)
        self.results.setMinimumHeight(180)
        self.results.itemDoubleClicked.connect(self.use_result)
        self.results.hide()
        body_layout.addWidget(self.results)
        self.session_tabs = QTabWidget()
        self._build_session()
        self.session_tabs.hide()
        body_layout.addWidget(self.session_tabs)
        body_layout.addStretch()
        scroll.setWidget(body)
        self.splitter.addWidget(scroll)
        log_panel = QWidget()
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_top = QHBoxLayout()
        log_top.addWidget(label('Log', 'cardTitle'))
        log_top.addStretch()
        export = make_button('Export…')
        export.clicked.connect(self.export_log)
        clear = make_button('Clear')
        clear.clicked.connect(lambda: self.log.clear())
        log_top.addWidget(export)
        log_top.addWidget(clear)
        log_layout.addLayout(log_top)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(10000)
        self.log.setFont(QFont('Menlo', 11))
        log_layout.addWidget(self.log)
        self.splitter.addWidget(log_panel)
        self.splitter.setSizes([510, 190])
        layout.addWidget(self.splitter, 1)
        self.status = label('Ready. Connect a camera and select an action.', 'status', True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        outer.addWidget(content, 1)
        self.setCentralWidget(central)

    def _menus(self):
        menu = self._menu('File')
        self.settings_action = make_action('Settings', self)
        self.settings_action.setMenuRole(QAction.MenuRole.PreferencesRole)
        self.settings_action.setShortcut(QKeySequence.StandardKey.Preferences)
        self.settings_action.triggered.connect(self.show_preferences)
        menu.addAction(self.settings_action)
        menu.addSeparator()
        export = make_action('Export log…', self)
        export.triggered.connect(self.export_log)
        menu.addAction(export)
        close = make_action('Close window', self)
        close.setShortcut(QKeySequence.StandardKey.Close)
        close.triggered.connect(self.close)
        menu.addAction(close)
        menu = self._menu('Camera')
        self.refresh_action = make_action('Detect camera', self)
        self.refresh_action.setShortcut(QKeySequence('Ctrl+R'))
        self.refresh_action.triggered.connect(lambda: self.start('info', {}))
        menu.addAction(self.refresh_action)
        run = make_action('Run action', self)
        run.setShortcut(QKeySequence('Ctrl+Return'))
        run.triggered.connect(self.run_operation)
        menu.addAction(run)
        menu = self._menu('Help')
        about = make_action('About ILCE Toolkit', self)
        about.setMenuRole(QAction.MenuRole.AboutRole)
        about.triggered.connect(self.about)
        menu.addAction(about)

    def _menu(self, title):
        menu = self.menuBar().addMenu(tr(title))
        set_text(menu, title, 'setTitle')
        return menu

    def _set_qt_language(self):
        app = QApplication.instance()
        if self.qt_translator is not None:
            app.removeTranslator(self.qt_translator)
            self.qt_translator = None
        if get_language() == 'de':
            directory = Path(sys._MEIPASS) / 'translations' if getattr(sys, 'frozen', False) else Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
            translator = QTranslator(self)
            if translator.load(str(directory / 'qtbase_de.qm')):
                app.installTranslator(translator)
                self.qt_translator = translator

    def show_preferences(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(tr('Settings'))
        layout = QVBoxLayout(dialog)
        layout.addWidget(label('Choose the interface language. Changes take effect immediately and are saved for the next launch.', 'muted', True))
        form = QFormLayout()
        languages = QComboBox()
        for code, name in (('en', 'English'), ('de', 'German')):
            languages.addItem(tr(name), code)
        languages.setCurrentIndex(languages.findData(get_language()))
        languages.setAccessibleName(tr('Language'))
        form.addRow(tr('Language'), languages)
        layout.addLayout(form)
        row = QHBoxLayout()
        row.addStretch()
        cancel = make_button('Cancel')
        cancel.clicked.connect(dialog.reject)
        apply = make_button('Apply')
        apply.setDefault(True)
        apply.clicked.connect(dialog.accept)
        row.addWidget(cancel)
        row.addWidget(apply)
        layout.addLayout(row)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.change_language(languages.currentData())

    def change_language(self, language):
        set_language(language)
        self.settings.setValue('language', get_language())
        self.settings.sync()
        self._set_qt_language()
        for widget in self.findChildren(QObject):
            retranslate(widget)
        for index, group in enumerate(GROUPS):
            self.navigation.item(index).setText(tr(group))
        for index in range(self.selector.count()):
            self.selector.setItemText(index, tr(BY_KEY[self.selector.itemData(index)].title))
        for index, (name, _) in enumerate(DRIVER_OPTIONS):
            self.driver.setItemText(index, tr(name))
        for index, (_, title, _) in enumerate(SHELL_TOOLS):
            self.shell_selector.setItemText(index, tr(title))
        for index, title in enumerate(('Terminal', 'Tweaks', 'Files & Backup')):
            self.session_tabs.setTabText(index, tr(title))
        for box in self.tweak_boxes.values():
            box.setText(tr(box.property('tweak_description')) + ' · ' + box.property('tweak_value'))
        if self.last_result is not None and not self.results.isHidden():
            self.show_data(*self.last_result)
        for widget in self.findChildren(QWidget):
            if widget.layout() is not None:
                widget.layout().invalidate()

    def _build_session(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.session_output = QPlainTextEdit()
        self.session_output.setReadOnly(True)
        self.session_output.setMaximumBlockCount(10000)
        self.session_output.setFont(QFont('Menlo', 11))
        layout.addWidget(self.session_output)
        row = QHBoxLayout()
        self.command = QLineEdit()
        set_text(self.command, 'PMCA command, e.g. help, info, pull /tmp/file…', 'setPlaceholderText')
        self.command.returnPressed.connect(self.send_command)
        self.command_button = make_button('Send')
        self.command_button.clicked.connect(self.send_command)
        row.addWidget(self.command, 1)
        row.addWidget(self.command_button)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.linux_button = make_button('Open Linux shell')
        self.linux_button.clicked.connect(lambda: self.session_action(dict(action='terminal_start')))
        self.terminal_stop = make_button('Leave Linux shell')
        self.terminal_stop.clicked.connect(self.stop_terminal)
        self.interrupt_button = make_button('Send Ctrl+C')
        self.interrupt_button.clicked.connect(lambda: self.controller.send(dict(action='terminal_input', text='\x03')))
        self.exit_session = make_button('End session')
        self.exit_session.clicked.connect(lambda: self.session_action(dict(action='session_exit')))
        for button in (self.linux_button, self.terminal_stop, self.interrupt_button, self.exit_session):
            row.addWidget(button)
        layout.addLayout(row)
        self.session_tabs.addTab(page, 'Terminal')
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(label('Tweaks are read from the camera. Select Apply changes to write your changes.', 'muted', True))
        self.tweak_form = QWidget()
        self.tweak_form_layout = QVBoxLayout(self.tweak_form)
        layout.addWidget(self.tweak_form)
        self.apply_tweaks = make_button('Apply changes')
        self.apply_tweaks.setObjectName('primary')
        self.apply_tweaks.clicked.connect(lambda: self.session_action(dict(action='tweaks_apply', settings={key: box.isChecked() for key, box in self.tweak_boxes.items()})))
        layout.addWidget(self.apply_tweaks)
        layout.addStretch()
        self.session_tabs.addTab(page, 'Tweaks')
        page = QWidget()
        layout = QVBoxLayout(page)
        self.shell_selector = QComboBox()
        for command, title, fields in SHELL_TOOLS:
            self.shell_selector.addItem(tr(title), command)
        self.shell_selector.currentIndexChanged.connect(self.select_shell_tool)
        layout.addWidget(self.shell_selector)
        self.shell_form_layout = QVBoxLayout()
        layout.addLayout(self.shell_form_layout)
        self.shell_run = make_button('Run')
        self.shell_run.clicked.connect(self.run_shell_tool)
        layout.addWidget(self.shell_run)
        layout.addStretch()
        self.session_tabs.addTab(page, tr('Files & Backup'))
        self.select_shell_tool(0)
        self.update_session_controls()

    def select_group(self, index):
        if index < 0:
            return
        group = GROUPS[index]
        set_text(self.title, group)
        self.selector.blockSignals(True)
        self.selector.clear()
        for operation in OPERATIONS:
            if operation.group == group:
                self.selector.addItem(tr(operation.title), operation.key)
        self.selector.blockSignals(False)
        self.select_operation(0)

    def select_operation(self, index):
        key = self.selector.itemData(index)
        if not key:
            return
        operation = BY_KEY[key]
        set_text(self.description, operation.description)
        if self.form:
            self.form_layout.removeWidget(self.form)
            self.form.hide()
            self.form.deleteLater()
        self.form = OperationForm(operation, self.packages)
        self.form_layout.addWidget(self.form)
        if key == 'market_download':
            self.form.set_value('token', self.market_token)
        self.required_label.setVisible(any(field.required for field in operation.fields))
        set_text(self.run_button, operation.title)
        self.admin_button.setVisible(key == self.active_operation and self.requires_admin)
        self.privacy_button.setVisible(key == self.active_operation and self.requires_privacy)
        self.results.hide()

    def select_key(self, key):
        operation = BY_KEY[key]
        self.navigation.setCurrentRow(GROUPS.index(operation.group))
        self.selector.setCurrentIndex(self.selector.findData(key))

    def run_operation(self, elevated=False):
        if self.form and not self.controller.busy:
            self.start(self.form.operation.key, self.form.values(), elevated=elevated)

    def start(self, key, values, elevated=False):
        if self.controller.busy:
            return
        operation = BY_KEY[key]
        try:
            validate(operation, values)
        except (ValueError, TypeError) as error:
            QMessageBox.information(self, tr('Check input'), tr(str(error)))
            return
        output = values.get('output')
        if output and Path(output).exists():
            if QMessageBox.question(self, tr('Replace file?'), tr('The destination file already exists. Replace it?')) != QMessageBox.StandardButton.Yes:
                return
        if key == 'market':
            self.market_token = values['token']
        self.active_operation = key
        self.requires_admin = False
        self.requires_privacy = False
        self.admin_button.hide()
        self.privacy_button.hide()
        self.session_ready = self.action_busy = self.terminal_active = False
        self.session_tabs.hide()
        self.results.hide()
        self.status.setStyleSheet('color: #263b59')
        set_text(self.status, operation.title + ' …')
        self.progress.setRange(0, 0)
        self.log.appendPlainText('\n── ' + tr(operation.title) + ' ──')
        if elevated:
            set_text(self.status, 'Requesting macOS administrator access for the camera…')
            self.log.appendPlainText(tr('Administrator access: only the USB camera worker is authorized; the interface runs under your user account.'))
        try:
            self.controller.start(key, values, self.driver.currentData(), elevated=elevated)
        except (OSError, ValueError, RuntimeError) as error:
            set_text(self.status, str(error))
            self.progress.setRange(0, 100)
            self.progress.setValue(0)

    def set_busy(self, busy):
        for widget in (self.run_button, self.admin_button, self.driver, self.selector, self.navigation, self.form):
            if widget:
                widget.setEnabled(not busy)
        self.refresh_action.setEnabled(not busy)
        if not busy:
            self.session_ready = self.action_busy = self.terminal_active = False
            self.update_session_controls()

    def append_terminal(self, text):
        cursor = self.session_output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self.session_output.setTextCursor(cursor)
        self.session_output.ensureCursorVisible()

    def handle_event(self, event):
        kind = event['event']
        if kind == 'log':
            text = event.get('text', '')
            self.log.appendPlainText(text)
            if self.session_ready:
                self.append_terminal(text + '\n')
            if self.active_operation == 'info':
                if text.startswith('Model:'):
                    set_text(self.camera_label, text.split(':', 1)[1].strip())
                elif text.startswith('Firmware version:'):
                    set_text(self.camera_label, self.camera_label.text() + '\nFirmware ' + text.split(':', 1)[1].strip())
        elif kind == 'progress':
            self.progress.setRange(0, 100)
            self.progress.setValue(event.get('percent', 0))
            set_text(self.status, '%s · %s %%' % (event.get('phase') or 'Transfer', event.get('percent', 0)))
        elif kind == 'data':
            self.show_data(event['kind'], event['value'])
        elif kind == 'error':
            camera_action = self.active_operation in BY_KEY and BY_KEY[self.active_operation].camera
            self.requires_admin = bool(event.get('requires_admin')) and camera_action and sys.platform == 'darwin'
            self.requires_privacy = bool(event.get('requires_full_disk_access')) and camera_action and sys.platform == 'darwin'
            selected = self.form is not None and self.form.operation.key == self.active_operation
            self.admin_button.setVisible(self.requires_admin and selected)
            self.privacy_button.setVisible(self.requires_privacy and selected)
            self.status.setStyleSheet('color: #b33434')
            set_text(self.status, event['message'])
            self.log.appendPlainText(tr(event['message']) + '\n' + event.get('detail', ''))
            if self.active_operation == 'info':
                set_text(self.camera_label, 'Camera unavailable')
        elif kind == 'done':
            self.progress.setRange(0, 100)
            self.progress.setValue(100 if event['success'] else 0)
            if event['success']:
                self.status.setStyleSheet('color: #26704c')
                message = 'Action completed successfully.'
                if self.active_operation in ('install', 'install_catalog'):
                    message = 'Installation confirmed. You can now disconnect the USB cable.'
                elif self.active_operation in ('updatershell', 'serviceshell'):
                    message = 'Session ended and camera connection closed.'
                set_text(self.status, message)
        elif kind == 'session_ready':
            self.session_ready = True
            self.session_commands = event['commands']
            self.session_output.clear()
            self.append_terminal(event['help'] + '\n')
            self.session_tabs.show()
            self.session_tabs.setCurrentIndex(0)
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            set_text(self.status, 'Session connected. Select an action or enter a PMCA command.')
            self.update_session_controls()
        elif kind == 'tweaks':
            self.set_tweaks(event['items'])
        elif kind == 'action_done':
            self.action_busy = False
            self.progress.setRange(0, 100)
            self.progress.setValue(100 if event['success'] else 0)
            set_text(self.status, 'Session action completed.' if event['success'] else event.get('message', 'Session action failed.'))
            self.status.setStyleSheet('color: #26704c' if event['success'] else 'color: #b33434')
            if not event['success']:
                self.append_terminal(event.get('message', '') + '\n')
            self.update_session_controls()
        elif kind == 'terminal_ready':
            self.terminal_active = True
            self.terminal_stop_sent = False
            set_text(self.status, 'Linux shell connected. Enter commands or send Ctrl+C.')
            self.update_session_controls()
        elif kind == 'terminal':
            self.append_terminal(event['text'])
        elif kind == 'terminal_ended':
            if not self.terminal_stop_sent:
                self.controller.send(dict(action='terminal_stop'))
            self.terminal_active = False
            self.update_session_controls()
        elif kind == 'prompt':
            text, accepted = QInputDialog.getText(self, tr('Camera session'), tr(event.get('text', 'Input')))
            self.controller.send(dict(action='prompt_response', text=text, cancelled=not accepted))

    def show_data(self, kind, value):
        self.last_result = (kind, value)
        self.results.clear()
        self.results.setProperty('result_kind', kind)
        if kind == 'apps':
            headers = ['App', 'Package', 'Author', 'Description']
            self.packages = [item['package'] for item in value]
            rows = [([item['name'], item['package'], item['author'], item['description']], item) for item in value]
        elif kind == 'market':
            headers = ['App', 'Camera', 'Device ID', 'App ID']
            rows = [([item['name'], item['model'], str(item['device']), str(item['app'])], item) for item in value]
        else:
            headers = ['Property', 'Value']
            names = {'package': 'Package', 'version': 'Version', 'version_code': 'Version code', 'min_sdk': 'Minimum Android version (SDK)', 'signed': 'Signature present', 'compatible_sdk': 'Minimum version compatible with camera'}
            rows = [([tr(names.get(key, key)), json.dumps(item, ensure_ascii=False) if not isinstance(item, str) else item], {}) for key, item in value.items()]
        self.results.setColumnCount(len(headers))
        self.results.setHeaderLabels([tr(header) for header in headers])
        for texts, data in rows:
            item = QTreeWidgetItem([str(text or '') for text in texts])
            item.setData(0, Qt.ItemDataRole.UserRole, data)
            self.results.addTopLevelItem(item)
        for index in range(len(headers) - 1):
            self.results.resizeColumnToContents(index)
        if not rows:
            self.results.addTopLevelItem(QTreeWidgetItem([tr('No entries available.')]))
        self.results.show()
        set_text(self.results, 'Double-click to select an app' if kind in ('apps', 'market') else '', 'setToolTip')
        if kind == 'apk' and (not value['compatible_sdk'] or not value['signed']):
            self.log.appendPlainText(tr('APK check: the minimum Android version or signature may be incompatible with the camera.'))

    def use_result(self, item, column):
        if self.controller.busy:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        kind = self.results.property('result_kind')
        if kind == 'apps' and data:
            self.select_key('install_catalog')
            self.form.set_value('package', data['package'])
        elif kind == 'market' and data:
            self.select_key('market_download')
            self.form.set_value('device', str(data['device']))
            self.form.set_value('app', str(data['app']))

    def set_tweaks(self, items):
        while self.tweak_form_layout.count():
            child = self.tweak_form_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.tweak_boxes = {}
        for item in items:
            box = QCheckBox()
            box.setProperty('tweak_description', item['description'])
            box.setProperty('tweak_value', item['value'])
            box.setText(tr(item['description']) + ' · ' + item['value'])
            box.setChecked(item['enabled'])
            self.tweak_boxes[item['id']] = box
            self.tweak_form_layout.addWidget(box)
        if not items:
            self.tweak_form_layout.addWidget(label('No tweaks are available for this camera.', 'muted'))
        self.update_session_controls()

    def update_session_controls(self):
        ready = self.session_ready and not self.action_busy
        self.command.setEnabled(self.session_ready and (ready or self.terminal_active))
        self.command_button.setEnabled(self.command.isEnabled())
        self.linux_button.setEnabled(ready and 'shell' in self.session_commands)
        self.terminal_stop.setEnabled(self.terminal_active)
        self.interrupt_button.setEnabled(self.terminal_active)
        self.exit_session.setEnabled(ready)
        self.apply_tweaks.setEnabled(ready and bool(self.tweak_boxes))
        self.tweak_form.setEnabled(ready)
        self.shell_selector.setEnabled(ready)
        self.shell_run.setEnabled(ready)
        if self.shell_form:
            self.shell_form.setEnabled(ready)
        if self.session_ready:
            for index, (command, title, fields) in enumerate(SHELL_TOOLS):
                self.shell_selector.model().item(index).setEnabled(command.split()[0] in self.session_commands)

    def session_action(self, message):
        if not self.session_ready or self.action_busy:
            return
        self.action_busy = True
        self.status.setStyleSheet('color: #263b59')
        set_text(self.status, 'Session action in progress…')
        self.progress.setRange(0, 0)
        self.update_session_controls()
        self.controller.send(message)

    def send_command(self):
        text = self.command.text().strip()
        if not text or not self.session_ready:
            return
        if self.terminal_active:
            self.controller.send(dict(action='terminal_input', text=text + '\n'))
        elif not self.action_busy:
            self.session_action(dict(action='command', command=text))
        else:
            return
        self.append_terminal('> ' + text + '\n')
        self.command.clear()

    def stop_terminal(self):
        if not self.terminal_stop_sent:
            self.terminal_stop_sent = True
            self.controller.send(dict(action='terminal_stop'))
        self.terminal_stop.setEnabled(False)

    def select_shell_tool(self, index):
        if index < 0:
            return
        command, title, fields = SHELL_TOOLS[index]
        if self.shell_form:
            self.shell_form_layout.removeWidget(self.shell_form)
            self.shell_form.hide()
            self.shell_form.deleteLater()
        self.shell_form = OperationForm(Operation(command, '', title, '', fields))
        self.shell_form_layout.addWidget(self.shell_form)

    def run_shell_tool(self):
        if not self.session_ready or self.action_busy:
            return
        values = self.shell_form.values()
        try:
            validate(self.shell_form.operation, values)
            if values.get('directory') and not Path(values['directory']).is_dir():
                raise ValueError('Destination directory not found.')
            if values.get('id'):
                int(values['id'], 16)
            if values.get('data'):
                bytes(int(part, 16) for part in values['data'].split())
        except (ValueError, TypeError) as error:
            QMessageBox.information(self, tr('Check input'), tr(str(error)))
            return
        def quote(value):
            return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
        command = self.shell_form.operation.key
        if command == 'push':
            command += ' ' + quote(values['local']) + ' ' + quote(values['remote'])
        elif command == 'pull':
            command += ' ' + quote(values['remote']) + ' ' + quote(values['local'])
        elif command in ('bootloader', 'bootrom', 'install'):
            command += ' ' + quote(values.get('directory') or values['local'])
        elif command.startswith('bk ') and values:
            command += ' ' + values['id']
            if 'data' in values:
                command += ' ' + values['data']
        self.append_terminal('> ' + command + '\n')
        self.session_action(dict(action='command', command=command))

    def export_log(self):
        path, _ = QFileDialog.getSaveFileName(self, tr('Export log'), 'pmca-log.txt', tr('Text files (*.txt)'))
        if path:
            try:
                Path(path).write_text(self.log.toPlainText(), encoding='utf-8')
            except OSError as error:
                QMessageBox.information(self, tr('Export failed'), str(error))

    def about(self):
        QMessageBox.about(self, 'ILCE Toolkit', tr('Desktop interface for Sony PMCA-RE.\n\nFor Sony cameras compatible with PMCA-RE. Available features depend on the model, firmware and USB mode.\n\nPrimary platform: macOS on Apple Silicon.\nRuntime: Python %s · %s', platform.python_version(), platform.machine()))

    def closeEvent(self, event):
        if self.controller.busy:
            event.ignore()
            QMessageBox.information(self, tr('Action in progress'), tr('The camera is still in use. Close a shell session using End session, or wait for the current action to finish.'))
            return
        self.market_token = ''
        self.settings.setValue('geometry', self.saveGeometry())
        if self.qt_translator is not None:
            QApplication.instance().removeTranslator(self.qt_translator)
            self.qt_translator = None
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('ILCE Toolkit')
    app.setOrganizationName('CaskLabs')
    app.setStyle('Fusion')
    palette = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, '#f3f5f8'), (QPalette.ColorRole.WindowText, '#18253d'),
        (QPalette.ColorRole.Base, '#ffffff'), (QPalette.ColorRole.AlternateBase, '#f3f5f8'),
        (QPalette.ColorRole.Text, '#18253d'), (QPalette.ColorRole.Button, '#f6f8fb'),
        (QPalette.ColorRole.ButtonText, '#18253d'), (QPalette.ColorRole.Highlight, '#dce9ff'),
        (QPalette.ColorRole.HighlightedText, '#18253d')):
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    if sys.platform == 'darwin':
        app.setFont(QFont('Helvetica Neue', 13))
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    return app.exec()
