# ILCE Toolkit

A desktop toolkit for Sony cameras, maintained by CaskLabs and based on
[Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE). Inspect cameras, install
Android apps on supported models, open service or updater sessions, apply
camera tweaks, and work with firmware, settings and local package files.

The released app runs on **Apple Silicon (M1 or newer) with macOS 14 or newer**.
It uses a Qt interface with **English and German** translations. Camera support
and available operations depend on the model, firmware, USB mode and backend.

[Installation](#installation) · [Usage](#usage) ·
[macOS USB permissions](#macos-usb-permissions) · [Development](#development) ·
[Command-line tools](#command-line-tools)

## Installation

### Homebrew

```bash
brew tap CaskLabs/tap https://github.com/CaskLabs/tap
brew install --cask ilce-toolkit
```

Update with `brew upgrade --cask ilce-toolkit`.
The cask is maintained in [CaskLabs/tap](https://github.com/CaskLabs/tap).

### Download the app

1. Download the macOS arm64 ZIP from the
   [latest ILCE Toolkit release](https://github.com/CaskLabs/ILCE-Toolkit/releases/latest).
2. Unzip it and move **ILCE Toolkit.app** to **Applications**.
3. Open the app.

The app bundles Python, Qt, libusb, the APK installer's local TLS certificate and
updater payloads. It does not need a separate Python or libusb installation.

Releases include `SHA256SUMS`. To verify a downloaded ZIP, put both files in the
same directory and run:

```bash
shasum -a 256 -c SHA256SUMS
```

### First launch on macOS

The app is **ad hoc signed**, without Apple Developer ID signing or notarization.
No paid Apple developer account is needed to build or distribute these releases.

If macOS blocks the first launch, attempt to open the app, then choose
**System Settings → Privacy & Security → Open Anyway** and confirm the exception
for ILCE Toolkit. See [Apple's instructions](https://support.apple.com/guide/mac-help/mh40617/mac).
Homebrew installation retains this macOS security check.

## Usage

The names below match the English interface. Switch to German in
**ILCE Toolkit → Settings** (**⌘,** on macOS). The selection takes effect
immediately and is saved for the next launch. Existing forms and sessions are
preserved; raw camera data and backend logs retain their original text.

### Getting started

1. Connect one Sony camera over USB.
2. Leave **USB driver** set to **Automatic**, unless an action requires libusb.
3. Select a section in the sidebar, then an action from its dropdown.
4. Fill in the required fields and click the action button.

Start with **Camera → Detect camera** to read model, firmware, serial number,
lens and GPS information where available. **Camera → Check system** checks the
runtime, libusb and installer TLS AES without accessing a camera.

Local file fields accept drag-and-drop. Results appear above the log; use
**Export…** in the log panel to save the log. Camera operations run one at a time.

### Installing camera apps

USB app installation requires a camera that supports PlayMemories Camera Apps.
**MTP mode can be used for APK installation.**

| Source | Steps in **Apps** |
| --- | --- |
| Local APK | Select **Install APK**, choose the APK file and click **Install APK**. Optionally choose a JSON installation report. |
| OpenMemories catalog | Run **Load app catalog**, double-click an entry, then click **Install app from catalog**. |

Use **Inspect APK** to read the package name, version, minimum Android SDK and
signature presence. Use **Test app installer** to check communication and read
device information. Installation success is reported after the camera confirms
completion.

**Query Sony store** and **Download Sony app** accept a Sony authentication token.
Double-clicking a store result prepares its device and app IDs for download.
These actions depend on the availability of Sony's online services.

### Service and updater sessions

Open **Shell & Tweaks** and choose a session type:

| Action | Connection and behavior |
| --- | --- |
| **Start service session** | Requires **Mass Storage** mode and the **Automatic** or **libusb** driver. Switches a supported camera into service mode. |
| **Start updater session** | Accepts MTP or Mass Storage mode. Detects the model and selects a bundled updater payload; optional model and custom-firmware fields are available. Follow the camera and log prompts when it switches to updater mode. |

To prepare a service session:

1. Disconnect USB.
2. In the camera's **USB Connection** settings, select **Mass Storage**.
3. Reconnect USB.
4. Select **Automatic** or **libusb** in ILCE Toolkit.
5. Click **Start service session**.

**MTP mode cannot start a service session.** On macOS, blocked USB access may
require the administrator retry described [below](#macos-usb-permissions).

Once connected, the session provides three tabs:

| Tab | Available tools |
| --- | --- |
| **Terminal** | Enter PMCA commands such as `help` or `info`, or select **Open Linux shell**. |
| **Tweaks** | Review the settings available on this camera, change checkboxes and select **Apply changes** to write them. |
| **Files & Backup** | Copy files, dump the bootloader or boot ROM, install an APK through the shell, and read, write, patch, sync or protect backup properties. |

Tools and tweaks are enabled according to the connected backend. Supported
settings can include recording limits, camera languages, the PAL/NTSC selector
and the USB app installer.

The session keeps the camera connection until you select **End session**.

| Shell control | Action |
| --- | --- |
| **Open Linux shell** | Enter the camera's Linux shell when supported |
| **Leave Linux shell** | Return to the PMCA session |
| **Send Ctrl+C** | Send the interrupt character to the Linux shell |
| **End session** | Close the session and release the camera connection |

The terminal transports text; it is not a full terminal emulator.

### Other tools

| Sidebar section | Actions |
| --- | --- |
| **Firmware** | **Install firmware** transfers a `.dat` firmware file. **Find compatible firmware** checks images in a ZIP archive against the connected camera. Firmware installation is separate from starting an updater shell. |
| **GPS** | **Update GPS assist data** accepts a local file or attempts a download from Sony. |
| **Wi-Fi & Streaming** | Read settings, optionally export JSON, or write settings from an exported JSON file. Wi-Fi actions also offer **Multi Wi-Fi**. |
| **File Tools** | Convert **APK → SPK**, extract **SPK → APK**, or **Inspect Backup.bin**. These actions work on local files without a camera. |

## macOS USB permissions

The macOS mass-storage driver can block access to the camera. If this happens:

1. Select **Run with administrator access** when offered, then approve the macOS
   administrator dialog. The retry is available for camera actions blocked by
   the mass-storage driver, including service and updater sessions.
2. If access is still denied, manually grant **ILCE Toolkit** access under
   **System Settings → Privacy & Security → Full Disk Access**, then restart the
   app. **Open privacy settings** opens this panel when the app offers it.
3. After a local ad hoc rebuild, you may need to remove and re-add the app in
   Full Disk Access because its code signature has changed.

Administrator authorization does not bypass Full Disk Access. Normal MTP app
installation and camera queries only request administrator rights if their USB
access requires capturing the mass-storage interface.

<details>
<summary>Technical details: administrator access and macOS privacy</summary>

The interface stays under your user account. Only the worker for the selected
camera action is authorized; its authenticated transport rejects other actions
and communicates with the GUI over an authenticated local socket.

File operations use the invoking user's effective permissions. The worker raises
its effective uid only around USB access and driver capture/restore.

Before loading libusb, the authorized worker creates an audit session attributed
to the invoking user. AppleScript's default administrator session has no audit
user (`AU_DEFAUDITID`), which can prevent macOS from applying an existing privacy
grant even when the worker runs as root. See the
[Apple Developer Support discussion](https://developer.apple.com/forums/thread/844378).

</details>

## Compatibility and data

- **Camera support:** an ILCE or DSC model name alone does not guarantee support
  for every action. Updater sessions need a compatible payload; app installation
  needs PMCA support; service sessions need a compatible service-mode backend.
- **Camera writes:** the USB protocols are reverse-engineered. Firmware, tweak
  and backup operations can change the device. Understand the selected action
  and keep backups before modifying firmware or backup properties.
- **Reports and exports:** temporary files replace their targets only after the
  operation succeeds.
- **Credentials:** Sony tokens are sent to the worker over stdin and are not
  stored in preferences or passed on the command line. Wi-Fi/streaming output
  can contain credentials; handle exported files and logs accordingly.
- **Online services:** catalog downloads, Sony-store queries and automatic GPS
  downloads need network access. Backend errors appear in the app's log.

Custom camera apps should target Android 2.3.7 (API 10), with a minimum SDK of
10 or lower. **Inspect APK** checks the minimum SDK and signature presence; it
cannot guarantee that an app will run on a particular camera.

## Development

### Run from source

CI uses Python 3.12. On macOS, install libusb, then create a virtual environment
and install the desktop dependencies:

```bash
git clone https://github.com/CaskLabs/ILCE-Toolkit.git
cd ILCE-Toolkit
brew install libusb
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-gui.txt
python pmca-gui.py
```

The source also contains Windows and Linux USB backends. This fork currently
publishes desktop releases for macOS on Apple Silicon; it does not publish
Windows, Linux or Intel Mac binaries. Source installations on other platforms
need their platform's USB library and driver setup. On Windows, activate the
virtual environment with `.venv\Scripts\Activate.ps1` in PowerShell.

### Build and verify the macOS app

With the virtual environment active on an Apple Silicon Mac:

```bash
python tools/build_macos.py
python tools/check_bundle.py
python tools/package_macos.py --version 0.1.0
open "dist/ILCE Toolkit.app"
```

Use the version declared in `pmca-gui.spec` when packaging. Bundle verification
checks the frozen worker, English/German translations, libusb, installer TLS
AES, APK/SPK conversion and the ad hoc code signature.

### Tests and releases

Run the desktop, worker and USB lifecycle tests without camera writes or network
access:

```bash
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
```

The [desktop workflow](.github/workflows/build.yml) tests and builds on an
Apple Silicon macOS runner. Matching version tags publish the verified app ZIP
and `SHA256SUMS` as a GitHub release. See [the release guide](docs/Releasing.md)
for versioning and updating the Homebrew cask.

Interface strings and source documentation use English. German translations are
in [`pmca/desktop/locales/de.json`](pmca/desktop/locales/de.json).

## Command-line tools

The original PMCA CLI remains available from the source checkout. The Homebrew
cask installs the desktop app. For CLI-only use, install `requirements.txt`
instead of `requirements-gui.txt`, plus the USB library for your platform.

With the virtual environment active:

```bash
python pmca-console.py --help
python pmca-console.py info
python pmca-console.py install -f /path/to/app.apk
python pmca-console.py install -i
python pmca-console.py updatershell
python pmca-console.py serviceshell
```

Use `python pmca-console.py <command> --help` for each command's arguments. The
macOS administrator retry and privacy-settings buttons belong to the desktop
interface; the CLI does not offer those dialogs.

## Resources and credits

- [Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE): original project and USB backends.
- [PMCADemo](https://github.com/ma1co/PMCADemo): example camera app.
- [OpenMemories: Framework](https://github.com/ma1co/OpenMemories-Framework): camera API framework for custom apps.
- [App installation protocol](docs/AppInstallation.md): background on the Sony APK/SPK installer.
- [nex-hack](http://www.personal-view.com/faqs/sony-hack/hack-development): earlier Sony camera reverse-engineering work.

Licensed under the [MIT License](LICENSE.txt). Original attribution is preserved.
