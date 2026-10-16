import asyncio
import socket
import unittest

from scripts.test_windows_offline import offline_connections


class OfflineConnectionsTests(unittest.TestCase):
    def test_default_asyncio_open_connection_is_blocked(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)

            async def connect():
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection(*listener.getsockname()), timeout=2)
                writer.close()
                await writer.wait_closed()

            with offline_connections(), self.assertRaisesRegex(AssertionError, 'offline network blocked'):
                asyncio.run(connect())

    def test_default_asyncio_sock_connect_is_blocked(self):
        with socket.socket() as listener, socket.socket() as client:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            client.setblocking(False)

            async def connect():
                await asyncio.wait_for(
                    asyncio.get_running_loop().sock_connect(client, listener.getsockname()), timeout=2)

            with offline_connections(), self.assertRaisesRegex(AssertionError, 'offline network blocked'):
                asyncio.run(connect())

    def test_ordinary_loopback_and_external_connections_remain_blocked(self):
        with offline_connections(), socket.socket() as sock:
            for address in (('127.0.0.1', 1), ('192.0.2.1', 80)):
                for operation in (sock.connect, sock.connect_ex):
                    with self.subTest(address=address, operation=operation), self.assertRaisesRegex(
                            AssertionError, 'offline network blocked'):
                        operation(address)

    def test_socketpair_can_only_connect_its_own_authenticated_peers(self):
        with offline_connections():
            left, right = socket.socketpair()
            with left, right:
                left.sendall(b'local wakeup')
                self.assertEqual(right.recv(12), b'local wakeup')
                with self.assertRaisesRegex(AssertionError, 'offline network blocked'):
                    left.connect(('127.0.0.1', 1))

    def test_asyncio_local_tasks_work_with_network_disabled(self):
        async def local_task():
            await asyncio.sleep(0)
            return 'synthetic'
        with offline_connections():
            self.assertEqual(asyncio.run(local_task()), 'synthetic')
