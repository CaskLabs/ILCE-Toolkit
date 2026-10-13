# Reverse Engineering Sony Digital Cameras
This tool interfaces with Sony digital cameras through USB. It allows to tweak settings, dump firmware, and in some cases install custom Android apps.

## Installation
There are two binaries:

* **pmca-console**: The main command line application
* **pmca-gui**: ILCE Toolkit, a macOS-first desktop interface for the complete command set

### Windows
The application should work fine on Windows using the operating system's mass storage and MTP USB drivers.

Download the [latest stable release](https://github.com/ma1co/Sony-PMCA-RE/releases/latest) or the newest [development build](https://ci.appveyor.com/project/ma1co/sony-pmca-re/build/artifacts).

### macOS
#### ILCE Toolkit (Apple Silicon)

The new desktop interface replaces the previous Tkinter GUI. Its primary target
is macOS 14 or newer on Apple Silicon (M1 and later).

Run from this checkout:

```bash
python3 -m venv .venv
source .venv/bin/activate
brew install libusb
python -m pip install -r requirements-gui.txt
python pmca-gui.py
```

Build a standalone arm64 app on an Apple Silicon Mac:

```bash
python tools/build_macos.py
open "dist/ILCE Toolkit.app"
```

The app bundles Python, Qt, libusb, the local installation certificate and the
updater payloads. No Python installation or Homebrew is needed on the target
Mac. Local builds are ad-hoc signed; public distribution requires Developer ID
signing and notarization. The existing CLI remains available.

| Area | Functions |
| --- | --- |
| Camera | Device, firmware, lens and GPS information; driver selection |
| Apps | Local APK installation and inspection, OpenMemories catalog, installer connection test, Sony-store queries and downloads |
| Shell & tweaks | Updater and service sessions, interactive Linux shell, all supported tweaks, file push/pull, bootloader and boot-ROM dumps, shell APK installation, backup read/write/patch/sync/protection |
| Firmware | Firmware update and matching images from ZIP archives |
| GPS | Local assist data or download from Sony |
| Wi-Fi & streaming | Display, JSON export and import; Multi-Wi-Fi |
| File tools | APK/SPK conversion and Backup.bin analysis |

Select an action in the sidebar. Local file fields also accept drag-and-drop.
Double-click an app in catalog results to prepare installation or download.
Shell sessions own the camera connection until **Sitzung beenden** is used;
their available tools depend on the camera/backend. **Linux-Shell verlassen**
returns to the PMCA session; **Strg+C senden** sends the interrupt character.
The protocol transports text, not a full terminal emulator.

For a service session on the a5000, disconnect USB, select **MENU → Setup →
USB Connection → Mass Storage** on the camera, reconnect USB and select the
automatic or libusb driver in the app. MTP mode cannot start service mode.
On macOS, the mass-storage kernel driver may own the interface. The app then
offers **Mit Administratorrechten starten** and requests authorization using
the macOS administrator dialog. Only the service worker is authorized. It
communicates with the GUI over an authenticated local socket, performs file
operations with the invoking user's effective permissions, and temporarily
raises its effective uid only around USB access and driver capture/restore. The
normal MTP app installer and camera queries do not request administrator rights.

Camera operations run in a separate process and cannot overlap. Reports and
exports are written through temporary files and only replace their targets on
success. Sony tokens are sent to the worker over stdin and are not stored in
preferences or passed on the command line. WLAN/streaming output can contain
credentials, so handle exported files and logs accordingly. Sony's online
services may no longer be available; the GUI reports backend failures.

Tests (no camera writes or network access):

```bash
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
python tools/check_bundle.py  # after building: verify the frozen worker and libusb
```

The GitHub Actions desktop workflow builds and tests on an Apple Silicon macOS
runner and uploads an app ZIP as a build artifact. It does not publish releases.

#### Original binaries

macOS binaries are also distributed, but less tested than the Windows equivalents. Getting the USB drivers to work may require some fiddling. To communicate with cameras in mass storage mode, Sony's [Camera Driver](https://support.d-imaging.sony.co.jp/mac/driver/11/ja/) has to be installed. Make sure to close all applications which could access USB drivers, including Photos, Dropbox and Google Drive.

The latest release binaries can be found in the [release section](https://github.com/ma1co/Sony-PMCA-RE/releases/latest).

### Linux
The application uses Python 3 and should work fine on Linux using libusb drivers.

Clone or download this repository, then run the following commands:
```bash
pip install -r requirements-gui.txt  # CLI and desktop dependencies
./pmca-console.py  # for the command line application
./pmca-gui.py  # for the gui application
```

## Usage
There are three main modes of interfacing with a camera:

### App Installer
If the camera supports *PlayMemories Camera Apps (PMCA)*, it is possible to install custom Android apps using this tool. A list of supported cameras can be found [here](https://openmemories.readthedocs.io/devices.html).

It is recommended to install the [*OpenMemories: Tweak*](https://github.com/ma1co/OpenMemories-Tweak) app. This app allows to tweak settings and to start *telnet* and *adb* servers to execute code on the system.

Other apps are available. A list can be found [here](https://github.com/ma1co/OpenMemories-AppList).

There are two ways to install apps:
* **pmca-gui**: In *Apps*, load the app catalog, double-click an app and install it, or select a local APK.
* **pmca-console**: Run `pmca-console install -i` to interactively select an app to install.

### Firmware Updater
Sony cameras can boot from a secondary partition for firmware updates. Using a custom firmware file, we can execute code in this mode. Note that the camera firmware itself remains untouched. The firmware update process is only used to execute custom code.

This mode does not require any special drivers, the operating system's mass storage USB driver is enough.

A list of supported camera models can be found [here](https://openmemories.readthedocs.io/devices.html). Devices based on the CXD90045 and CXD90057 architectures are not compatible, since their firmware is cryptographically signed.

There are two ways to use this:
* **pmca-gui**: In *Shell & Tweaks*, start an updater session. The session's *Tweaks* tab provides checkboxes and an apply button.
* **pmca-console**: Run `pmca-console updatershell`. There are commands available to dump the firmware, execute Linux commands, and to tweak settings.

Note that this requires rebooting the camera to firmware update mode. You will be guided through this process.

### Service Mode
Sony cameras have a USB mode called *senser mode*, which is used during servicing for calibration and other things. It can also be used to execute code on the running system.

Service mode has the best camera compatibility, but requires custom USB drivers.

It is supported in the command line application and in the desktop interface's *Shell & Tweaks* section:
* **pmca-console**: Run `pmca-console serviceshell`. There are commands available to dump the firmware and to execute Linux commands.

#### Windows Drivers
To use service mode on Windows, custom drivers have to be installed using [Zadig](http://zadig.akeo.ie/):
* Make sure the camera is connected in mass storage mode.
* In Zadig, check *Options -> List All Devices*, select the camera, select *libusb-win32* and click *Replace Driver*.
* Run `pmca-console serviceshell` to make the camera switch modes.
* Once the camera has switched, repeat the above step to install a driver for service mode.
* You should now be able to use `pmca-console serviceshell`.

To be able to use the camera normally again, the libusb drivers have to be uninstalled in device manager.

## Is it safe?
This is an experiment in a very early stage. All information has been found through reverse engineering. Even though everything worked fine for our developers, it could cause harm to your hardware. If you break your camera, you get to keep both pieces. **We won't take any responsibility.**

## What about custom apps?
It is possible to develop custom Android apps for supported cameras. Keep in mind that they should be compatible with Android 2.3.7. Debug and release certificates are accepted by the camera. See [*PMCADemo*](https://github.com/ma1co/PMCADemo) for a demo app.

There are a few special Sony APIs which allow you to take advantage of the features of your camera. They can be used through [*OpenMemories: Framework*](https://github.com/ma1co/OpenMemories-Framework).

## Special thanks
Without the work done by the people at [nex-hack](http://www.personal-view.com/faqs/sony-hack/hack-development), this wouldn't have been possible. Thanks a lot!
