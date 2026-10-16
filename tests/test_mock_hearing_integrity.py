import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from tests.platform_fixtures import private_directory

from mock_hearing import append_turn, create_session, load_session


def digest(session):
    content = {key: value for key, value in session.items() if key != 'content_sha256'}
    raw = json.dumps(content, sort_keys=True, separators=(',', ':'),
                     ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


class MockHearingIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = private_directory(Path(self.tmp.name).resolve() / 'case')
        self.path = self.root / 'session.json'
        self.packet = dict(case_id='synthetic', procedure='civil_first_instance',
                           our_role='plaintiff', materials=[], synthetic=True,
                           human_review=None)
        self.turn = dict(case_id='synthetic', stage='issues', role='moderator',
                         text='演练陈述', material_ids=[], source_cards=[],
                         unresolved=['尚未核实'])

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, session):
        self.path.write_text(json.dumps(session, ensure_ascii=False), encoding='utf-8')

    def test_create_v2_and_digest_covers_full_session(self):
        session = create_session(self.root, self.packet)
        self.assertEqual(session.get('schema_version'), 2)
        self.assertIn('content_sha256', session)
        self.assertEqual(session['content_sha256'], digest(session))
        self.assertEqual(load_session(self.root), session)

    def test_each_append_updates_digest_and_pause_roundtrips(self):
        session = create_session(self.root, self.packet)
        previous = session.get('content_sha256')
        for role in ('moderator', 'plaintiff', 'defendant', 'moderator'):
            session = append_turn(self.root, {**self.turn, 'role': role})
            self.assertNotEqual(session.get('content_sha256'), previous)
            self.assertEqual(session.get('content_sha256'), digest(session))
            self.assertEqual(load_session(self.root), session)
            previous = session['content_sha256']

    def test_semantically_valid_changes_and_redundant_turn_deletion_are_rejected(self):
        create_session(self.root, self.packet)
        for _ in range(2):
            original = append_turn(self.root, {**self.turn, 'source_cards': [{'quote': '原文'}]})
        changes = []
        for field, value in (('text', '改写陈述'), ('source_cards', [{'quote': '改写原文'}])):
            changed = copy.deepcopy(original)
            changed['turns'][0][field] = value
            changes.append(changed)
        changed = copy.deepcopy(original)
        changed['turns'].pop()
        changes.append(changed)
        changes.extend({**original, **change} for change in (
            {'completed': True}, {'stage': 'evidence'}, {'synthetic': False},
            {'schema_version': True}, {'schema_version': 2.0}, {'schema_version': 3},
            {'content_sha256': '0' * 64}))
        for changed in changes:
            with self.subTest(changed=changed):
                self.save(changed)
                before = self.path.read_bytes()
                with self.assertRaises(ValueError):
                    load_session(self.root)
                with self.assertRaises(ValueError):
                    append_turn(self.root, self.turn)
                self.assertEqual(self.path.read_bytes(), before)

    def test_mixed_formats_are_rejected(self):
        original = create_session(self.root, self.packet)
        for field in ('schema_version', 'content_sha256'):
            changed = {key: value for key, value in original.items() if key != field}
            self.save(changed)
            with self.subTest(field=field), self.assertRaises(ValueError):
                load_session(self.root)

    def test_version_is_exact_integer_even_with_recomputed_digest(self):
        original = create_session(self.root, self.packet)
        for version in (True, 2.0, '2', 1, 3, None):
            changed = {**original, 'schema_version': version}
            changed['content_sha256'] = digest(changed)
            self.save(changed)
            with self.subTest(version=version), self.assertRaises(ValueError):
                load_session(self.root)

    def test_legacy_reads_original_cards_and_bytes_but_cannot_append(self):
        session = create_session(self.root, self.packet)
        session = append_turn(self.root, self.turn)
        legacy = {key: value for key, value in session.items()
                  if key not in ('schema_version', 'content_sha256')}
        legacy['turns'][0]['source_cards'] = [None, {}, 'historical']
        self.save(legacy)
        before = self.path.read_bytes()
        self.assertEqual(load_session(self.root), legacy)
        self.assertEqual(self.path.read_bytes(), before)
        with self.assertRaisesRegex(ValueError, '只读'):
            append_turn(self.root, self.turn)
        self.assertEqual(self.path.read_bytes(), before)

    def test_v2_rejects_each_invalid_card_on_append_and_read(self):
        original = create_session(self.root, self.packet)
        for card in (None, False, 1, 'text', [], {}):
            with self.subTest(card=card):
                self.save(original)
                before = self.path.read_bytes()
                with self.assertRaises(ValueError):
                    append_turn(self.root, {**self.turn, 'source_cards': [{'tool': 'example'}, card]})
                self.assertEqual(self.path.read_bytes(), before)
                stored = {**self.turn, 'source_cards': [card],
                          'synthetic': True, 'human_review': None}
                changed = {**original, 'turns': [stored]}
                changed['content_sha256'] = digest(changed)
                self.save(changed)
                with self.assertRaises(ValueError):
                    load_session(self.root)

    def test_nonempty_tool_objects_are_preserved_without_authentication(self):
        create_session(self.root, self.packet)
        cards = [{'tool': 'example', 'raw': {'unknown': None}}, {'arbitrary': [1, 2]}]
        session = append_turn(self.root, {**self.turn, 'source_cards': cards, 'unresolved': []})
        self.assertEqual(load_session(self.root), session)
        self.assertEqual(session['turns'][0]['source_cards'], cards)
        self.assertIsNone(session['turns'][0]['human_review'])
