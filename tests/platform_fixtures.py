"""Real local filesystem fixtures without weakening platform security checks."""
import errno
import os
from pathlib import Path
import unittest


def private_directory(path):
    path = Path(path)
    if os.name == 'nt':
        from windows_private import private_directory as create_private
        return create_private(path, create=True)
    path.mkdir(mode=0o700)
    return path


def symlink(link, target, *, target_is_directory=False):
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as error:
        if (getattr(error, 'winerror', None) in (1, 50, 1314)
                or error.errno in (errno.ENOSYS, errno.EOPNOTSUPP)):
            raise unittest.SkipTest(f'Symlink fixture unavailable: {error}') from error
        raise
