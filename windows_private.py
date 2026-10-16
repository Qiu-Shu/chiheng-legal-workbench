"""Windows local private files, using pywin32 (required only on Windows).

Only the current user, SYSTEM and Administrators are trusted. Existing ACLs are
inspected, never repaired. Native handles validate the actual object before I/O;
ancestor handles prevent renaming during open. This does not protect against a
malicious process running as the same user or an administrator rewriting data.
"""
from contextlib import closing, contextmanager, ExitStack
import ntpath
import os
from pathlib import Path, PureWindowsPath
import re

if os.name == 'nt':
    import msvcrt
    import ntsecuritycon
    import pywintypes
    import win32api
    import win32con
    import win32file
    import win32security


def validate_path(path):
    """Accept ordinary local drive paths only; reject Win32 aliasing and ADS."""
    name = os.fspath(path).replace('/', '\\')
    drive, tail = ntpath.splitdrive(name)
    if drive and (not re.fullmatch('[a-zA-Z]:', drive) or not tail.startswith('\\')):
        raise ValueError('仅接受本机普通盘符路径，不接受设备、UNC 或盘符相对路径')
    for part in tail.split('\\'):
        if not part:
            continue
        if (part in ('.', '..') or part.endswith((' ', '.'))
                or any(ord(char) < 32 or char in '<>:"|?*' for char in part)
                or re.fullmatch(r'(?i:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])',
                                part.split('.')[0].rstrip(' '))):
            raise ValueError('路径含不支持的 Windows 名称、数据流或相对跳转')
    full = PureWindowsPath(ntpath.abspath(name))
    if not re.fullmatch('[a-zA-Z]:', full.drive) or not full.is_absolute():
        raise ValueError('仅接受本机普通盘符路径')
    return full


def validate_acl(owner, control, aces, user, directory=False):
    """Fail closed on null/absent ACLs, unknown ACEs/flags and broad trustees.

    ACE tuples are (type, flags, mask, SID string). Only basic allow ACEs with
    OI/CI/INHERITED flags are accepted. A private root must be protected and all
    its entries must propagate to both files and directories.
    """
    trusted = {user, 'S-1-5-18', 'S-1-5-32-544'}
    if (owner not in trusted or not control & 4 or not aces
            or directory and not control & 0x1000):
        raise ValueError('私有对象的所有者或 DACL 不可信；不会自动修改既有权限')
    user_access = False
    for kind, flags, mask, sid in aces:
        if (kind != 0 or flags & ~0x13 or sid not in trusted
                or directory and flags & 3 != 3):
            raise ValueError('私有对象 DACL 含宽泛、未知或不安全的 ACE')
        user_access |= sid == user and bool(mask)
    if not user_access:
        raise ValueError('私有对象 DACL 必须明确允许当前用户访问')


def _user_sid():
    with closing(win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)) as token:
        return win32security.ConvertSidToStringSid(
            win32security.GetTokenInformation(token, win32security.TokenUser)[0])


def _check_acl(handle, directory=False):
    s = win32security
    descriptor = s.GetSecurityInfo(handle, s.SE_FILE_OBJECT,
                                   s.OWNER_SECURITY_INFORMATION | s.DACL_SECURITY_INFORMATION)
    acl = descriptor.GetSecurityDescriptorDacl()
    aces = []
    if acl is not None:
        for index in range(acl.GetAceCount()):
            ace = acl.GetAce(index)
            if len(ace) != 3 or ace[0][0] != s.ACCESS_ALLOWED_ACE_TYPE:
                raise ValueError('不支持的私有对象 ACE 类型')
            aces.append((*ace[0], ace[1], s.ConvertSidToStringSid(ace[2])))
    validate_acl(s.ConvertSidToStringSid(descriptor.GetSecurityDescriptorOwner()),
                 descriptor.GetSecurityDescriptorControl()[0], aces, _user_sid(), directory)


def _open_handle(path, access, disposition):
    try:
        return win32file.CreateFile(str(path), access,
            win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE, None, disposition,
            win32file.FILE_FLAG_OPEN_REPARSE_POINT | win32con.FILE_FLAG_BACKUP_SEMANTICS, None)
    except pywintypes.error as error:
        if error.winerror in (2, 3):
            raise FileNotFoundError(str(path)) from error
        if error.winerror in (80, 183):
            raise FileExistsError(str(path)) from error
        raise


def _check_object(handle, directory=False):
    info = win32file.GetFileInformationByHandle(handle)
    attrs = info[0]
    if (win32file.GetFileType(handle) != win32file.FILE_TYPE_DISK
            or attrs & (win32con.FILE_ATTRIBUTE_REPARSE_POINT | win32con.FILE_ATTRIBUTE_DEVICE)
            or bool(attrs & win32con.FILE_ATTRIBUTE_DIRECTORY) != directory
            or not directory and info[7] != 1):
        raise ValueError('仅接受无重解析点的普通目录或无硬链接的普通文件')


@contextmanager
def _parents(path):
    with ExitStack() as stack:
        for parent in reversed(path.parents):
            # Zero access does not participate in Windows delete-sharing checks.
            handle = _open_handle(parent, ntsecuritycon.FILE_LIST_DIRECTORY, win32con.OPEN_EXISTING)
            stack.callback(handle.Close)
            _check_object(handle, directory=True)
        yield


def private_directory(path, create=False):
    """Create with a protected inheritable ACL, or validate an existing root."""
    path = validate_path(path)
    with _parents(path):
        if create:
            user = _user_sid()
            descriptor = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
                f'O:{user}D:P(A;OICI;FA;;;{user})(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)', 1)
            attributes = pywintypes.SECURITY_ATTRIBUTES()
            attributes.SECURITY_DESCRIPTOR = descriptor
            attributes.bInheritHandle = False
            try:
                win32file.CreateDirectory(str(path), attributes)
            except pywintypes.error as error:
                if error.winerror != 183:
                    raise
        with closing(_open_handle(path, win32con.READ_CONTROL, win32con.OPEN_EXISTING)) as handle:
            _check_object(handle, directory=True)
            _check_acl(handle, directory=True)
    return Path(path)


def open_file(path, private=False, writable=False, create=False, exclusive=False):
    """Return an owned CRT fd validated on the same native handle before I/O.

    Creation never truncates an existing file. New private files must inherit a
    checked private parent ACL. Closing the fd also closes its native handle,
    retaining compatibility with portable_lock.
    """
    path = validate_path(path)
    with _parents(path):
        if create and private:
            private_directory(path.parent)
        access = win32con.GENERIC_READ | (win32con.GENERIC_WRITE if writable or create else 0)
        if private:
            access |= win32con.READ_CONTROL
        disposition = (win32con.CREATE_NEW if exclusive else win32con.OPEN_ALWAYS) if create else win32con.OPEN_EXISTING
        handle = _open_handle(path, access, disposition)
        try:
            _check_object(handle)
            if private:
                _check_acl(handle)
            flags = (os.O_RDWR if writable or create else os.O_RDONLY) | os.O_BINARY | os.O_NOINHERIT
            fd = msvcrt.open_osfhandle(int(handle), flags)
            handle.Detach()  # The CRT owns the handle only after successful conversion.
            return fd
        finally:
            handle.Close()
