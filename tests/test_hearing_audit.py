import copy
from contextlib import closing
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from tests.platform_fixtures import private_directory
from unittest.mock import patch

import legal_mcp
from legal_store import LegalStore
from hearing_sources import append_law_turn
from mock_hearing import append_turn, create_session, load_session


ROOT = Path(__file__).resolve().parents[1]


class HearingAuditTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = private_directory(Path(temporary.name).resolve() / 'case')
        self.body = '虚构材料：甲已收款。乙提出异议。😀\n'
        self.material = self.root / 'material.txt'
        self.material.write_text(self.body, encoding='utf-8')
        artifact = self.root / 'artifact.txt'
        artifact.write_text('虚构辅助产物', encoding='utf-8')
        packet = dict(case_id='synthetic', procedure='civil_first_instance',
                      our_role='plaintiff', synthetic=True, human_review=None,
                      materials=[dict(id=identifier, relative_path=path.name,
                                      sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                                 for identifier, path in [('M1', self.material), ('A1', artifact)]])
        create_session(self.root, packet)
        self.path = self.root / 'session.json'
        self.turn = dict(case_id='synthetic', stage='issues', role='moderator',
                         text='演练陈述：甲已收款。仍须核对。', material_ids=['M1', 'A1'],
                         source_cards=[], unresolved=['未核实'], audit=self.audit())

    def audit(self):
        return dict(
            fact_register=[dict(fact_id='F1', speaker='甲', text='甲已收款', time=None,
                status='supported_by_record',
                source_refs=[dict(material_id='M1', start=5, end=9, quote='甲已收款')],
                contrary_refs=[dict(material_id='M1', start=10, end=15, quote='乙提出异议')],
                external_use_status='internal_only')],
            admission_queue=[dict(admission_id='R1', text='甲已收款', fact_ids=['F1'],
                purpose='澄清演练命题', risk='可能涉及自认', reviewer=None,
                decision=None, reviewed_at=None)],
            attack_links=[dict(attack_id='T1', fact_ids=['F1'], admission_review_ids=['R1'],
                               external_use_status='blocked')],
            artifact_ids=['A1'], corrections=[])

    def reject(self, turn):
        before = self.path.read_bytes()
        names = set(self.root.iterdir())
        with self.assertRaises(ValueError):
            append_turn(self.root, turn)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(set(self.root.iterdir()), names)

    def save_rehashed(self, session):
        content = {key: value for key, value in session.items() if key != 'content_sha256'}
        raw = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        session['content_sha256'] = hashlib.sha256(raw.encode()).hexdigest()
        self.path.write_text(json.dumps(session, ensure_ascii=False), encoding='utf-8')

    def test_valid_audit_roundtrip_without_sidecars_or_input_mutation(self):
        original = copy.deepcopy(self.turn)
        names = set(self.root.iterdir())
        try:
            session = append_turn(self.root, self.turn)
        except ValueError as error:
            self.fail(f'有效 audit 应能保存和读回：{error}')
        self.assertEqual(session, load_session(self.root))
        self.assertEqual(session['turns'][0]['audit'], self.audit())
        self.assertEqual(self.turn, original)
        self.assertEqual(set(self.root.iterdir()), names)

    def test_exact_object_fields_and_list_types(self):
        paths = [(), ('fact_register', 0), ('fact_register', 0, 'source_refs', 0),
                 ('admission_queue', 0), ('attack_links', 0)]
        for path in paths:
            for operation in ('missing', 'extra', 'not_object'):
                value = copy.deepcopy(self.turn)
                target = value['audit']
                for key in path:
                    target = target[key]
                if operation == 'missing':
                    target.pop(next(iter(target)))
                elif operation == 'extra':
                    target['unknown'] = None
                elif path:
                    parent = value['audit']
                    for key in path[:-1]:
                        parent = parent[key]
                    parent[path[-1]] = []
                else:
                    value['audit'] = None
                with self.subTest(path=path, operation=operation):
                    self.reject(value)
        for field in self.audit():
            for invalid in (None, {}, 'bad', True):
                value = copy.deepcopy(self.turn)
                value['audit'][field] = invalid
                with self.subTest(field=field, invalid=invalid):
                    self.reject(value)

    def test_python_tuples_are_not_accepted_as_audit_lists(self):
        paths = [(field,) for field in self.audit()]
        paths += [('fact_register', 0, field) for field in ('source_refs', 'contrary_refs')]
        paths += [('admission_queue', 0, 'fact_ids'), ('attack_links', 0, 'fact_ids'),
                  ('attack_links', 0, 'admission_review_ids')]
        for path in paths:
            value = copy.deepcopy(self.turn)
            parent = value['audit']
            for key in path[:-1]:
                parent = parent[key]
            parent[path[-1]] = tuple(parent[path[-1]])
            with self.subTest(path=path):
                self.reject(value)

    def test_fact_fields_ids_status_and_record_requirements(self):
        variants = [('fact_id', item) for item in ('', ' ', None, 1, [], {})]
        variants += [(field, item) for field in ('speaker', 'text') for item in ('', ' ', None, 1)]
        variants += [('time', item) for item in ('', ' ', False, [], 1)]
        variants += [('status', item) for item in ('proven', None, [], {})]
        variants += [('external_use_status', item) for item in ('approved', 'allowed', None, [])]
        variants += [(field, item) for field in ('source_refs', 'contrary_refs') for item in (None, {}, 'bad')]
        for field, item in variants:
            value = copy.deepcopy(self.turn)
            value['audit']['fact_register'][0][field] = item
            with self.subTest(field=field, item=item):
                self.reject(value)
        for status in ('supported_by_record', 'admitted_in_record', 'judicially_found'):
            value = copy.deepcopy(self.turn)
            value['audit']['fact_register'][0].update(status=status, source_refs=[])
            with self.subTest(status=status):
                self.reject(value)
        for field in ('fact_register', 'admission_queue', 'attack_links'):
            value = copy.deepcopy(self.turn)
            value['audit'][field] *= 2
            with self.subTest(duplicate=field):
                self.reject(value)

    def test_reference_offsets_quotes_and_membership(self):
        variants = [('material_id', item) for item in ('unknown', '', None, [])]
        variants += [('start', item) for item in (True, -1, 5.0, '5', None, 9, 10)]
        variants += [('end', item) for item in (False, -1, 5, 9.0, '9', None, len(self.body) + 1)]
        variants += [('quote', item) for item in ('', '甲已收', '甲已收款。', None, [])]
        for refs in ('source_refs', 'contrary_refs'):
            for field, item in variants:
                value = copy.deepcopy(self.turn)
                value['audit']['fact_register'][0][refs] = [dict(material_id='M1', start=5, end=9, quote='甲已收款')]
                value['audit']['fact_register'][0][refs][0][field] = item
                with self.subTest(refs=refs, field=field, item=item):
                    self.reject(value)
        self.reject({**self.turn, 'material_ids': ['A1']})

    def test_admission_queue_cannot_claim_approval_or_dangle(self):
        variants = [(field, item) for field in ('admission_id', 'text', 'purpose', 'risk')
                    for item in ('', ' ', None, [], 1)]
        variants += [('text', '未出现在发言中的文字')]
        variants += [('fact_ids', item) for item in ([], ['missing'], ['F1', 'F1'], [None], [[]], {})]
        variants += [(field, item) for field in ('reviewer', 'decision', 'reviewed_at')
                     for item in ('approved', False, 0, {}, [])]
        for field, item in variants:
            value = copy.deepcopy(self.turn)
            value['audit']['admission_queue'][0][field] = item
            with self.subTest(field=field, item=item):
                self.reject(value)

    def test_attack_and_artifact_links_are_closed_and_unique(self):
        variants = [('attack_id', item) for item in ('', ' ', None, [])]
        variants += [(field, item) for field in ('fact_ids', 'admission_review_ids')
                     for item in (['missing'], [None], [[]], {})]
        variants += [('fact_ids', ['F1', 'F1']), ('admission_review_ids', ['R1', 'R1'])]
        variants += [('external_use_status', item) for item in ('internal_only', 'approved', None, [])]
        for field, item in variants:
            value = copy.deepcopy(self.turn)
            value['audit']['attack_links'][0][field] = item
            with self.subTest(field=field, item=item):
                self.reject(value)
        for artifacts in (['missing'], ['A1', 'A1'], [None], [[]]):
            value = copy.deepcopy(self.turn)
            value['audit']['artifact_ids'] = artifacts
            with self.subTest(artifacts=artifacts):
                self.reject(value)
        self.reject({**self.turn, 'material_ids': ['M1']})

    def test_supported_statuses_unicode_positions_and_empty_optional_lists(self):
        for status in ('alleged', 'supported_by_record', 'admitted_in_record', 'judicially_found',
                       'hypothetical', 'disputed', 'unclear'):
            value = copy.deepcopy(self.turn)
            fact = value['audit']['fact_register'][0]
            fact.update(status=status, time='待核实时间', external_use_status='blocked')
            fact['source_refs'] = [dict(material_id='M1', start=16, end=17, quote='😀')]
            append_turn(self.root, value)
        empty = {key: [] for key in self.audit()}
        append_turn(self.root, {**self.turn, 'audit': empty})
        value = copy.deepcopy(self.turn)
        value['audit']['attack_links'][0].update(fact_ids=[], admission_review_ids=[],
                                                external_use_status='internal_only')
        value['audit']['admission_queue'] = []
        value['audit']['fact_register'][0].update(status='alleged', source_refs=[], contrary_refs=[])
        append_turn(self.root, value)
        self.assertEqual(len(load_session(self.root)['turns']), 9)

    def test_corrections_only_reference_earlier_audit_turns_without_rewriting(self):
        plain = {key: value for key, value in self.turn.items() if key != 'audit'}
        append_turn(self.root, plain)
        first = append_turn(self.root, self.turn)['turns'][1]
        invalid = [None, {}, {'turn_index': 1}, {'turn_index': 1, 'reason': '更正', 'extra': None}]
        invalid += [dict(turn_index=target, reason='更正') for target in (True, -1, 0, 2, 3, 1.0, '1', [])]
        invalid += [dict(turn_index=1, reason=reason) for reason in ('', ' ', None, [])]
        for correction in invalid:
            value = copy.deepcopy(self.turn)
            value['audit']['corrections'] = [correction]
            with self.subTest(correction=correction):
                self.reject(value)
        value = copy.deepcopy(self.turn)
        value['audit']['corrections'] = [dict(turn_index=1, reason='补充说明')]*2
        self.reject(value)
        value['audit']['corrections'] = [dict(turn_index=1, reason='补充说明')]
        session = append_turn(self.root, value)
        self.assertEqual(session['turns'][1], first)
        self.assertEqual(load_session(self.root), session)

    def test_load_revalidates_audit_after_content_hash_recomputed(self):
        session = append_turn(self.root, self.turn)
        variants = []
        for section, field, bad in [('fact_register', 'source_refs', [dict(material_id='M1', start=5, end=9, quote='伪造')]),
                                    ('admission_queue', 'reviewer', '伪签名'),
                                    ('attack_links', 'external_use_status', 'internal_only')]:
            changed = copy.deepcopy(session)
            changed['turns'][0]['audit'][section][0][field] = bad
            variants.append(changed)
        changed = copy.deepcopy(session)
        changed['turns'][0]['audit']['corrections'] = [dict(turn_index=0, reason='自指')]
        variants.append(changed)
        for changed in variants:
            self.save_rehashed(changed)
            before = self.path.read_bytes()
            with self.subTest(audit=changed['turns'][0]['audit']), self.assertRaises(ValueError):
                load_session(self.root)
            self.assertEqual(self.path.read_bytes(), before)
            self.reject(self.turn)

    def test_material_and_artifact_integrity_rechecked_on_load_and_append(self):
        append_turn(self.root, self.turn)
        for name in ('material.txt', 'artifact.txt'):
            path = self.root / name
            original = path.read_bytes()
            path.write_text('改写', encoding='utf-8')
            with self.subTest(name=name), self.assertRaises(ValueError):
                load_session(self.root)
            self.reject(self.turn)
            path.write_bytes(original)

    def test_plain_v2_and_read_only_legacy_remain_compatible(self):
        plain = {key: value for key, value in self.turn.items() if key != 'audit'}
        session = append_turn(self.root, plain)
        self.assertEqual(load_session(self.root), session)
        legacy = {key: value for key, value in session.items() if key not in ('schema_version', 'content_sha256')}
        self.path.write_text(json.dumps(legacy), encoding='utf-8')
        before = self.path.read_bytes()
        self.assertEqual(load_session(self.root), legacy)
        self.reject(self.turn)
        self.assertEqual(self.path.read_bytes(), before)
        legacy['turns'][0]['audit'] = self.audit()
        self.path.write_text(json.dumps(legacy), encoding='utf-8')
        with self.assertRaises(ValueError):
            load_session(self.root)

    def test_atomic_failure_does_not_save_audit_or_leave_temporary_files(self):
        before = self.path.read_bytes()
        names = set(self.root.iterdir())
        for operation in ('os.replace', 'os.fsync'):
            with self.subTest(operation=operation), patch('mock_hearing.' + operation, side_effect=OSError('injected')):
                with self.assertRaises(OSError):
                    append_turn(self.root, self.turn)
            self.assertEqual(self.path.read_bytes(), before)
            self.assertEqual(set(self.root.iterdir()), names)

    def test_append_law_preserves_audit_and_actual_local_fragment(self):
        with tempfile.TemporaryDirectory() as directory, closing(LegalStore(Path(directory) / 'synthetic.sqlite3')) as store:
            database = Path(directory) / 'synthetic.sqlite3'
            version = store.add(law_id='synthetic', title='虚构测试法规', text='第一条 测试正文。',
                                source_url='https://example.org/law', locator='全文', region='CN')
            sources = [dict(claim='仍须核对', version_id=version, offset=0, length=5)]
            with patch.object(legal_mcp, 'DB', database):
                actual = legal_mcp.get_law_fragment(version, offset=0, length=5)
                session = append_law_turn(self.root, self.turn, sources)
            self.assertEqual(session['turns'][0]['audit'], self.audit())
            self.assertEqual(session['turns'][0]['source_cards'][0]['result'], actual)
            self.assertEqual(load_session(self.root), session)

    def test_cli_append_read_and_invalid_audit(self):
        command = [sys.executable, '-B', str(ROOT / 'scripts/mock_hearing_session.py')]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'turn.json'
            path.write_text(json.dumps(self.turn), encoding='utf-8')
            appended = subprocess.run([*command, 'append', '--case-root', str(self.root), '--input', str(path)],
                                      capture_output=True, text=True)
            self.assertEqual(appended.returncode, 0, appended.stderr)
            read = subprocess.run([*command, 'read', '--case-root', str(self.root)], capture_output=True, text=True)
            self.assertEqual(read.returncode, 0, read.stderr)
            self.assertEqual(json.loads(read.stdout), json.loads(appended.stdout))
            invalid = copy.deepcopy(self.turn)
            invalid['audit']['admission_queue'][0]['decision'] = 'approved'
            path.write_text(json.dumps(invalid), encoding='utf-8')
            before = self.path.read_bytes()
            rejected = subprocess.run([*command, 'append', '--case-root', str(self.root), '--input', str(path)],
                                      capture_output=True, text=True)
            self.assertEqual(rejected.returncode, 2)
            self.assertNotIn('Traceback', rejected.stderr)
            self.assertEqual(self.path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
