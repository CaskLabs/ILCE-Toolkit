"""Exercise the frozen worker without camera writes or network access."""
import json
from pathlib import Path
import subprocess
import tempfile


def main():
    root = Path(__file__).resolve().parents[1]
    bundle = root / 'dist' / 'ILCE Toolkit.app'
    executable = bundle / 'Contents' / 'MacOS' / 'ILCE Toolkit'

    def invoke(operation, values=None):
        result = subprocess.run([str(executable), '--worker'],
            input=json.dumps(dict(operation=operation, values=values or {})) + '\n',
            text=True, capture_output=True, timeout=30)
        events = [json.loads(line) for line in result.stdout.splitlines()]
        if result.returncode or not events or events[-1] != dict(event='done', success=True):
            raise RuntimeError('Frozen worker failed: %s\n%s' % (events, result.stderr))
        return events

    data = next(event['value'] for event in invoke('diagnostics') if event['event'] == 'data')
    if data['architecture'] != 'arm64' or not data['bundled'] or not data['libusb'] or not data['installer_certificate'] or not data['updater_models']:
        raise RuntimeError('Unexpected bundle configuration: %s' % data)
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / 'App with spaces.apk'
        packed = Path(directory) / 'App.spk'
        restored = Path(directory) / 'Restored.apk'
        source.write_bytes(bytes(range(256)) * 1000)
        invoke('apk2spk', dict(input=str(source), output=str(packed)))
        invoke('spk2apk', dict(input=str(packed), output=str(restored)))
        if source.read_bytes() != restored.read_bytes():
            raise RuntimeError('Bundled conversion round trip failed.')
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(bundle)], check=True)
    print('Verified arm64 app, bundled libusb, worker transport, APK/SPK round trip and code signature.')


if __name__ == '__main__':
    main()
