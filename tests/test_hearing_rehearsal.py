import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from tests.platform_fixtures import private_directory, symlink
from unittest.mock import patch

import mock_hearing
from mock_hearing import append_turn, create_session, hearing_progress, load_session


ROOT = Path(__file__).resolve().parents[1]


def digest(session):
    content = {key: value for key, value in session.items() if key != 'content_sha256'}
    raw = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


class HearingRehearsalTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.parent = self.root / 'parent'
        self.child = self.root / 'child'
        private_directory(self.parent)
        private_directory(self.child)
        self.packet = dict(case_id='synthetic', procedure='civil_first_instance',
                           our_role='plaintiff', synthetic=True, human_review=None,
                           materials=[])
        self.focus = ['补充举证', '练习追问']
        create_session(self.parent, self.packet)
        question = dict(question_id='Q1', text='是否收到？', addressed_to='plaintiff')
        task = dict(task_id='T1', text='补充材料。', kind='wording', status='open',
                    material_ids=[], review_note=None)
        append_turn(self.parent, self.turn(tracking=dict(issue_id='I1', questions=[question],
                    responses=[], tasks=[task], law_checks=[])))
        append_turn(self.parent, self.turn(role='plaintiff', tracking=dict(issue_id='I1',
                    questions=[], responses=[dict(question_id='Q1', kind='answer', text='已收到。')],
                    tasks=[{**task, 'status': 'addressed_pending_review', 'review_note': '待律师核验'}],
                    law_checks=[])))
        for stage, roles in [('issues', ['defendant']), ('evidence', ['plaintiff', 'defendant']),
                             ('questions', ['moderator', 'plaintiff', 'defendant']),
                             ('debate', ['plaintiff', 'defendant']), ('review', ['reviewer'])]:
            for role in roles:
                append_turn(self.parent, self.turn(stage, role))
        self.previous = load_session(self.parent)
        self.parent_bytes = (self.parent / 'session.json').read_bytes()

    def turn(self, stage='issues', role='moderator', **changes):
        return dict(case_id='synthetic', stage=stage, role=role,
                    text='是否收到？已收到。补充材料。', material_ids=[], source_cards=[],
                    unresolved=['尚未核实'], **changes)

    def rehearse(self, packet=None, focus=None, root=None, previous=None):
        creator = getattr(mock_hearing, 'create_rehearsal', None)
        self.assertTrue(callable(creator), '缺少 create_rehearsal API')
        return creator(self.child if root is None else root,
                       self.packet if packet is None else packet,
                       self.parent if previous is None else previous,
                       self.focus if focus is None else focus)

    def assert_no_child(self):
        self.assertFalse((self.child / 'session.json').exists())
        self.assertFalse(list(self.child.glob('.session-*.tmp')))

    def assert_parent_unchanged(self):
        self.assertEqual((self.parent / 'session.json').read_bytes(), self.parent_bytes)

    def save_rehashed(self, session, root=None):
        session['content_sha256'] = digest(session)
        (self.child if root is None else root).joinpath('session.json').write_text(
            json.dumps(session, ensure_ascii=False), encoding='utf-8')

    def cli(self, operation, root=None, value=None, previous=None):
        args = [sys.executable, '-B', str(ROOT / 'scripts/mock_hearing_session.py'),
                operation, '--case-root', str(self.child if root is None else root)]
        if previous is not None:
            args.extend(['--previous-case-root', str(previous)])
        if value is not None:
            path = self.root / 'input.json'
            path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
            args.extend(['--input', str(path)])
        return subprocess.run(args, text=True, capture_output=True)

    def test_completed_parent_generates_exact_link_and_empty_independent_child(self):
        packet, focus = copy.deepcopy(self.packet), list(self.focus)
        self.assertTrue(self.previous['completed'])
        self.assertEqual(len(self.previous['turns']), 11)
        with patch('mock_hearing.load_session', wraps=load_session) as loader:
            session = self.rehearse()
        loader.assert_called_once_with(self.parent)
        self.assertEqual(session['rehearsal_of'], dict(case_id='synthetic',
            content_sha256=self.previous['content_sha256'], turn_count=11, focus=self.focus))
        self.assertEqual(session['turns'], [])
        self.assertEqual(session['stage'], 'issues')
        self.assertFalse(session['completed'])
        self.assertIsNone(session['human_review'])
        self.assertEqual(session['content_sha256'], digest(session))
        self.assertEqual(load_session(self.child), session)
        self.assertEqual(hearing_progress(self.child)['issues'], [])
        self.assertFalse(hearing_progress(self.child)['tracking_recorded'])
        self.assertEqual((self.packet, self.focus), (packet, focus))
        self.assertNotIn(str(self.root), json.dumps(session))
        if os.name != 'nt':
            self.assertEqual(stat.S_IMODE((self.child / 'session.json').stat().st_mode), 0o600)
        self.assert_parent_unchanged()

    def test_focus_requires_native_nonempty_unique_list_of_nonempty_strings(self):
        creator = getattr(mock_hearing, 'create_rehearsal', None)
        self.assertTrue(callable(creator), '缺少 create_rehearsal API')
        for focus in (None, (), ('重点',), [], '', '重点', {}, [None], [1], [False], [[]],
                      [''], [' '], ['重点', '重点']):
            with self.subTest(focus=focus), self.assertRaises(ValueError):
                creator(self.child, self.packet, self.parent, focus)
            self.assert_no_child()
            self.assert_parent_unchanged()

    def test_identity_mismatches_and_packet_extra_fields_rejected(self):
        for changes in ({'case_id': 'other'}, {'procedure': 'criminal'},
                        {'our_role': 'defendant'}, {'synthetic': False}, {'synthetic': 1},
                        {'human_review': '已批准'}, {'rehearsal_of': {}}, {'focus': self.focus}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.rehearse(packet={**self.packet, **changes})
            self.assert_no_child()
            self.assert_parent_unchanged()
        for packet in ([], 'packet', {}, {'case_id': 'synthetic'}):
            with self.subTest(packet=packet), self.assertRaises(ValueError):
                self.rehearse(packet=packet)
            self.assert_no_child()

    def test_incomplete_and_legacy_parents_rejected(self):
        incomplete = self.root / 'incomplete'
        create_session(incomplete, self.packet)
        before = (incomplete / 'session.json').read_bytes()
        with self.assertRaises(ValueError):
            self.rehearse(previous=incomplete)
        self.assertEqual((incomplete / 'session.json').read_bytes(), before)
        legacy = {key: value for key, value in self.previous.items()
                  if key not in ('schema_version', 'content_sha256')}
        legacy['turns'] = [{key: value for key, value in turn.items() if key != 'tracking'}
                           for turn in legacy['turns']]
        (self.parent / 'session.json').write_text(json.dumps(legacy), encoding='utf-8')
        before = (self.parent / 'session.json').read_bytes()
        self.assertTrue(load_session(self.parent)['completed'])
        with self.assertRaises(ValueError):
            self.rehearse()
        self.assertEqual((self.parent / 'session.json').read_bytes(), before)
        self.assert_no_child()

    def test_parent_must_pass_real_load_validation(self):
        changed = copy.deepcopy(self.previous)
        changed['turns'][0]['text'] = '篡改'
        (self.parent / 'session.json').write_text(json.dumps(changed), encoding='utf-8')
        before = (self.parent / 'session.json').read_bytes()
        with self.assertRaises(ValueError):
            self.rehearse()
        self.assert_no_child()
        self.assertEqual((self.parent / 'session.json').read_bytes(), before)

    def test_same_directory_and_existing_child_do_not_overwrite(self):
        with self.assertRaises(ValueError):
            self.rehearse(root=self.parent / '.')
        self.assert_parent_unchanged()
        create_session(self.child, self.packet)
        before = (self.child / 'session.json').read_bytes()
        with self.assertRaises((ValueError, FileExistsError)):
            self.rehearse()
        self.assertEqual((self.child / 'session.json').read_bytes(), before)
        self.assert_parent_unchanged()

    def test_atomic_creation_contains_link_before_first_publication(self):
        original_write = mock_hearing._write
        publications = []

        def observe(root, session, create=False):
            self.assertTrue(create)
            self.assertEqual(session['rehearsal_of']['content_sha256'], self.previous['content_sha256'])
            publications.append(copy.deepcopy(session))
            return original_write(root, session, create=create)

        with patch('mock_hearing._write', side_effect=observe):
            session = self.rehearse()
        self.assertEqual(publications, [session])
        self.assert_parent_unchanged()

    def test_fsync_and_publish_failure_leave_no_child_session_or_temporary_file(self):
        for name in ('fsync', 'rename' if os.name == 'nt' else 'link'):
            with self.subTest(name=name), patch('mock_hearing.os.' + name,
                    side_effect=OSError('injected write failure')):
                with self.assertRaises(OSError):
                    self.rehearse()
            self.assert_no_child()
            self.assert_parent_unchanged()

    def test_explicit_materials_are_new_and_unlisted_files_are_not_scanned(self):
        material = self.child / 'new.txt'
        material.write_text('新的明确材料', encoding='utf-8')
        (self.child / 'unlisted.bin').write_bytes(b'\xff')
        (self.parent / 'private.txt').write_text('不应继承', encoding='utf-8')
        packet = {**self.packet, 'materials': [dict(id='NEW', relative_path='new.txt',
                  sha256=hashlib.sha256(material.read_bytes()).hexdigest())]}
        session = self.rehearse(packet=packet)
        self.assertEqual(session['materials'], packet['materials'])
        self.assertFalse((self.child / 'private.txt').exists())
        self.assertEqual(load_session(self.child), session)
        self.assert_parent_unchanged()

    def test_missing_material_is_not_copied_from_parent(self):
        (self.parent / 'parent-only.txt').write_text('仅在父目录', encoding='utf-8')
        packet = {**self.packet, 'materials': [dict(id='M1', relative_path='parent-only.txt',
                  sha256=hashlib.sha256('仅在父目录'.encode()).hexdigest())]}
        with self.assertRaises(OSError):
            self.rehearse(packet=packet)
        self.assertFalse((self.child / 'parent-only.txt').exists())
        self.assert_no_child()
        self.assert_parent_unchanged()

    def test_symlink_guards_are_retained(self):
        alias = self.root / 'alias'
        symlink(alias, self.parent, target_is_directory=True)
        for root, previous in ((alias, self.parent), (self.child, alias)):
            with self.subTest(root=root, previous=previous), self.assertRaises(ValueError):
                self.rehearse(root=root, previous=previous)
        symlink(self.child / 'linked.txt', self.parent / 'session.json')
        packet = {**self.packet, 'materials': [dict(id='M1', relative_path='linked.txt', sha256='0' * 64)]}
        with self.assertRaises(ValueError):
            self.rehearse(packet=packet)
        self.assert_no_child()
        self.assert_parent_unchanged()

    @unittest.skipIf(os.name == 'nt', 'POSIX mode bits; native Windows DACL rejection is tested separately')
    def test_broad_directory_permissions_are_rejected_without_chmod(self):
        self.child.chmod(0o755)
        with self.assertRaises(ValueError):
            self.rehearse()
        self.assertEqual(stat.S_IMODE(self.child.stat().st_mode), 0o755)
        self.assert_no_child()
        self.assert_parent_unchanged()

    def test_material_path_guards_are_retained(self):
        for path in ('../parent/session.json', str(self.parent / 'session.json')):
            packet = {**self.packet, 'materials': [dict(id='M1', relative_path=path, sha256='0' * 64)]}
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.rehearse(packet=packet)
        self.assert_no_child()
        self.assert_parent_unchanged()

    def test_malformed_child_link_rejected_even_with_recomputed_hash(self):
        original = self.rehearse()
        link = original['rehearsal_of']
        links = [None, [], 'parent', {**link, 'extra': True}]
        links.extend({key: value for key, value in link.items() if key != field} for field in link)
        variants = [('case_id', value) for value in ('other', '', None, 1, [])]
        variants += [('content_sha256', value) for value in ('A' * 64, 'a' * 63, 'g' * 64, None, 1)]
        variants += [('turn_count', value) for value in (True, False, 0, -1, 11.0, '11', None)]
        variants += [('focus', value) for value in ([], None, '重点', [''], [' '], [1], [[]], ['a', 'a'])]
        links.extend({**link, field: value} for field, value in variants)
        for malformed in links:
            with self.subTest(link=malformed):
                changed = {**original, 'rehearsal_of': malformed}
                self.save_rehashed(changed)
                before = (self.child / 'session.json').read_bytes()
                with self.assertRaises(ValueError):
                    load_session(self.child)
                with self.assertRaises(ValueError):
                    append_turn(self.child, self.turn())
                self.assertEqual((self.child / 'session.json').read_bytes(), before)

    def test_child_link_is_in_content_hash_and_legacy_may_not_have_link(self):
        original = self.rehearse()
        changed = copy.deepcopy(original)
        changed['rehearsal_of']['focus'] = ['修改后的重点']
        (self.child / 'session.json').write_text(json.dumps(changed), encoding='utf-8')
        with self.assertRaises(ValueError):
            load_session(self.child)
        legacy = {key: value for key, value in original.items()
                  if key not in ('schema_version', 'content_sha256')}
        (self.child / 'session.json').write_text(json.dumps(legacy), encoding='utf-8')
        with self.assertRaises(ValueError):
            load_session(self.child)

    def test_moved_child_reads_and_appends_without_parent_and_keeps_snapshot_link(self):
        original = self.rehearse()
        moved = self.root / 'moved-child'
        self.child.rename(moved)
        self.parent.rename(self.root / 'unavailable-parent')
        self.assertFalse(self.parent.exists())
        self.assertEqual(load_session(moved), original)
        updated = append_turn(moved, self.turn())
        self.assertEqual(updated['rehearsal_of'], original['rehearsal_of'])
        self.assertEqual(len(updated['turns']), 1)
        self.assertEqual(updated['content_sha256'], digest(updated))
        self.assertFalse(hearing_progress(moved)['structural_completed'])
        self.assertEqual(hearing_progress(moved)['issues'], [])
        # The snapshot is not a signature or a live authorization check.
        updated['rehearsal_of']['content_sha256'] = '0' * 64
        self.save_rehashed(updated, root=moved)
        self.assertEqual(load_session(moved)['rehearsal_of']['content_sha256'], '0' * 64)

    def test_new_directory_is_created_privately_and_original_init_contract_stays(self):
        fresh = self.root / 'fresh'
        self.rehearse(root=fresh)
        if os.name != 'nt':
            self.assertEqual(stat.S_IMODE(fresh.stat().st_mode), 0o700)
        ordinary = create_session(self.child, self.packet)
        self.assertNotIn('rehearsal_of', ordinary)
        other = self.root / 'invalid-init'
        with self.assertRaises(ValueError):
            create_session(other, {'packet': self.packet, 'focus': self.focus})
        self.assertFalse((other / 'session.json').exists())

    def test_cli_rehearse_read_append_and_progress_roundtrip(self):
        result = self.cli('rehearse', value={'packet': self.packet, 'focus': self.focus},
                          previous=self.parent)
        self.assertEqual(result.returncode, 0, result.stderr)
        session = json.loads(result.stdout)
        self.assertEqual(session['rehearsal_of']['content_sha256'], self.previous['content_sha256'])
        for operation, value in [('read', None), ('append', self.turn()), ('progress', None)]:
            result = self.cli(operation, value=value)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['case_id'], 'synthetic')
        self.assert_parent_unchanged()

    def test_cli_rejects_missing_previous_and_nonexact_input_without_session(self):
        for value in ({'packet': self.packet}, {'focus': self.focus}, [],
                      {'packet': self.packet, 'focus': self.focus, 'rehearsal_of': {}},
                      {'packet': self.packet, 'focus': []}):
            with self.subTest(value=value):
                result = self.cli('rehearse', value=value, previous=self.parent)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertNotIn('Traceback', result.stderr)
                self.assertIn('未完成', result.stderr)
                self.assert_no_child()
        result = self.cli('rehearse', value={'packet': self.packet, 'focus': self.focus})
        self.assertEqual(result.returncode, 2)
        self.assertIn('--previous-case-root', result.stderr)
        self.assert_parent_unchanged()


if __name__ == '__main__':
    unittest.main()
