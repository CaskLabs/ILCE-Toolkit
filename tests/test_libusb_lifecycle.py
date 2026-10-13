from contextlib import nullcontext
import unittest
from unittest.mock import Mock, patch

import usb.core
from pmca.usb.driver import UsbDeviceHandle
from pmca.usb.driver.generic.libusb import UsbBackend, MtpContext, UsbCaptureRequired


class LibusbLifecycleTests(unittest.TestCase):
    def test_macos_repeated_reset_keeps_the_existing_claim(self):
        device = Mock()
        backend = UsbBackend(device)
        with patch('pmca.usb.driver.generic.libusb.sys.platform', 'darwin'), patch('usb.util.claim_interface') as claim, patch('usb.util.release_interface') as release:
            backend.reset()
            backend.reset()
        self.assertEqual(claim.call_count, 2)
        claim.assert_called_with(device, 0)
        release.assert_not_called()
        device.is_kernel_driver_active.assert_not_called()
        device.detach_kernel_driver.assert_not_called()
        backend.close()

    def test_macos_genuine_claim_failure_remains_an_error(self):
        device = Mock()
        device.get_active_configuration.return_value = {(0, 0): Mock(bInterfaceClass=6)}
        backend = UsbBackend(device)
        error = usb.core.USBError('Interface owned by another process', errno=13)
        with patch('pmca.usb.driver.generic.libusb.sys.platform', 'darwin'), patch('usb.util.claim_interface', side_effect=error):
            with self.assertRaises(usb.core.USBError):
                backend.reset()
        device.detach_kernel_driver.assert_not_called()
        backend.close()

    def test_mass_storage_kernel_driver_requests_admin_without_detaching(self):
        device = Mock()
        device.get_active_configuration.return_value = {(0, 0): Mock(bInterfaceClass=8)}
        device.is_kernel_driver_active.return_value = True
        backend = UsbBackend(device)
        error = usb.core.USBError('Access denied', errno=13)
        with patch('pmca.usb.driver.generic.libusb.sys.platform', 'darwin'), patch('usb.util.claim_interface', side_effect=error), patch('os.getuid', return_value=501):
            with self.assertRaises(UsbCaptureRequired):
                backend.reset()
        device.detach_kernel_driver.assert_not_called()
        backend.close()

    def test_authorized_capture_temporarily_raises_and_restores_effective_uid(self):
        backend = UsbBackend(Mock())
        effective = [501]
        changes = []

        def set_uid(uid):
            changes.append(uid)
            effective[0] = uid

        def capture(interface):
            self.assertEqual(effective[0], 0)
            self.assertEqual(interface, 0)
            raise usb.core.USBError('capture failed')

        with patch('os.geteuid', side_effect=lambda: effective[0]), patch('os.seteuid', side_effect=set_uid):
            with self.assertRaises(usb.core.USBError):
                backend._capture(capture)
        self.assertEqual(changes, [0, 501])
        self.assertEqual(effective[0], 501)
        backend.close()

    def test_authorized_mass_storage_capture_claims_again_and_reattaches_on_close(self):
        device = Mock()
        device.get_active_configuration.return_value = {(0, 0): Mock(bInterfaceClass=8)}
        device.is_kernel_driver_active.return_value = True
        backend = UsbBackend(device)
        error = usb.core.USBError('Access denied', errno=13)
        with patch('pmca.usb.driver.generic.libusb.sys.platform', 'darwin'), patch('usb.util.claim_interface', side_effect=[error, None]) as claim, patch('os.getuid', return_value=0), patch('os.geteuid', return_value=0), patch.object(backend, '_capture', side_effect=lambda operation: operation(0)), patch('usb.util.release_interface') as release, patch('usb.util.dispose_resources') as dispose:
            backend.reset()
            backend.close()
            self.assertEqual(claim.call_count, 2)
            device.detach_kernel_driver.assert_called_once_with(0)
            device.attach_kernel_driver.assert_called_once_with(0)
            release.assert_called_once_with(device, 0)
            dispose.assert_called_once_with(device)

    def test_claim_happens_before_authorized_capture_rights_are_dropped(self):
        device = Mock()
        device.get_active_configuration.return_value = {(0, 0): Mock(bInterfaceClass=8)}
        device.is_kernel_driver_active.return_value = True
        effective = [501]
        attempts = []
        backend = UsbBackend(device)

        def claim(device, interface):
            attempts.append(effective[0])
            if len(attempts) == 1:
                raise usb.core.USBError('Access denied', errno=13)
            self.assertEqual(effective[0], 0)

        with patch('pmca.usb.driver.generic.libusb.sys.platform', 'darwin'), patch('os.getuid', return_value=0), patch('os.geteuid', side_effect=lambda: effective[0]), patch('os.seteuid', side_effect=lambda uid: effective.__setitem__(0, uid)), patch('usb.util.claim_interface', side_effect=claim), patch('usb.util.release_interface'), patch('usb.util.dispose_resources'):
            backend.reset()
            self.assertEqual(effective[0], 501)
            backend.close()
            self.assertEqual(effective[0], 501)
        self.assertEqual(attempts, [0, 0])

    def test_linux_still_detaches_a_kernel_driver(self):
        device = Mock()
        device.is_kernel_driver_active.return_value = True
        backend = UsbBackend(device)
        with patch('pmca.usb.driver.generic.libusb.sys.platform', 'linux'):
            backend.reset()
        device.detach_kernel_driver.assert_called_once_with(0)
        backend.close()

    def test_context_releases_handles_after_success_and_failure(self):
        for fail in (False, True):
            with self.subTest(fail=fail), patch('usb.util.dispose_resources') as dispose:
                context = MtpContext()
                device = Mock()
                with self.assertRaises(RuntimeError) if fail else nullcontext():
                    with context:
                        backend = context._openBackend(UsbDeviceHandle(device, 0x054c, 0x08d3))
                        if fail:
                            raise RuntimeError('failed operation')
                dispose.assert_called_once_with(device)
                self.assertEqual(context._backends, [])
                backend.close()
                backend.__del__()
                dispose.assert_called_once_with(device)
