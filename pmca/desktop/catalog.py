"""Declarative forms shared by the desktop interface and worker validation."""
from dataclasses import dataclass
from .i18n import tr


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: str = 'text'
    required: bool = False
    hint: str = ''
    choices: tuple = ()


@dataclass(frozen=True)
class Operation:
    key: str
    group: str
    title: str
    description: str
    fields: tuple = ()
    camera: bool = False
    session: bool = False


def file_field(key, label, required=True, hint=''):
    return Field(key, label, 'file', required, hint)


def output_field(key, label, required=True, hint=''):
    return Field(key, label, 'output', required, hint)


OPERATIONS = (
    Operation('info', 'Camera', 'Detect camera', 'Read model, firmware, serial number, lens and GPS information.', camera=True),
    Operation('diagnostics', 'Camera', 'Check system', 'Check Python, processor architecture and the USB library without accessing a camera.'),
    Operation('install', 'Apps', 'Install APK', 'Transfer a local Android app to the camera through the USB app installer.', (
        file_field('apk', 'APK file'), output_field('output', 'Installation report (JSON)', False)), True),
    Operation('apk_inspect', 'Apps', 'Inspect APK', 'Check package, version, minimum Android version and signature before installation.', (file_field('apk', 'APK file'),)),
    Operation('apps', 'Apps', 'Load app catalog', 'Load the OpenMemories app catalog. Select an app to install.'),
    Operation('install_catalog', 'Apps', 'Install app from catalog', 'Install an app from the OpenMemories catalog using its package name.', (
        Field('package', 'Package name', 'package', True, 'e.g. com.github.ma1co.openmemories.tweak'),
        output_field('output', 'Installation report (JSON)', False)), True),
    Operation('install_test', 'Apps', 'Test app installer', 'Test communication with the app installer and read device information.', (
        output_field('output', 'Device report (JSON)', False),), True),
    Operation('market', 'Apps', 'Query Sony store', 'Query devices and free apps using a Sony authentication token. Availability depends on the Sony service.', (
        Field('token', 'Sony token', 'password', True),)),
    Operation('market_download', 'Apps', 'Download Sony app', 'Download an APK using its device and app IDs.', (
        Field('token', 'Sony token', 'password', True), Field('device', 'Device ID', required=True),
        Field('app', 'App ID', required=True), output_field('output', 'Save APK')),),
    Operation('updatershell', 'Shell & Tweaks', 'Start updater session', 'Open an updater shell for tweaks, Linux shell, files, bootloader, boot ROM and backup settings. Follow the instructions on the camera. Support depends on the camera model.', (
        Field('model', 'Model (optional)', hint='Detect automatically or enter your Sony model'),
        file_field('firmware', 'Custom firmware (optional)', False)), True, True),
    Operation('serviceshell', 'Shell & Tweaks', 'Start service session', "Disconnect USB, select Mass Storage in the camera's USB Connection settings, then reconnect USB. Select Automatic or libusb. If macOS owns the interface, use the administrator access button. Service mode requires a supported camera and cannot start in MTP mode.", camera=True, session=True),
    Operation('firmware', 'Firmware', 'Install firmware', 'Transfer a Sony firmware file to the connected camera. Follow the instructions on the camera.', (
        file_field('firmware', 'Firmware file (.dat)'),), True),
    Operation('guess_firmware', 'Firmware', 'Find compatible firmware', 'Check firmware images in a ZIP archive for compatibility with the camera model.', (
        file_field('archive', 'Firmware archive (.zip)'),), True),
    Operation('gps', 'GPS', 'Update GPS assist data', 'Write GPS assist data from a local file or download it automatically from Sony.', (
        file_field('gps', 'GPS file (optional)', False),), True),
    Operation('wifi_read', 'Wi-Fi & Streaming', 'Read Wi-Fi settings', 'Display saved Wi-Fi settings or export them as JSON. Requires support from the camera.', (
        Field('multi', 'Multi Wi-Fi', 'check'), output_field('output', 'Export JSON (optional)', False)), True),
    Operation('wifi_write', 'Wi-Fi & Streaming', 'Write Wi-Fi settings', 'Import Wi-Fi settings from a previously exported JSON file. Requires support from the camera.', (
        file_field('settings', 'Wi-Fi settings (.json)'), Field('multi', 'Multi Wi-Fi', 'check')), True),
    Operation('stream_read', 'Wi-Fi & Streaming', 'Read streaming settings', 'Display streaming and social media settings or export them as JSON. Requires support from the camera.', (
        output_field('output', 'Export JSON (optional)', False),), True),
    Operation('stream_write', 'Wi-Fi & Streaming', 'Write streaming settings', 'Import streaming and social media settings from a JSON file. Requires support from the camera.', (
        file_field('settings', 'Streaming settings (.json)'),), True),
    Operation('apk2spk', 'File Tools', 'APK → SPK', 'Convert an APK to the Sony app package format.', (
        file_field('input', 'APK file'), output_field('output', 'Save SPK'))),
    Operation('spk2apk', 'File Tools', 'SPK → APK', 'Extract an APK from a Sony app package.', (
        file_field('input', 'SPK file'), output_field('output', 'Save APK'))),
    Operation('print_backup', 'File Tools', 'Inspect Backup.bin', 'Display backup properties with their IDs, attributes, data and reset values.', (
        file_field('input', 'Backup.bin'),)),
)

BY_KEY = {operation.key: operation for operation in OPERATIONS}
CAMERA_OPERATIONS = frozenset(operation.key for operation in OPERATIONS if operation.camera)
GROUPS = tuple(dict.fromkeys(operation.group for operation in OPERATIONS))


def validate(operation, values):
    from pathlib import Path
    for field in operation.fields:
        value = values.get(field.key, '')
        if field.required and not value:
            raise ValueError(tr('%s is required.', tr(field.label)))
        if value and field.kind == 'file' and not Path(value).is_file():
            raise ValueError(tr('%s: file not found.', tr(field.label)))
        if value and field.kind == 'output':
            path = Path(value)
            if not path.parent.is_dir() or path.is_dir():
                raise ValueError(tr('%s: invalid destination path.', tr(field.label)))
            for source in operation.fields:
                if source.kind == 'file' and values.get(source.key) and path.resolve() == Path(values[source.key]).resolve():
                    raise ValueError(tr('Input and output files must be different.'))
