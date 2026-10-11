"""Process locks for the library's open file objects and descriptors.

POSIX keeps its existing flock protocol. Windows coordinates cooperating writers
on one byte at 2**63 - 1, outside library contents, so locking a ledger does not
prevent ordinary reads or appends. Locks are released when the handle closes.
"""
import errno
import os

if os.name != 'nt':
    from fcntl import flock, LOCK_SH, LOCK_EX, LOCK_NB, LOCK_UN
else:
    LOCK_SH, LOCK_EX, LOCK_NB, LOCK_UN = 1, 2, 4, 8

    def flock(file, operation):
        return _windows_flock(file if isinstance(file, int) else file.fileno(), operation)


def _windows_flock(fd, operation):
    import ctypes
    from ctypes import wintypes
    import msvcrt

    if operation not in (LOCK_SH, LOCK_EX, LOCK_SH | LOCK_NB, LOCK_EX | LOCK_NB, LOCK_UN):
        raise ValueError('Unsupported lock operation')

    class OVERLAPPED(ctypes.Structure):
        _fields_ = [('Internal', ctypes.c_size_t), ('InternalHigh', ctypes.c_size_t),
                    ('Offset', wintypes.DWORD), ('OffsetHigh', wintypes.DWORD),
                    ('hEvent', wintypes.HANDLE)]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(OVERLAPPED)]
    kernel.UnlockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                   wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(OVERLAPPED)]
    kernel.LockFileEx.restype = kernel.UnlockFileEx.restype = wintypes.BOOL
    handle = msvcrt.get_osfhandle(fd)
    overlapped = OVERLAPPED(Offset=0xffffffff, OffsetHigh=0x7fffffff)
    if operation == LOCK_UN:
        ok = kernel.UnlockFileEx(handle, 0, 1, 0, ctypes.byref(overlapped))
    else:
        flags = (2 if operation & LOCK_EX else 0) | (1 if operation & LOCK_NB else 0)
        ok = kernel.LockFileEx(handle, flags, 0, 1, 0, ctypes.byref(overlapped))
    if not ok:
        code = ctypes.get_last_error()
        if code == 33 and operation & LOCK_NB:  # ERROR_LOCK_VIOLATION only.
            raise BlockingIOError(errno.EAGAIN, 'File lock is busy')
        if code == 158 and operation == LOCK_UN:  # Already unlocked, like flock.
            return
        raise ctypes.WinError(code)
