"""Blocking process locks; never continue without acquiring the ledger lock."""
import os

LOCK_EX, LOCK_UN = 2, 8

if os.name == 'nt':
    import ctypes
    from ctypes import wintypes
    import msvcrt

    class OVERLAPPED(ctypes.Structure):
        _fields_ = [('Internal', ctypes.c_size_t), ('InternalHigh', ctypes.c_size_t),
                    ('Offset', wintypes.DWORD), ('OffsetHigh', wintypes.DWORD),
                    ('hEvent', wintypes.HANDLE)]

    _kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    _kernel.LockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(OVERLAPPED)]
    _kernel.LockFileEx.restype = wintypes.BOOL
    _kernel.UnlockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                     wintypes.DWORD, ctypes.POINTER(OVERLAPPED)]
    _kernel.UnlockFileEx.restype = wintypes.BOOL

    def flock(file, operation):
        fd = file if isinstance(file, int) else file.fileno()
        handle = msvcrt.get_osfhandle(fd)
        overlapped = OVERLAPPED()  # Always lock byte zero, irrespective of append position.
        if operation == LOCK_EX:
            ok = _kernel.LockFileEx(handle, 2, 0, 1, 0, ctypes.byref(overlapped))
        elif operation == LOCK_UN:
            ok = _kernel.UnlockFileEx(handle, 0, 1, 0, ctypes.byref(overlapped))
        else:
            raise ValueError('unsupported lock operation')
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
else:
    from fcntl import flock, LOCK_EX, LOCK_UN
