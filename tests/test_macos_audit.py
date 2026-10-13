import ctypes
import sys
import unittest
from unittest.mock import Mock, patch

from pmca.desktop import macos


class MacAuditTests(unittest.TestCase):
    def test_authorized_helper_attributes_access_without_enabling_extra_auditing(self):
        library = Mock()
        session = dict(user=501, flags=0x6010,
                       terminal=dict(port=7, type=4, address=[0, 0, 0, 0]))

        def read(pointer, size):
            self.assertEqual(size, 48)
            info = ctypes.cast(pointer, ctypes.POINTER(macos._AuditInfo)).contents
            info.user = 0xffffffff
            info.mask.success = 5
            info.mask.failure = 9
            return 0

        def write(pointer, size):
            info = ctypes.cast(pointer, ctypes.POINTER(macos._AuditInfo)).contents
            self.assertEqual(info.user, 501)
            self.assertEqual(info.session, 0xffffffff)
            self.assertEqual(info.flags, 0x6010)
            self.assertEqual((info.mask.success, info.mask.failure), (5, 9))
            self.assertEqual((info.terminal.port, info.terminal.type), (7, 4))
            return 0

        library.getaudit_addr.side_effect = read
        library.setaudit_addr.side_effect = write
        with patch.object(macos, '_library', return_value=library), patch('os.geteuid', return_value=0):
            macos.initialize_audit_session(501, session)
        library.setaudit_addr.assert_called_once()

    def test_worker_rejects_mismatched_user_before_changing_its_identity(self):
        with patch('os.geteuid', return_value=0), patch.object(macos, '_library') as library:
            with self.assertRaises(ValueError):
                macos.initialize_audit_session(501, dict(user=502))
        library.assert_not_called()

    def test_failed_audit_initialization_is_reported(self):
        library = Mock()
        library.getaudit_addr.return_value = -1
        with patch('os.geteuid', return_value=0), patch.object(macos, '_library', return_value=library), patch('ctypes.get_errno', return_value=1):
            with self.assertRaises(PermissionError):
                macos.initialize_audit_session(501, dict(user=501))
        library.setaudit_addr.assert_not_called()

    @unittest.skipUnless(sys.platform == 'darwin', 'macOS audit API')
    def test_native_audit_snapshot_has_correct_abi(self):
        self.assertEqual(ctypes.sizeof(macos._AuditInfo), 48)
        session = macos.audit_session()
        self.assertEqual(len(session['terminal']['address']), 4)
        self.assertIn(session['terminal']['type'], (4, 16))
