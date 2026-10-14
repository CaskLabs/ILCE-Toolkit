ILCE Toolkit is a desktop interface for Sony cameras compatible with PMCA-RE,
with English and German interfaces, APK installation, camera information,
service and updater sessions, camera tweaks, and local conversion tools.

Requires **Apple Silicon (M1 or newer) and macOS 14 or newer**. Python, Qt and
libusb are bundled. Available camera operations depend on the model, firmware
and USB mode. Service sessions require Mass Storage mode; APK installation can
use MTP. Mass Storage operations can request administrator authorization.

Install with Homebrew:

```bash
brew tap CaskLabs/tap https://github.com/CaskLabs/tap
brew install --cask ilce-toolkit
```

Or download the macOS arm64 ZIP and move **ILCE Toolkit.app** to **Applications**.
The release includes `SHA256SUMS`; run `shasum -a 256 -c SHA256SUMS` in the download
directory to verify the ZIP.

The app is **ad hoc signed**, without Apple Developer ID signing or notarization.
If macOS blocks it on first launch, open **System Settings → Privacy & Security →
Open Anyway** after attempting to launch it and confirm the exception for this
app. See [Apple's instructions](https://support.apple.com/guide/mac-help/mh40617/mac).

This release includes the bundled TLS source required for the camera's APK
installation handshake. The frozen worker's AES self-check is verified before
publishing. Automated checks do not write to a camera.

Based on [Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE).
