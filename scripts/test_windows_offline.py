"""Run packaged tests without live HTTP. Run with the main environment interpreter."""
import os
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def main():
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    # Only the vendor fixture temporarily loads the separately installed SDK1.
    from scrapling.fetchers import Fetcher
    with patch.object(socket.socket, 'connect', side_effect=AssertionError('offline network blocked')), \
         patch.object(socket.socket, 'connect_ex', side_effect=AssertionError('offline network blocked')), \
         patch.object(Fetcher, 'get', side_effect=AssertionError('offline fetch blocked')):
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover(str(ROOT / 'tests')))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
