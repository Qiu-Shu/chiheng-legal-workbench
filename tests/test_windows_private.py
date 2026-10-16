"""Portable policy checks plus explicit native Windows security acceptance tests."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from contextlib import ExitStack, nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import windows_private as private


class WindowsPrivatePolicyTests(unittest.TestCase):
    def test_parent_handles_participate_in_delete_sharing_and_close_on_error(self):
        constants = SimpleNamespace(OPEN_EXISTING=3, FILE_SHARE_READ=1, FILE_SHARE_WRITE=2,
            FILE_FLAG_BACKUP_SEMANTICS=0x2000000)
        path = private.validate_path(r'C:\parent\child\data')
        for fail_check in (False, True):
            with self.subTest(fail_check=fail_check), ExitStack() as stack:
                handles = [MagicMock() for _ in path.parents]
                create = MagicMock(side_effect=handles)
                stack.enter_context(patch.object(private, 'win32con', constants, create=True))
                stack.enter_context(patch.object(private, 'ntsecuritycon',
                    SimpleNamespace(FILE_LIST_DIRECTORY=1), create=True))
                stack.enter_context(patch.object(private, 'win32file',
                    SimpleNamespace(CreateFile=create, FILE_FLAG_OPEN_REPARSE_POINT=0x200000), create=True))
                stack.enter_context(patch.object(private, '_check_object',
                    side_effect=[None, ValueError('unsafe ancestor')] if fail_check else None))
                if fail_check:
                    with self.assertRaisesRegex(ValueError, 'unsafe ancestor'):
                        with private._parents(path):
                            self.fail('unsafe ancestor reached the body')
                else:
                    with private._parents(path):
                        for handle in handles:
                            handle.Close.assert_not_called()
                for call in create.call_args_list:
                    self.assertEqual(call.args[1], 1)  # FILE_LIST_DIRECTORY participates in sharing.
                    self.assertEqual(call.args[2], 3)  # FILE_SHARE_DELETE remains absent.
                for handle in handles[:create.call_count]:
                    handle.Close.assert_called_once()
                for handle in handles[create.call_count:]:
                    handle.Close.assert_not_called()

    def test_native_open_contract_same_handle_and_failure_cleanup(self):
        constants = SimpleNamespace(GENERIC_READ=0x80000000, GENERIC_WRITE=0x40000000,
            READ_CONTROL=0x20000, OPEN_EXISTING=3, OPEN_ALWAYS=4, CREATE_NEW=1,
            FILE_SHARE_READ=1, FILE_SHARE_WRITE=2,
            FILE_FLAG_BACKUP_SEMANTICS=0x2000000, FILE_ATTRIBUTE_REPARSE_POINT=1024,
            FILE_ATTRIBUTE_DEVICE=64, FILE_ATTRIBUTE_DIRECTORY=16)
        for failure in (None, 'acl', 'links', 'reparse', 'directory', 'crt'):
            with self.subTest(failure=failure), ExitStack() as stack:
                handle = MagicMock()
                handle.__int__.return_value = 123
                file_api = SimpleNamespace(CreateFile=MagicMock(return_value=handle), FILE_FLAG_OPEN_REPARSE_POINT=0x200000,
                    FILE_TYPE_DISK=1, GetFileType=MagicMock(return_value=1),
                    GetFileInformationByHandle=MagicMock(return_value=(
                        1024 if failure == 'reparse' else 16 if failure == 'directory' else 0,
                        None, None, None, 0, 0, 0, 2 if failure == 'links' else 1, 0, 1)))
                crt = SimpleNamespace(open_osfhandle=MagicMock(return_value=456))
                if failure == 'crt':
                    crt.open_osfhandle.side_effect = OSError('conversion failed')
                for name, value in [('win32con', constants), ('win32file', file_api),
                                    ('msvcrt', crt)]:
                    stack.enter_context(patch.object(private, name, value, create=True))
                stack.enter_context(patch.object(private, '_parents', return_value=nullcontext()))
                acl = stack.enter_context(patch.object(private, '_check_acl',
                    side_effect=ValueError('unsafe ACL') if failure == 'acl' else None))
                for name in ('O_BINARY', 'O_NOINHERIT'):
                    stack.enter_context(patch.object(private.os, name, 0, create=True))
                if failure:
                    with self.assertRaises((ValueError, OSError)):
                        private.open_file(r'C:\private\record', private=True)
                    handle.Detach.assert_not_called()
                    if failure != 'crt':
                        crt.open_osfhandle.assert_not_called()
                else:
                    self.assertEqual(private.open_file(r'C:\private\record', private=True), 456)
                    acl.assert_called_once_with(handle)
                    file_api.GetFileInformationByHandle.assert_called_once_with(handle)
                    handle.Detach.assert_called_once()
                    self.assertEqual(crt.open_osfhandle.call_args.args[0], 123)
                handle.Close.assert_called_once()
                args = file_api.CreateFile.call_args.args
                self.assertEqual(args[2], 3)  # No delete-sharing while validating.
                self.assertTrue(args[5] & file_api.FILE_FLAG_OPEN_REPARSE_POINT)

    def test_ancestors_remain_open_through_target_validation_and_crt_transfer(self):
        constants = SimpleNamespace(GENERIC_READ=0x80000000, READ_CONTROL=0x20000,
                                    OPEN_EXISTING=3)
        path = private.validate_path(r'C:\parent\data')
        handles = [MagicMock() for _ in range(len(path.parents) + 1)]
        handles[-1].__int__.return_value = 123
        checkpoints = []

        def held(checkpoint):
            for handle in handles:
                handle.Close.assert_not_called()
            checkpoints.append(checkpoint)

        def check_object(handle, directory=False):
            if not directory:
                held('object')

        def transfer(handle, flags):
            self.assertEqual(handle, 123)
            held('crt')
            return 456

        with ExitStack() as stack:
            for name, value in [('win32con', constants),
                                ('ntsecuritycon', SimpleNamespace(FILE_LIST_DIRECTORY=1)),
                                ('msvcrt', SimpleNamespace(open_osfhandle=transfer))]:
                stack.enter_context(patch.object(private, name, value, create=True))
            for name in ('O_BINARY', 'O_NOINHERIT'):
                stack.enter_context(patch.object(private.os, name, 0, create=True))
            stack.enter_context(patch.object(private, '_open_handle', side_effect=handles))
            stack.enter_context(patch.object(private, '_check_object', side_effect=check_object))
            stack.enter_context(patch.object(private, '_check_acl', side_effect=lambda handle: held('acl')))
            self.assertEqual(private.open_file(path, private=True), 456)
        self.assertEqual(checkpoints, ['object', 'acl', 'crt'])
        for handle in handles:
            handle.Close.assert_called_once()
        handles[-1].Detach.assert_called_once()

    def test_only_genuine_exists_errors_are_classified_as_exists(self):
        class ApiError(Exception):
            def __init__(self, code):
                self.winerror = code
        constants = SimpleNamespace(FILE_SHARE_READ=1, FILE_SHARE_WRITE=2,
            FILE_FLAG_BACKUP_SEMANTICS=0x2000000)
        for code, expected in [(2, FileNotFoundError), (3, FileNotFoundError),
                               (80, FileExistsError), (183, FileExistsError), (5, ApiError)]:
            with self.subTest(code=code), patch.object(private, 'win32con', constants, create=True), \
                    patch.object(private, 'pywintypes', SimpleNamespace(error=ApiError), create=True), \
                    patch.object(private, 'win32file',
                        SimpleNamespace(CreateFile=MagicMock(side_effect=ApiError(code)),
                            FILE_FLAG_OPEN_REPARSE_POINT=0x200000), create=True):
                with self.assertRaises(expected):
                    private._open_handle(r'C:\safe\data', 0, 3)

    def test_unsupported_windows_names_are_rejected_before_io(self):
        for name in (r'C:\case\a:stream', r'C:\case\NUL.txt', r'C:\case\COM¹',
                     r'C:\case\LPT9.log', r'C:\case\trailing.', r'C:\case\space ',
                     r'\\server\share\case', r'\\?\C:\case', r'\\.\pipe\x',
                     r'C:case', r'C:\case\..\other', 'C:\\case\\bad\x00name',
                     r'C:\case\a*b', r'C:\case\CONIN$'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                private.validate_path(name)
        self.assertEqual(str(private.validate_path(r'C:\safe\材料.txt')), r'C:\safe\材料.txt')

    def test_acl_is_closed_to_untrusted_owners_and_every_unknown_ace(self):
        user = 'S-1-5-21-1-2-3-1000'
        safe = [(0, 3, 0x1f01ff, sid) for sid in (user, 'S-1-5-18', 'S-1-5-32-544')]
        private.validate_acl(user, 0x1004, safe, user, directory=True)
        private.validate_acl(user, 4, [(0, 16, 0x120089, user)], user)
        bad = [None, [], safe + [(0, 3, 1, 'S-1-1-0')],
               safe + [(1, 3, 1, user)], safe + [(5, 3, 1, user)],
               safe + [(0, 8, 1, user)], safe + [(0, 64, 1, user)]]
        for aces in bad:
            with self.subTest(aces=aces), self.assertRaises(ValueError):
                private.validate_acl(user, 0x1004, aces, user, directory=True)
        for owner, control, aces in [('S-1-1-0', 0x1004, safe),
                                     (user, 4, safe), (user, 0x1000, safe),
                                     (user, 0x1004, [(0, 0, 1, user)])]:
            with self.assertRaises(ValueError):
                private.validate_acl(owner, control, aces, user, directory=True)


@unittest.skipUnless(os.name == 'nt', 'PENDING: requires native Windows and pywin32')
class WindowsPrivateNativeTests(unittest.TestCase):
    def setUp(self):
        import win32security
        self.security = win32security
        self.tmp = tempfile.TemporaryDirectory()
        self.root = private.private_directory(Path(self.tmp.name) / 'hearing', create=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_held_parent_blocks_rename_and_releases_on_success_and_error(self):
        renamed = self.root.with_name('renamed')
        for fail_body in (False, True):
            with self.subTest(fail_body=fail_body):
                try:
                    with private._parents(private.validate_path(self.root / 'child')):
                        with self.assertRaises(OSError) as blocked:
                            os.rename(self.root, renamed)
                        self.assertEqual(blocked.exception.winerror, 32)
                        if fail_body:
                            raise ValueError('simulated body failure')
                except ValueError as error:
                    self.assertTrue(fail_body)
                    self.assertEqual(str(error), 'simulated body failure')
                os.rename(self.root, renamed)
                os.rename(renamed, self.root)

    def test_directory_creation_retains_parent_through_acl_check(self):
        renamed = self.root.with_name('renamed')
        create_directory = private.win32file.CreateDirectory
        check_acl = private._check_acl
        checkpoints = []

        def assert_parent_held():
            with self.assertRaises(OSError) as blocked:
                os.rename(self.root, renamed)
            self.assertEqual(blocked.exception.winerror, 32)

        def create(path, attributes):
            assert_parent_held()
            checkpoints.append('create')
            return create_directory(path, attributes)

        def check(handle, directory=False):
            assert_parent_held()
            checkpoints.append('acl')
            return check_acl(handle, directory=directory)

        with patch.object(private.win32file, 'CreateDirectory', side_effect=create), \
                patch.object(private, '_check_acl', side_effect=check):
            private.private_directory(self.root / 'child', create=True)
        self.assertEqual(checkpoints, ['create', 'acl'])
        os.rename(self.root, renamed)
        os.rename(renamed, self.root)

    def test_synthetic_full_hearing_read_append_and_duplicate_preservation(self):
        from mock_hearing import create_session, append_turn, load_session, ROLES, STAGES
        material = self.root / '材料.txt'
        material.write_text('合成测试材料。', encoding='utf-8')
        packet = dict(case_id='windows-synthetic', procedure='civil_first_instance',
                      our_role='plaintiff', synthetic=True, human_review=None,
                      materials=[dict(id='M1', relative_path=material.name,
                                      sha256=hashlib.sha256(material.read_bytes()).hexdigest())])
        expected = create_session(self.root, packet)
        self.assertEqual(load_session(self.root), expected)
        for stage in STAGES:
            for role in sorted(ROLES[stage]):
                expected = append_turn(self.root, dict(case_id=packet['case_id'], stage=stage,
                    role=role, text='合成陈述。', material_ids=['M1'], source_cards=[],
                    unresolved=['仅为测试，未检索。']))
                self.assertEqual(load_session(self.root), expected)
        self.assertTrue(expected['completed'])
        before = (self.root / 'session.json').read_bytes()
        with self.assertRaises(FileExistsError):
            create_session(self.root, packet)
        self.assertEqual((self.root / 'session.json').read_bytes(), before)
        for name in ('session.json', '.session.lock'):
            os.close(private.open_file(self.root / name, private=True))

    def test_broad_and_null_acl_rejected_without_repair(self):
        s = self.security
        for name, dacl in [('broad', s.ConvertStringSecurityDescriptorToSecurityDescriptor(
                'D:P(A;OICI;FA;;;WD)', 1).GetSecurityDescriptorDacl()), ('null', None)]:
            target = private.private_directory(self.root / name, create=True)
            s.SetNamedSecurityInfo(str(target), s.SE_FILE_OBJECT,
                s.DACL_SECURITY_INFORMATION | s.PROTECTED_DACL_SECURITY_INFORMATION,
                None, None, dacl, None)
            before = bytes(s.GetFileSecurity(str(target), s.DACL_SECURITY_INFORMATION))
            with self.assertRaises(ValueError):
                private.private_directory(target, create=True)
            after = bytes(s.GetFileSecurity(str(target), s.DACL_SECURITY_INFORMATION))
            self.assertEqual(before, after)

    def test_private_file_acl_and_hardlinks_are_rejected(self):
        s = self.security
        path = self.root / 'data'
        os.close(private.open_file(path, private=True, create=True))
        alias = self.root / 'alias'
        os.link(path, alias)
        with self.assertRaises(ValueError):
            private.open_file(path, private=True)
        alias.unlink()
        dacl = s.ConvertStringSecurityDescriptorToSecurityDescriptor('D:P(A;;FA;;;WD)', 1).GetSecurityDescriptorDacl()
        s.SetNamedSecurityInfo(str(path), s.SE_FILE_OBJECT,
            s.DACL_SECURITY_INFORMATION | s.PROTECTED_DACL_SECURITY_INFORMATION,
            None, None, dacl, None)
        with self.assertRaises(ValueError):
            private.open_file(path, private=True)

    def test_windows_material_aliases_are_refused(self):
        from mock_hearing import create_session
        packet = dict(case_id='aliases', procedure='civil_first_instance',
                      our_role='plaintiff', synthetic=True, human_review=None, materials=[])
        for name in ('C:material.txt', 'data:stream', 'NUL.txt', 'data.',
                     '.SESSION.LOCK', 'SESSION.JSON'):
            packet['materials'] = [dict(id='M1', relative_path=name, sha256='0' * 64)]
            with self.subTest(name=name), self.assertRaises(ValueError):
                create_session(self.root, packet)

    def test_junction_root_and_material_ancestor_are_rejected(self):
        target = private.private_directory(self.root / 'target', create=True)
        (target / 'material.txt').write_text('synthetic', encoding='utf-8')
        alias = self.root / 'junction'
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(alias), str(target)], check=True,
                       capture_output=True)
        try:
            with self.assertRaises(ValueError):
                private.private_directory(alias)
            with self.assertRaises(ValueError):
                private.open_file(alias / 'material.txt')
            with self.assertRaises(ValueError):
                private.open_file(alias)
        finally:
            alias.rmdir()

    def test_security_failure_never_becomes_file_exists(self):
        from mock_hearing import create_session
        s = self.security
        path = self.root / 'session.json'
        path.write_text('sentinel', encoding='utf-8')
        dacl = s.ConvertStringSecurityDescriptorToSecurityDescriptor('D:P(A;;FA;;;WD)', 1).GetSecurityDescriptorDacl()
        s.SetNamedSecurityInfo(str(path), s.SE_FILE_OBJECT,
            s.DACL_SECURITY_INFORMATION | s.PROTECTED_DACL_SECURITY_INFORMATION,
            None, None, dacl, None)
        with self.assertRaises(ValueError):
            create_session(self.root, {})
        self.assertEqual(path.read_text(), 'sentinel')
