"""Portable behavior runs on this host; native Windows checks remain explicit."""
import importlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from tests.platform_fixtures import symlink
from unittest.mock import Mock, patch

import library_transfer


class PortableLockTests(unittest.TestCase):
    @staticmethod
    def finish(process):
        # These probe children emit at most two lines, well below pipe capacity.
        process.wait(timeout=10)
        with process.stdout, process.stderr:
            return process.stdout.read(), process.stderr.read()

    def test_buffered_process_output_is_preserved(self):
        self.assertTrue(hasattr(self, 'finish'), 'A buffered-stream-safe finisher is required')
        process = subprocess.Popen([sys.executable, '-c', "print('ready\\nacquired', flush=True)"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        process.wait(timeout=10)
        self.assertEqual(process.stdout.readline().strip(), 'ready')
        output, errors = self.finish(process)
        self.assertEqual(output.strip(), 'acquired')
        self.assertEqual(errors, '')

    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('portable_lock'),
                             'shared portable lock API is required')
        self.api = importlib.import_module('portable_lock')
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'ledger'
        self.path.write_bytes(b'first record\n')

    def child(self, operation, wait=False):
        code = '''import sys
import portable_lock as lock
with open(sys.argv[1], 'rb') as stream:
    print('ready', flush=True)
    try:
        lock.flock(stream, int(sys.argv[2]))
    except BlockingIOError:
        print('busy', flush=True)
    else:
        print('acquired', flush=True)
'''
        process = subprocess.Popen([sys.executable, '-c', code, str(self.path), str(operation)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            cwd=Path(__file__).resolve().parents[1])
        self.addCleanup(lambda: process.poll() is None and process.kill())
        self.assertEqual(process.stdout.readline().strip(), 'ready')
        if wait:
            return process
        output, errors = self.finish(process)
        self.assertEqual(process.returncode, 0, errors)
        return output.strip()

    def test_exclusive_conflict_and_close_release_across_processes(self):
        with self.path.open('rb') as stream:
            self.api.flock(stream, self.api.LOCK_EX)
            self.assertEqual(self.child(self.api.LOCK_EX | self.api.LOCK_NB), 'busy')
            self.assertEqual(self.child(self.api.LOCK_SH | self.api.LOCK_NB), 'busy')
        self.assertEqual(self.child(self.api.LOCK_EX | self.api.LOCK_NB), 'acquired')

    def test_shared_readers_and_explicit_unlock(self):
        with self.path.open('rb') as stream:
            self.api.flock(stream.fileno(), self.api.LOCK_SH)
            self.assertEqual(self.child(self.api.LOCK_SH | self.api.LOCK_NB), 'acquired')
            self.assertEqual(self.child(self.api.LOCK_EX | self.api.LOCK_NB), 'busy')
            self.api.flock(stream, self.api.LOCK_UN)
            self.assertEqual(self.child(self.api.LOCK_EX | self.api.LOCK_NB), 'acquired')

    def test_blocking_wait_acquires_after_owner_closes(self):
        with self.path.open('rb') as stream:
            self.api.flock(stream, self.api.LOCK_EX)
            process = self.child(self.api.LOCK_EX, wait=True)
            with self.assertRaises(subprocess.TimeoutExpired):
                process.wait(timeout=0.2)
        output, errors = self.finish(process)
        self.assertEqual(process.returncode, 0, errors)
        self.assertEqual(output.strip(), 'acquired')

    def test_lock_does_not_move_offset_or_prevent_content_io(self):
        with self.path.open('r+b') as stream:
            stream.seek(2)
            self.api.flock(stream, self.api.LOCK_EX)
            self.assertEqual(stream.tell(), 2)
            self.assertEqual(self.path.read_bytes(), b'first record\n')
            stream.seek(0, os.SEEK_END)
            stream.write(b'next\n')
            stream.flush()
            self.api.flock(stream, self.api.LOCK_UN)
            self.assertEqual(stream.tell(), len(b'first record\nnext\n'))
        self.assertEqual(self.path.read_bytes(), b'first record\nnext\n')

    def test_posix_uses_existing_flock_protocol(self):
        if sys.platform == 'win32':
            self.skipTest('POSIX flock interoperation only')
        import fcntl
        with self.path.open('rb') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            self.assertEqual(self.child(self.api.LOCK_EX | self.api.LOCK_NB), 'busy')

    def test_windows_native_boundary_flags_offsets_and_busy_error(self):
        native = Mock()
        native.LockFileEx.return_value = 1
        native.UnlockFileEx.return_value = 1
        msvcrt = types.SimpleNamespace(get_osfhandle=Mock(return_value=2**40))
        with patch.dict(sys.modules, msvcrt=msvcrt), \
                patch('ctypes.WinDLL', return_value=native, create=True), \
                patch('ctypes.get_last_error', return_value=33, create=True):
            self.api._windows_flock(42, self.api.LOCK_EX | self.api.LOCK_NB)
            args = native.LockFileEx.call_args.args
            self.assertEqual(args[:5], (2**40, 3, 0, 1, 0))
            self.assertEqual((args[5]._obj.Offset, args[5]._obj.OffsetHigh),
                             (0xffffffff, 0x7fffffff))
            self.api._windows_flock(42, self.api.LOCK_SH)
            self.assertEqual(native.LockFileEx.call_args.args[1], 0)
            self.api._windows_flock(42, self.api.LOCK_UN)
            self.assertEqual(native.UnlockFileEx.call_args.args[:4], (2**40, 0, 1, 0))
            native.LockFileEx.return_value = 0
            with self.assertRaises(BlockingIOError):
                self.api._windows_flock(42, self.api.LOCK_EX | self.api.LOCK_NB)
            with patch('ctypes.get_last_error', return_value=5, create=True), \
                    patch('ctypes.WinError', return_value=PermissionError('denied'), create=True):
                with self.assertRaises(PermissionError):
                    self.api._windows_flock(42, self.api.LOCK_EX | self.api.LOCK_NB)

    @unittest.skipUnless(sys.platform == 'win32', 'PENDING: native Windows 10 execution required')
    def test_native_windows_readonly_exclusive_lock_and_unrestricted_data_read(self):
        with self.path.open('rb') as stream:
            self.api.flock(stream, self.api.LOCK_EX)
            self.assertEqual(stream.read(), b'first record\n')
            self.assertEqual(self.path.read_bytes(), b'first record\n')


class WindowsTransferTests(unittest.TestCase):
    def test_symlink_fixture_skips_only_known_capability_failures(self):
        for code in (1, 50, 1314):
            error = OSError('synthetic missing symlink capability')
            error.winerror = code
            link = Mock()
            link.symlink_to.side_effect = error
            with self.subTest(code=code), self.assertRaises(unittest.SkipTest):
                symlink(link, Path('target'))

    def test_symlink_fixture_keeps_other_errors_as_failures(self):
        for code in (5, 32, 183):
            error = OSError('synthetic unexpected filesystem failure')
            error.winerror = code
            link = Mock()
            link.symlink_to.side_effect = error
            with self.subTest(code=code), self.assertRaises(OSError) as raised:
                symlink(link, Path('target'))
            self.assertIs(raised.exception, error)

    def test_windows_unsafe_names_are_rejected_on_every_export_host(self):
        for name in ('CON', 'nul.json', 'COM1.txt', 'aux', 'LPT9.data', 'com¹.txt',
                     'name.', 'name ', 'bad*name', 'bad?name', 'bad<name', 'bad>name',
                     'bad|name', 'bad"name', 'NUL .txt', 'CONIN$.txt', 'CONOUT$'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                library_transfer._safe_name('data/quarantine/' + name)
        self.assertEqual(library_transfer._safe_name('data/quarantine/公开材料 1.txt'),
                         'data/quarantine/公开材料 1.txt')

    def test_windows_publication_uses_native_no_replace_rename_before_loading_libc(self):
        with patch.object(library_transfer.sys, 'platform', 'win32'), \
                patch.object(library_transfer.os, 'rename') as rename, \
                patch.object(library_transfer.ctypes, 'CDLL') as libc:
            library_transfer._rename_directory_no_replace('source', 'target')
            rename.assert_called_once_with('source', 'target')
            libc.assert_not_called()
            rename.side_effect = FileExistsError('target')
            with self.assertRaises(FileExistsError):
                library_transfer._rename_directory_no_replace('source', 'target')

    def test_windows_restore_refuses_symlink_ancestry_before_unpack(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            real = root / 'real'
            real.mkdir()
            alias = root / 'alias'
            symlink(alias, real, target_is_directory=True)
            with patch.object(library_transfer.sys, 'platform', 'win32'), \
                    patch.object(library_transfer, '_unpack_verified') as unpack:
                with self.assertRaisesRegex(ValueError, '[Ss]ymlink|[Rr]eparse'):
                    library_transfer.restore_library('unused.zip', alias / 'new')
                unpack.assert_not_called()

    def test_windows_restore_refuses_reparse_ancestry_before_unpack(self):
        with tempfile.TemporaryDirectory() as folder:
            real = Path(folder).resolve() / 'real'
            real.mkdir()
            original = Path.lstat
            def reparse(path, *args, **kwargs):
                if path == real:
                    return types.SimpleNamespace(st_mode=0o40700, st_file_attributes=0x400)
                return original(path, *args, **kwargs)
            with patch.object(library_transfer.sys, 'platform', 'win32'), \
                    patch.object(Path, 'lstat', reparse), \
                    patch.object(library_transfer, '_unpack_verified') as unpack:
                with self.assertRaisesRegex(ValueError, '[Rr]eparse'):
                    library_transfer.restore_library('unused.zip', real / 'new')
                unpack.assert_not_called()


if __name__ == '__main__':
    unittest.main()
