"""Run packaged tests without live HTTP. Run with the main environment interpreter."""
import os
from contextlib import ExitStack, contextmanager
from pathlib import Path
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def offline_connections():
    if getattr(socket.socket.connect, '_chiheng_offline_guard', False):
        yield
        return
    connect = socket.socket.connect
    socketpair_code = getattr(socket.socketpair, '__code__', None)

    def guarded_connect(sock, address):
        caller = sys._getframe(1)
        # Windows asyncio uses the stdlib's authenticated loopback socketpair.
        if socketpair_code is not None and caller.f_code is socketpair_code:
            listener = caller.f_locals.get('lsock')
            if (sock is caller.f_locals.get('csock') and listener is not None
                    and address == listener.getsockname()[:2]
                    and address[0] in ('127.0.0.1', '::1')):
                return connect(sock, address)
        raise AssertionError('offline network blocked')

    guarded_connect._chiheng_offline_guard = True
    with ExitStack() as stack:
        stack.enter_context(patch.object(socket.socket, 'connect', guarded_connect))
        stack.enter_context(patch.object(socket.socket, 'connect_ex',
                                        side_effect=AssertionError('offline network blocked')))
        if os.name == 'nt':
            from asyncio.windows_events import IocpProactor
            # Proactor connects through ConnectEx/WSAConnect, bypassing socket.connect.
            stack.enter_context(patch.object(IocpProactor, 'connect',
                                            side_effect=AssertionError('offline network blocked')))
        yield


def main():
    if os.name == 'nt':
        os.environ['PYTHONUTF8'] = '1'
        if not sys.flags.utf8_mode:
            return subprocess.run([sys.executable, '-B', '-X', 'utf8', str(Path(__file__).resolve())]).returncode
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    # Only the vendor fixture temporarily loads the separately installed SDK1.
    from scrapling.fetchers import Fetcher
    with offline_connections(), \
         patch.object(Fetcher, 'get', side_effect=AssertionError('offline fetch blocked')):
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover(str(ROOT / 'tests')))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
