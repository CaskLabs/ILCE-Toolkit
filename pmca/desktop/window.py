"""macOS-first desktop UI; all camera work runs in an isolated process."""
import json
from pathlib import Path
import platform
import sys

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence, QPalette, QTextCursor
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog,
    QFormLayout, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QSplitter, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .catalog import BY_KEY, GROUPS, OPERATIONS, Field, Operation, validate
from .controller import Controller

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
    result = QLabel(text)
    if name:
        result.setObjectName(name)
    result.setWordWrap(wrap)
    return result


class FileInput(QWidget):
    def __init__(self, field):
        super().__init__()
        self.field = field
        self.setAcceptDrops(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(field.hint or 'Datei auswählen oder hier hineinziehen')
        self.edit.setAcceptDrops(False)
        self.edit.setAccessibleName(field.label)
        button = QPushButton('Auswählen …')
        button.clicked.connect(self.browse)
        layout.addWidget(self.edit, 1)
        layout.addWidget(button)

    def browse(self):
        if self.field.kind == 'directory':
            path = QFileDialog.getExistingDirectory(self, self.field.label, self.edit.text())
        else:
            dialog = QFileDialog.getSaveFileName if self.field.kind == 'output' else QFileDialog.getOpenFileName
            path, _ = dialog(self, self.field.label, self.edit.text())
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
                widget = QCheckBox('Aktivieren')
            elif field.kind == 'package':
                widget = QComboBox()
                widget.setEditable(True)
                widget.addItems(packages)
                widget.setCurrentText('')
                widget.lineEdit().setPlaceholderText(field.hint)
            else:
                widget = QLineEdit()
                widget.setPlaceholderText(field.hint)
                if field.kind == 'password':
                    widget.setEchoMode(QLineEdit.EchoMode.Password)
            widget.setAccessibleName(field.label)
            self.inputs[field.key] = widget
            layout.addRow(field.label + (' *' if field.required else ''), widget)

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


SHELL_TOOLS = (
    ('info', 'Geräteinformationen', ()),
    ('push', 'Datei auf Kamera kopieren', (Field('local', 'Lokale Datei', 'file', True), Field('remote', 'Kamerapfad', required=True))),
    ('pull', 'Datei von Kamera kopieren', (Field('remote', 'Kamerapfad', required=True), Field('local', 'Speichern als', 'output', True))),
    ('bootloader', 'Bootloader sichern', (Field('directory', 'Zielverzeichnis', 'directory', True),)),
    ('bootrom', 'Boot-ROM sichern', (Field('local', 'Speichern als', 'output', True),)),
    ('install', 'APK über Shell installieren', (Field('local', 'APK-Datei', 'file', True),)),
    ('bk r', 'Backup-Eigenschaft lesen', (Field('id', 'Eigenschafts-ID (hex)', required=True),)),
    ('bk w', 'Backup-Eigenschaft schreiben', (Field('id', 'Eigenschafts-ID (hex)', required=True), Field('data', 'Daten (Hexbytes)', required=True))),
    ('bk patch', 'Backup-Eigenschaft patchen', (Field('id', 'Eigenschafts-ID (hex)', required=True), Field('data', 'Daten (Hexbytes)', required=True))),
    ('bk s', 'Backup auf Kamera synchronisieren', ()),
    ('bk lock', 'Backup-Schreibschutz aktivieren', ()),
    ('bk unlock', 'Backup-Schreibschutz aufheben', ()),
)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('ILCE Toolkit')
        self.resize(1180, 850)
        self.setMinimumSize(940, 700)
        if sys.platform == 'darwin':
            self.setUnifiedTitleAndToolBarOnMac(True)
        self.settings = QSettings('CaskLabs', 'ILCE Toolkit')
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
        self.navigation.addItems(GROUPS)
        self.navigation.currentRowChanged.connect(self.select_group)
        side.addWidget(self.navigation, 1)
        self.camera_label = label('Keine Kamera geprüft', wrap=True)
        side.addWidget(self.camera_label)
        side.addSpacing(12)
        side.addWidget(label('macOS · Apple Silicon\nLokale USB-Verbindung', 'eyebrow'))
        outer.addWidget(sidebar)
        content = QWidget()
        content.setObjectName('content')
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(16)
        top = QHBoxLayout()
        self.title = label('', 'title')
        top.addWidget(self.title, 1)
        top.addWidget(label('USB-Treiber', 'muted'))
        self.driver = QComboBox()
        for name, value in [('Automatisch', None), ('libusb', 'libusb'), ('Native', 'native'), ('QEMU', 'qemu')]:
            self.driver.addItem(name, value)
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
        self.run_button = QPushButton('Ausführen')
        self.run_button.setObjectName('primary')
        self.run_button.clicked.connect(self.run_operation)
        buttons.addWidget(self.run_button)
        buttons.addStretch()
        self.required_label = label('* Pflichtfeld', 'muted')
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
        log_top.addWidget(label('Protokoll', 'cardTitle'))
        log_top.addStretch()
        export = QPushButton('Exportieren …')
        export.clicked.connect(self.export_log)
        clear = QPushButton('Leeren')
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
        self.status = label('Bereit. Kamera verbinden und eine Aktion auswählen.', 'status', True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        outer.addWidget(content, 1)
        self.setCentralWidget(central)

    def _menus(self):
        menu = self.menuBar().addMenu('Datei')
        export = QAction('Protokoll exportieren …', self)
        export.triggered.connect(self.export_log)
        menu.addAction(export)
        close = QAction('Fenster schließen', self)
        close.setShortcut(QKeySequence.StandardKey.Close)
        close.triggered.connect(self.close)
        menu.addAction(close)
        menu = self.menuBar().addMenu('Kamera')
        self.refresh_action = QAction('Kamera erkennen', self)
        self.refresh_action.setShortcut(QKeySequence('Ctrl+R'))
        self.refresh_action.triggered.connect(lambda: self.start('info', {}))
        menu.addAction(self.refresh_action)
        run = QAction('Aktion ausführen', self)
        run.setShortcut(QKeySequence('Ctrl+Return'))
        run.triggered.connect(self.run_operation)
        menu.addAction(run)
        menu = self.menuBar().addMenu('Hilfe')
        about = QAction('Über ILCE Toolkit', self)
        about.setMenuRole(QAction.MenuRole.AboutRole)
        about.triggered.connect(self.about)
        menu.addAction(about)

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
        self.command.setPlaceholderText('PMCA-Befehl, z. B. help, info, pull /tmp/file …')
        self.command.returnPressed.connect(self.send_command)
        self.command_button = QPushButton('Senden')
        self.command_button.clicked.connect(self.send_command)
        row.addWidget(self.command, 1)
        row.addWidget(self.command_button)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.linux_button = QPushButton('Linux-Shell öffnen')
        self.linux_button.clicked.connect(lambda: self.session_action(dict(action='terminal_start')))
        self.terminal_stop = QPushButton('Linux-Shell verlassen')
        self.terminal_stop.clicked.connect(self.stop_terminal)
        self.interrupt_button = QPushButton('Strg+C senden')
        self.interrupt_button.clicked.connect(lambda: self.controller.send(dict(action='terminal_input', text='\x03')))
        self.exit_session = QPushButton('Sitzung beenden')
        self.exit_session.clicked.connect(lambda: self.session_action(dict(action='session_exit')))
        for button in (self.linux_button, self.terminal_stop, self.interrupt_button, self.exit_session):
            row.addWidget(button)
        layout.addLayout(row)
        self.session_tabs.addTab(page, 'Terminal')
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(label('Tweaks werden aus der Kamera gelesen. Änderungen mit „Übernehmen“ schreiben.', 'muted', True))
        self.tweak_form = QWidget()
        self.tweak_form_layout = QVBoxLayout(self.tweak_form)
        layout.addWidget(self.tweak_form)
        self.apply_tweaks = QPushButton('Änderungen übernehmen')
        self.apply_tweaks.setObjectName('primary')
        self.apply_tweaks.clicked.connect(lambda: self.session_action(dict(action='tweaks_apply', settings={key: box.isChecked() for key, box in self.tweak_boxes.items()})))
        layout.addWidget(self.apply_tweaks)
        layout.addStretch()
        self.session_tabs.addTab(page, 'Tweaks')
        page = QWidget()
        layout = QVBoxLayout(page)
        self.shell_selector = QComboBox()
        for command, title, fields in SHELL_TOOLS:
            self.shell_selector.addItem(title, command)
        self.shell_selector.currentIndexChanged.connect(self.select_shell_tool)
        layout.addWidget(self.shell_selector)
        self.shell_form_layout = QVBoxLayout()
        layout.addLayout(self.shell_form_layout)
        self.shell_run = QPushButton('Ausführen')
        self.shell_run.clicked.connect(self.run_shell_tool)
        layout.addWidget(self.shell_run)
        layout.addStretch()
        self.session_tabs.addTab(page, 'Dateien & Backup')
        self.select_shell_tool(0)
        self.update_session_controls()

    def select_group(self, index):
        if index < 0:
            return
        group = GROUPS[index]
        self.title.setText(group)
        self.selector.blockSignals(True)
        self.selector.clear()
        for operation in OPERATIONS:
            if operation.group == group:
                self.selector.addItem(operation.title, operation.key)
        self.selector.blockSignals(False)
        self.select_operation(0)

    def select_operation(self, index):
        key = self.selector.itemData(index)
        if not key:
            return
        operation = BY_KEY[key]
        self.description.setText(operation.description)
        if self.form:
            self.form_layout.removeWidget(self.form)
            self.form.hide()
            self.form.deleteLater()
        self.form = OperationForm(operation, self.packages)
        self.form_layout.addWidget(self.form)
        if key == 'market_download':
            self.form.set_value('token', self.market_token)
        self.required_label.setVisible(any(field.required for field in operation.fields))
        self.run_button.setText(operation.title)
        self.results.hide()

    def select_key(self, key):
        operation = BY_KEY[key]
        self.navigation.setCurrentRow(GROUPS.index(operation.group))
        self.selector.setCurrentIndex(self.selector.findData(key))

    def run_operation(self):
        if self.form and not self.controller.busy:
            self.start(self.form.operation.key, self.form.values())

    def start(self, key, values):
        if self.controller.busy:
            return
        operation = BY_KEY[key]
        try:
            validate(operation, values)
        except (ValueError, TypeError) as error:
            QMessageBox.information(self, 'Eingabe prüfen', str(error))
            return
        output = values.get('output')
        if output and Path(output).exists():
            if QMessageBox.question(self, 'Datei ersetzen?', 'Die Zieldatei existiert bereits. Soll sie ersetzt werden?') != QMessageBox.StandardButton.Yes:
                return
        if key == 'market':
            self.market_token = values['token']
        self.active_operation = key
        self.session_ready = self.action_busy = self.terminal_active = False
        self.session_tabs.hide()
        self.results.hide()
        self.status.setStyleSheet('color: #263b59')
        self.status.setText(operation.title + ' …')
        self.progress.setRange(0, 0)
        self.log.appendPlainText('\n── ' + operation.title + ' ──')
        self.controller.start(key, values, self.driver.currentData())

    def set_busy(self, busy):
        for widget in (self.run_button, self.driver, self.selector, self.navigation, self.form):
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
                    self.camera_label.setText(text.split(':', 1)[1].strip())
                elif text.startswith('Firmware version:'):
                    self.camera_label.setText(self.camera_label.text() + '\nFirmware ' + text.split(':', 1)[1].strip())
        elif kind == 'progress':
            self.progress.setRange(0, 100)
            self.progress.setValue(event.get('percent', 0))
            self.status.setText('%s · %s %%' % (event.get('phase') or 'Übertragung', event.get('percent', 0)))
        elif kind == 'data':
            self.show_data(event['kind'], event['value'])
        elif kind == 'error':
            self.status.setStyleSheet('color: #b33434')
            self.status.setText(event['message'])
            self.log.appendPlainText(event['message'] + '\n' + event.get('detail', ''))
            if self.active_operation == 'info':
                self.camera_label.setText('Kamera nicht erreichbar')
        elif kind == 'done':
            self.progress.setRange(0, 100)
            self.progress.setValue(100 if event['success'] else 0)
            if event['success']:
                self.status.setStyleSheet('color: #26704c')
                message = 'Aktion erfolgreich abgeschlossen.'
                if self.active_operation in ('install', 'install_catalog'):
                    message = 'Installation bestätigt. Das USB-Kabel kann jetzt entfernt werden.'
                elif self.active_operation in ('updatershell', 'serviceshell'):
                    message = 'Sitzung beendet und Kameraverbindung geschlossen.'
                self.status.setText(message)
        elif kind == 'session_ready':
            self.session_ready = True
            self.session_commands = event['commands']
            self.session_output.clear()
            self.append_terminal(event['help'] + '\n')
            self.session_tabs.show()
            self.session_tabs.setCurrentIndex(0)
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.status.setText('Sitzung verbunden. Aktion auswählen oder PMCA-Befehl eingeben.')
            self.update_session_controls()
        elif kind == 'tweaks':
            self.set_tweaks(event['items'])
        elif kind == 'action_done':
            self.action_busy = False
            self.progress.setRange(0, 100)
            self.progress.setValue(100 if event['success'] else 0)
            self.status.setText('Sitzungsaktion abgeschlossen.' if event['success'] else event.get('message', 'Sitzungsaktion fehlgeschlagen.'))
            self.status.setStyleSheet('color: #26704c' if event['success'] else 'color: #b33434')
            if not event['success']:
                self.append_terminal(event.get('message', '') + '\n')
            self.update_session_controls()
        elif kind == 'terminal_ready':
            self.terminal_active = True
            self.terminal_stop_sent = False
            self.status.setText('Linux-Shell verbunden. Befehle eingeben oder Strg+C senden.')
            self.update_session_controls()
        elif kind == 'terminal':
            self.append_terminal(event['text'])
        elif kind == 'terminal_ended':
            if not self.terminal_stop_sent:
                self.controller.send(dict(action='terminal_stop'))
            self.terminal_active = False
            self.update_session_controls()
        elif kind == 'prompt':
            text, accepted = QInputDialog.getText(self, 'Kamera-Sitzung', event.get('text', 'Eingabe'))
            self.controller.send(dict(action='prompt_response', text=text, cancelled=not accepted))

    def show_data(self, kind, value):
        self.results.clear()
        self.results.setProperty('result_kind', kind)
        if kind == 'apps':
            headers = ['App', 'Paket', 'Autor', 'Beschreibung']
            self.packages = [item['package'] for item in value]
            rows = [([item['name'], item['package'], item['author'], item['description']], item) for item in value]
        elif kind == 'market':
            headers = ['App', 'Kamera', 'Geräte-ID', 'App-ID']
            rows = [([item['name'], item['model'], str(item['device']), str(item['app'])], item) for item in value]
        else:
            headers = ['Eigenschaft', 'Wert']
            names = {'package': 'Paket', 'version': 'Version', 'version_code': 'Versionscode', 'min_sdk': 'Android-Mindestversion (SDK)', 'signed': 'Signatur vorhanden', 'compatible_sdk': 'Mindestversion passt zur Kamera'}
            rows = [([names.get(key, key), json.dumps(item, ensure_ascii=False) if not isinstance(item, str) else item], {}) for key, item in value.items()]
        self.results.setColumnCount(len(headers))
        self.results.setHeaderLabels(headers)
        for texts, data in rows:
            item = QTreeWidgetItem([str(text or '') for text in texts])
            item.setData(0, Qt.ItemDataRole.UserRole, data)
            self.results.addTopLevelItem(item)
        for index in range(len(headers) - 1):
            self.results.resizeColumnToContents(index)
        if not rows:
            self.results.addTopLevelItem(QTreeWidgetItem(['Keine Einträge verfügbar.']))
        self.results.show()
        self.results.setToolTip('Doppelklick: App auswählen' if kind in ('apps', 'market') else '')
        if kind == 'apk' and (not value['compatible_sdk'] or not value['signed']):
            self.log.appendPlainText('APK-Prüfung: Mindestversion oder Signatur passt möglicherweise nicht zur Kamera.')

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
            box = QCheckBox(item['description'] + ' · ' + item['value'])
            box.setChecked(item['enabled'])
            self.tweak_boxes[item['id']] = box
            self.tweak_form_layout.addWidget(box)
        if not items:
            self.tweak_form_layout.addWidget(label('Für diese Kamera sind keine Tweaks verfügbar.', 'muted'))
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
        self.status.setText('Sitzungsaktion läuft …')
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
                raise ValueError('Zielverzeichnis nicht gefunden.')
            if values.get('id'):
                int(values['id'], 16)
            if values.get('data'):
                bytes(int(part, 16) for part in values['data'].split())
        except (ValueError, TypeError) as error:
            QMessageBox.information(self, 'Eingabe prüfen', str(error))
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
        path, _ = QFileDialog.getSaveFileName(self, 'Protokoll exportieren', 'pmca-log.txt', 'Textdateien (*.txt)')
        if path:
            try:
                Path(path).write_text(self.log.toPlainText(), encoding='utf-8')
            except OSError as error:
                QMessageBox.information(self, 'Export fehlgeschlagen', str(error))

    def about(self):
        QMessageBox.about(self, 'ILCE Toolkit', 'Neue Desktop-Oberfläche für Sony PMCA-RE.\n\n'
            'Primäre Plattform: macOS mit Apple Silicon.\nLaufzeit: Python %s · %s\n\n'
            'Kameraabhängige Funktionen benötigen die Unterstützung des jeweiligen Modells.'
            % (platform.python_version(), platform.machine()))

    def closeEvent(self, event):
        if self.controller.busy:
            event.ignore()
            QMessageBox.information(self, 'Aktion läuft', 'Die Kamera wird noch verwendet. Eine Shell-Sitzung zuerst über „Sitzung beenden“ schließen; bei anderen Aktionen den Abschluss abwarten.')
            return
        self.market_token = ''
        self.settings.setValue('geometry', self.saveGeometry())
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
