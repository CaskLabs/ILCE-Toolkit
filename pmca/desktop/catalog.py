"""Declarative forms shared by the desktop interface and worker validation."""
from dataclasses import dataclass


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
    Operation('info', 'Kamera', 'Kamera erkennen', 'Modell, Firmware, Seriennummer, Objektiv und GPS-Informationen auslesen.', camera=True),
    Operation('diagnostics', 'Kamera', 'System prüfen', 'Python, Prozessorarchitektur und USB-Bibliothek prüfen, ohne auf die Kamera zuzugreifen.'),
    Operation('install', 'Apps', 'APK installieren', 'Eine lokale Android-App über den USB-App-Installer auf die Kamera übertragen.', (
        file_field('apk', 'APK-Datei'), output_field('output', 'Installationsbericht (JSON)', False)), True),
    Operation('apk_inspect', 'Apps', 'APK prüfen', 'Paket, Version, Android-Mindestversion und Signatur vor der Installation prüfen.', (file_field('apk', 'APK-Datei'),)),
    Operation('apps', 'Apps', 'App-Katalog laden', 'Den OpenMemories-App-Katalog laden. Eine App auswählen und anschließend installieren.'),
    Operation('install_catalog', 'Apps', 'App aus Katalog installieren', 'Eine App über ihren Paketnamen aus dem OpenMemories-Katalog installieren.', (
        Field('package', 'Paketname', 'package', True, 'z. B. com.github.ma1co.openmemories.tweak'),
        output_field('output', 'Installationsbericht (JSON)', False)), True),
    Operation('install_test', 'Apps', 'App-Installer testen', 'Die Kommunikation mit dem App-Installer testen und Geräteinformationen lesen.', (
        output_field('output', 'Gerätebericht (JSON)', False),), True),
    Operation('market', 'Apps', 'Sony-Store abfragen', 'Geräte und kostenlose Apps mit einem Sony-Authentifizierungstoken abfragen. Die Verfügbarkeit hängt vom Sony-Dienst ab.', (
        Field('token', 'Sony-Token', 'password', True),)),
    Operation('market_download', 'Apps', 'Sony-App herunterladen', 'Eine App anhand der Geräte- und App-ID als APK herunterladen.', (
        Field('token', 'Sony-Token', 'password', True), Field('device', 'Geräte-ID', required=True),
        Field('app', 'App-ID', required=True), output_field('output', 'APK speichern')),),
    Operation('updatershell', 'Shell & Tweaks', 'Updater-Sitzung starten', 'Updater-Shell öffnen: Tweaks, Linux-Shell, Dateien, Bootloader, Boot-ROM und Backup-Einstellungen. Den Anweisungen auf der Kamera folgen.', (
        Field('model', 'Modell (optional)', hint='Automatisch erkennen oder z. B. ILCE-5000'),
        file_field('firmware', 'Custom-Firmware (optional)', False)), True, True),
    Operation('serviceshell', 'Shell & Tweaks', 'Service-Sitzung starten', 'Service-Shell öffnen. Die Kamera muss im Massenspeichermodus verbunden sein; für diesen Modus werden libusb-Treiber benötigt.', camera=True, session=True),
    Operation('firmware', 'Firmware', 'Firmware installieren', 'Eine Sony-Firmwaredatei auf die angeschlossene Kamera übertragen. Den Anweisungen auf der Kamera folgen.', (
        file_field('firmware', 'Firmwaredatei (.dat)'),), True),
    Operation('guess_firmware', 'Firmware', 'Passende Firmware finden', 'Firmwareabbilder aus einem ZIP mit der Kamera auf Modellkompatibilität prüfen.', (
        file_field('archive', 'Firmwarearchiv (.zip)'),), True),
    Operation('gps', 'GPS', 'GPS-Hilfsdaten aktualisieren', 'GPS-Hilfsdaten aus einer lokalen Datei schreiben oder automatisch von Sony herunterladen.', (
        file_field('gps', 'GPS-Datei (optional)', False),), True),
    Operation('wifi_read', 'WLAN & Streaming', 'WLAN auslesen', 'Gespeicherte WLAN-Einstellungen anzeigen oder als JSON exportieren.', (
        Field('multi', 'Multi-WLAN', 'check'), output_field('output', 'JSON exportieren (optional)', False)), True),
    Operation('wifi_write', 'WLAN & Streaming', 'WLAN schreiben', 'WLAN-Einstellungen aus einer zuvor exportierten JSON-Datei übernehmen.', (
        file_field('settings', 'WLAN-Einstellungen (.json)'), Field('multi', 'Multi-WLAN', 'check')), True),
    Operation('stream_read', 'WLAN & Streaming', 'Streaming auslesen', 'Streaming- und Social-Media-Einstellungen anzeigen oder als JSON exportieren.', (
        output_field('output', 'JSON exportieren (optional)', False),), True),
    Operation('stream_write', 'WLAN & Streaming', 'Streaming schreiben', 'Streaming- und Social-Media-Einstellungen aus einer JSON-Datei übernehmen.', (
        file_field('settings', 'Streaming-Einstellungen (.json)'),), True),
    Operation('apk2spk', 'Dateiwerkzeuge', 'APK → SPK', 'Eine APK in das Sony-App-Paketformat umwandeln.', (
        file_field('input', 'APK-Datei'), output_field('output', 'SPK speichern'))),
    Operation('spk2apk', 'Dateiwerkzeuge', 'SPK → APK', 'Eine APK aus einem Sony-App-Paket extrahieren.', (
        file_field('input', 'SPK-Datei'), output_field('output', 'APK speichern'))),
    Operation('print_backup', 'Dateiwerkzeuge', 'Backup.bin analysieren', 'Alle Backup-Eigenschaften mit ID, Attributen, Daten und Rücksetzwerten anzeigen.', (
        file_field('input', 'Backup.bin'),)),
)

BY_KEY = {operation.key: operation for operation in OPERATIONS}
GROUPS = tuple(dict.fromkeys(operation.group for operation in OPERATIONS))


def validate(operation, values):
    from pathlib import Path
    for field in operation.fields:
        value = values.get(field.key, '')
        if field.required and not value:
            raise ValueError('%s fehlt.' % field.label)
        if value and field.kind == 'file' and not Path(value).is_file():
            raise ValueError('%s: Datei nicht gefunden.' % field.label)
        if value and field.kind == 'output':
            path = Path(value)
            if not path.parent.is_dir() or path.is_dir():
                raise ValueError('%s: Ungültiger Zielpfad.' % field.label)
            for source in operation.fields:
                if source.kind == 'file' and values.get(source.key) and path.resolve() == Path(values[source.key]).resolve():
                    raise ValueError('Eingabe- und Ausgabedatei müssen verschieden sein.')
