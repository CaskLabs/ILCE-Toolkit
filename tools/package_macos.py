"""Package a built macOS app without altering its ad hoc signature."""
import argparse
import hashlib
from pathlib import Path
import plistlib
import re
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', help='Require the bundle version to match this release version.')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    bundle = root / 'dist' / 'ILCE Toolkit.app'
    with (bundle / 'Contents' / 'Info.plist').open('rb') as file:
        version = plistlib.load(file)['CFBundleShortVersionString']
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise SystemExit('Expected a three-part release version, got %r.' % version)
    if args.version and args.version != version:
        raise SystemExit('Release version %s does not match bundle version %s.' % (args.version, version))
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(bundle)], check=True)
    archive = root / 'dist' / ('ILCE-Toolkit-%s-macos-arm64.zip' % version)
    subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(bundle), str(archive)], check=True)
    with archive.open('rb') as file:
        checksum = hashlib.file_digest(file, 'sha256').hexdigest()
    (root / 'dist' / 'SHA256SUMS').write_text('%s  %s\n' % (checksum, archive.name), encoding='utf-8')
    print('Packaged: %s\nSHA256: %s' % (archive, checksum))


if __name__ == '__main__':
    main()
