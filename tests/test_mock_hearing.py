import copy
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from tests.platform_fixtures import private_directory, symlink
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
from mock_hearing import append_turn, create_session, load_session


def turn(stage='issues', role='moderator', **changes):
    return dict(case_id='synthetic-case', stage=stage, role=role,
                text='仅供模拟演练的陈述。', material_ids=['M1'],
                source_cards=[], unresolved=['本回合未检索法律依据，仍待核实。'],
                **changes)


def append_many(root, count):
    for _ in range(count):
        append_turn(root, turn())


class MockHearingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = private_directory(Path(self.tmp.name).resolve() / 'case')
        self.material = self.root / 'material.txt'
        self.material.write_text('虚构材料：甲向乙主张借款。', encoding='utf-8')
        self.packet = dict(case_id='synthetic-case', procedure='civil_first_instance',
                           our_role='plaintiff', synthetic=True, human_review=None,
                           materials=[dict(id='M1', relative_path='material.txt',
                                           sha256=hashlib.sha256(self.material.read_bytes()).hexdigest())])

    def tearDown(self):
        self.tmp.cleanup()

    def assert_unchanged_rejection(self, value):
        before = (self.root / 'session.json').read_bytes()
        with self.assertRaises((ValueError, OSError)):
            append_turn(self.root, value)
        self.assertEqual((self.root / 'session.json').read_bytes(), before)

    def test_create_roundtrip_and_private_permissions(self):
        original = copy.deepcopy(self.packet)
        session = create_session(self.root, self.packet)
        self.assertEqual(load_session(self.root), session)
        self.assertEqual(session['turns'], [])
        self.assertEqual(session['stage'], 'issues')
        self.assertFalse(session['completed'])
        self.assertEqual(self.packet, original)
        if os.name != 'nt':
            for name in ('session.json', '.session.lock'):
                self.assertEqual(stat.S_IMODE((self.root / name).stat().st_mode), 0o600)

    def test_wrong_procedure_role_and_human_signature_are_rejected(self):
        for changes in ({'procedure': 'criminal'}, {'our_role': 'judge'},
                        {'synthetic': 'yes'}, {'human_review': '律师签名'},
                        {'reviewer_signature': '律师'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                create_session(self.root, {**self.packet, **changes})
            self.assertFalse((self.root / 'session.json').exists())

    def test_duplicate_init_preserves_bytes(self):
        create_session(self.root, self.packet)
        before = (self.root / 'session.json').read_bytes()
        with self.assertRaises((ValueError, FileExistsError)):
            create_session(self.root, self.packet)
        self.assertEqual((self.root / 'session.json').read_bytes(), before)

    def test_invalid_material_paths_and_duplicate_ids_are_rejected(self):
        for path in ('../material.txt', '/etc/passwd', 'a/../material.txt',
                     './material.txt', 'a//b', 'session.json', '.session.lock'):
            packet = copy.deepcopy(self.packet)
            packet['materials'][0]['relative_path'] = path
            with self.subTest(path=path), self.assertRaises((ValueError, OSError)):
                create_session(self.root, packet)
        packet = copy.deepcopy(self.packet)
        packet['materials'] *= 2
        with self.assertRaises(ValueError):
            create_session(self.root, packet)

    def test_material_symlink_and_nested_symlink_are_rejected(self):
        symlink(self.root / 'link.txt', self.material)
        symlink(self.root / 'linked', self.root, target_is_directory=True)
        for path in ('link.txt', 'linked/material.txt'):
            packet = copy.deepcopy(self.packet)
            packet['materials'][0]['relative_path'] = path
            with self.subTest(path=path), self.assertRaises(ValueError):
                create_session(self.root, packet)

    def test_root_session_and_lock_symlinks_are_rejected(self):
        alias = self.root / 'alias'
        symlink(alias, self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            create_session(alias, self.packet)
        for name in ('session.json', '.session.lock'):
            path = self.root / name
            if path.exists():
                path.unlink()
            symlink(path, self.material)
            with self.subTest(name=name), self.assertRaises((ValueError, OSError)):
                create_session(self.root, self.packet)
            self.assertEqual(self.material.read_text(), '虚构材料：甲向乙主张借款。')
            path.unlink()

    def test_nested_material_works_without_scanning_unlisted_files(self):
        (self.root / 'docs').mkdir()
        self.material.rename(self.root / 'docs' / 'material.txt')
        self.packet['materials'][0]['relative_path'] = 'docs/material.txt'
        (self.root / 'unlisted.bin').write_bytes(b'\xff')
        create_session(self.root, self.packet)
        self.assertEqual(len(load_session(self.root)['materials']), 1)

    def test_material_hardlink_is_rejected_on_init(self):
        before = self.material.read_bytes()
        os.link(self.material, self.root / 'material-copy.txt')
        with self.assertRaises(ValueError):
            create_session(self.root, self.packet)
        self.assertFalse((self.root / 'session.json').exists())
        self.assertEqual(self.material.read_bytes(), before)

    def test_material_session_and_lock_hardlinks_block_read_and_append(self):
        create_session(self.root, self.packet)
        for name in ('material.txt', 'session.json', '.session.lock'):
            with self.subTest(name=name):
                original = self.root / name
                before = original.read_bytes()
                alias = self.root / (name + '.hardlink')
                os.link(original, alias)
                try:
                    with self.assertRaises(ValueError):
                        load_session(self.root)
                    self.assert_unchanged_rejection(turn())
                    self.assertEqual(original.read_bytes(), before)
                    self.assertEqual(alias.read_bytes(), before)
                finally:
                    alias.unlink()

    def test_wrong_hash_invalid_utf8_and_size_limit_are_rejected(self):
        for raw in (b'\xff', b'x' * (2 * 1024 * 1024 + 1)):
            self.material.write_bytes(raw)
            self.packet['materials'][0]['sha256'] = hashlib.sha256(raw).hexdigest()
            with self.assertRaises(ValueError):
                create_session(self.root, self.packet)
        self.material.write_text('changed', encoding='utf-8')
        with self.assertRaises(ValueError):
            create_session(self.root, self.packet)
        self.packet['materials'] *= 101
        with self.assertRaises(ValueError):
            create_session(self.root, self.packet)

    def test_material_hash_change_blocks_read_and_append(self):
        create_session(self.root, self.packet)
        self.material.write_text('changed', encoding='utf-8')
        with self.assertRaises(ValueError):
            load_session(self.root)
        self.assert_unchanged_rejection(turn())

    def test_manifest_or_saved_turn_tamper_is_rejected(self):
        create_session(self.root, self.packet)
        path = self.root / 'session.json'
        original = path.read_text()
        for change in ({'case_id': 'other'}, {'procedure': 'criminal'},
                       {'completed': True}, {'turns': [{**turn(), 'role': 'stranger'}]}):
            path.write_text(json.dumps({**json.loads(original), **change}), encoding='utf-8')
            with self.subTest(change=change), self.assertRaises(ValueError):
                load_session(self.root)

    def test_cross_case_unknown_role_material_and_human_review_rejected(self):
        create_session(self.root, self.packet)
        for change in ({'case_id': 'other'}, {'role': 'judge'}, {'material_ids': ['missing']},
                       {'human_review': '人工已审核'}, {'synthetic': False},
                       {'reviewer_signature': '律师'}, {'source_cards': {}}, {'unresolved': []}):
            self.assert_unchanged_rejection({**turn(), **change})

    def test_stage_jumps_and_missing_roles_are_rejected(self):
        create_session(self.root, self.packet)
        self.assert_unchanged_rejection(turn('questions'))
        append_turn(self.root, turn())
        self.assert_unchanged_rejection(turn('evidence', 'plaintiff'))
        append_turn(self.root, turn(role='plaintiff'))
        self.assert_unchanged_rejection(turn('evidence', 'plaintiff'))
        append_turn(self.root, turn(role='defendant'))
        append_turn(self.root, turn('evidence', 'plaintiff'))
        self.assert_unchanged_rejection(turn('questions'))
        self.assert_unchanged_rejection(turn())
        self.assert_unchanged_rejection(turn('evidence', 'moderator'))

    def test_complete_all_stages_preserves_source_cards_and_stops(self):
        create_session(self.root, self.packet)
        card = {'tool': 'law_search', 'result': {'url': 'https://example.org', 'quote': '工具原文'}}
        stages = [('issues', ['moderator', 'plaintiff', 'defendant']),
                  ('evidence', ['plaintiff', 'defendant']),
                  ('questions', ['moderator', 'plaintiff', 'defendant']),
                  ('debate', ['plaintiff', 'defendant']), ('review', ['reviewer'])]
        for stage, roles in stages:
            for role in roles:
                result = append_turn(self.root, {**turn(stage, role), 'source_cards': [card], 'unresolved': []})
        self.assertTrue(result['completed'])
        self.assertEqual(result, load_session(self.root))
        self.assertEqual(len(result['turns']), 11)
        for row in result['turns']:
            self.assertEqual(row['source_cards'], [card])
            self.assertTrue(row['synthetic'])
            self.assertIsNone(row['human_review'])
        self.assert_unchanged_rejection(turn('review', 'reviewer'))

    def test_unfilled_questions_and_debate_cannot_advance_and_review_role_is_exclusive(self):
        create_session(self.root, self.packet)
        for stage, roles in [('issues', ['moderator', 'plaintiff', 'defendant']),
                             ('evidence', ['plaintiff', 'defendant'])]:
            for role in roles:
                append_turn(self.root, turn(stage, role))
        append_turn(self.root, turn('questions', 'plaintiff'))
        append_turn(self.root, turn('questions', 'defendant'))
        self.assert_unchanged_rejection(turn('debate', 'plaintiff'))
        append_turn(self.root, turn('questions', 'moderator'))
        append_turn(self.root, turn('debate', 'plaintiff'))
        self.assert_unchanged_rejection(turn('review', 'reviewer'))
        append_turn(self.root, turn('debate', 'defendant'))
        self.assert_unchanged_rejection(turn('review', 'plaintiff'))

    def test_concurrent_append_keeps_every_turn(self):
        create_session(self.root, self.packet)
        context = multiprocessing.get_context('spawn')
        workers = [context.Process(target=append_many, args=(str(self.root), 5)) for _ in range(3)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=15)
            self.assertEqual(worker.exitcode, 0)
        self.assertEqual(len(load_session(self.root)['turns']), 15)

    def test_atomic_replace_failure_leaves_old_session_and_no_temporary_file(self):
        create_session(self.root, self.packet)
        before = (self.root / 'session.json').read_bytes()
        names = set(self.root.iterdir())
        with patch('mock_hearing.os.replace', side_effect=OSError('injected disk failure')):
            with self.assertRaises(OSError):
                append_turn(self.root, turn())
        self.assertEqual((self.root / 'session.json').read_bytes(), before)
        self.assertEqual(set(self.root.iterdir()), names)

    def test_invalid_session_encoding_is_rejected(self):
        session = create_session(self.root, self.packet)
        (self.root / 'session.json').write_bytes(json.dumps(session).encode('utf-16'))
        with self.assertRaises(ValueError):
            load_session(self.root)

    def test_fsync_failure_keeps_old_session_and_cleans_temporary_file(self):
        create_session(self.root, self.packet)
        before = (self.root / 'session.json').read_bytes()
        names = set(self.root.iterdir())
        with patch('mock_hearing.os.fsync', side_effect=OSError('injected sync failure')):
            with self.assertRaises(OSError):
                append_turn(self.root, turn())
        self.assertEqual((self.root / 'session.json').read_bytes(), before)
        self.assertEqual(set(self.root.iterdir()), names)

    def test_init_write_failure_does_not_leave_session_or_temporary_file(self):
        operation = 'rename' if os.name == 'nt' else 'link'
        with patch('mock_hearing.os.' + operation, side_effect=OSError('injected disk failure')):
            with self.assertRaises(OSError):
                create_session(self.root, self.packet)
        self.assertFalse((self.root / 'session.json').exists())
        self.assertFalse(list(self.root.glob('.session-*.tmp')))

    def test_new_empty_case_directory_and_nonsynthetic_markers(self):
        root = self.root / 'new-case'
        create_session(root, {**self.packet, 'materials': [], 'synthetic': False})
        result = append_turn(root, {**turn(), 'material_ids': []})
        if os.name != 'nt':
            self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
        self.assertFalse(result['turns'][0]['synthetic'])
        self.assertIsNone(result['turns'][0]['human_review'])

    @unittest.skipIf(os.name == 'nt', 'POSIX mode bits; native Windows DACL rejection is tested separately')
    def test_broad_existing_directory_is_rejected_without_chmod(self):
        self.root.chmod(0o755)
        with self.assertRaises(ValueError):
            create_session(self.root, self.packet)
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o755)

    def test_cli_init_read_append_and_failure(self):
        command = [sys.executable, '-B', str(ROOT / 'scripts/mock_hearing_session.py')]
        packet_path = self.root / 'packet.json'
        packet_path.write_text(json.dumps(self.packet), encoding='utf-8')
        turn_path = self.root / 'turn.json'
        turn_path.write_text(json.dumps(turn()), encoding='utf-8')
        for operation, path in [('init', packet_path), ('read', None), ('append', turn_path)]:
            args = [*command, operation, '--case-root', str(self.root)]
            if path:
                args.extend(['--input', str(path)])
            result = subprocess.run(args, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['case_id'], 'synthetic-case')
        bad = subprocess.run([*command, 'init', '--case-root', str(self.root), '--input', str(packet_path)],
                             text=True, capture_output=True)
        self.assertNotEqual(bad.returncode, 0)
        self.assertNotIn('Traceback', bad.stderr)
        missing = subprocess.run([*command, 'read'], text=True, capture_output=True)
        self.assertNotEqual(missing.returncode, 0)
        help_result = subprocess.run([*command, '--help'], text=True, capture_output=True)
        self.assertIn('同一', help_result.stdout)
        self.assertIn('issues', help_result.stdout)


if __name__ == '__main__':
    unittest.main()
