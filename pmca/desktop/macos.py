"""Keep an authorized worker associated with the invoking macOS user."""
import ctypes
import os


class _AuditMask(ctypes.Structure):
    _fields_ = [('success', ctypes.c_uint32), ('failure', ctypes.c_uint32)]


class _Terminal(ctypes.Structure):
    _fields_ = [('port', ctypes.c_int32), ('type', ctypes.c_uint32),
                ('address', ctypes.c_uint32 * 4)]


class _AuditInfo(ctypes.Structure):
    _fields_ = [('user', ctypes.c_uint32), ('mask', _AuditMask),
                ('terminal', _Terminal), ('session', ctypes.c_uint32),
                ('flags', ctypes.c_uint64)]


def _library():
    library = ctypes.CDLL('/usr/lib/libbsm.dylib', use_errno=True)
    for name in ('getaudit_addr', 'setaudit_addr'):
        function = getattr(library, name)
        function.argtypes = [ctypes.POINTER(_AuditInfo), ctypes.c_int]
        function.restype = ctypes.c_int
    return library


def _check(result):
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def audit_session():
    """Snapshot only the caller's audit identity, without changing permissions."""
    info = _AuditInfo()
    _check(_library().getaudit_addr(ctypes.byref(info), ctypes.sizeof(info)))
    return dict(user=info.user, flags=info.flags,
                terminal=dict(port=info.terminal.port, type=info.terminal.type,
                              address=list(info.terminal.address)))


def initialize_audit_session(user, session):
    """Create an attributed audit session before initializing IOKit.

    AppleScript authorization starts helpers with AU_DEFAUDITID (-1), which
    leaves removable-volume access without a logged-in TCC user. Preserve the
    invoking user's terminal/flags and the helper's existing audit masks; do
    not copy the all-ones masks returned to unprivileged callers.
    """
    if os.geteuid() != 0:
        raise PermissionError('The macOS user session requires an authorized helper.')
    if not isinstance(session, dict) or session.get('user') != user:
        raise ValueError('The macOS session does not match the invoking user.')
    library = _library()
    info = _AuditInfo()
    _check(library.getaudit_addr(ctypes.byref(info), ctypes.sizeof(info)))
    info.user = user
    info.session = 0xffffffff  # AU_ASSIGN_ASID: create a new session.
    info.flags = session['flags']
    terminal = session['terminal']
    info.terminal = _Terminal(terminal['port'], terminal['type'],
                             (ctypes.c_uint32 * 4)(*terminal['address']))
    _check(library.setaudit_addr(ctypes.byref(info), ctypes.sizeof(info)))
