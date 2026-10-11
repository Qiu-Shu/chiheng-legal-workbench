import copy
import hashlib
import importlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import legal_mcp
from legal_store import LegalStore
from mock_hearing import create_session, load_session, append_turn
from scripts import mock_hearing_session as cli


class HearingSourcesTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('hearing_sources'), '缺少本地法库适配入口')
        self.adapter = importlib.import_module('hearing_sources')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.before_db = legal_mcp.DB
        self.addCleanup(setattr, legal_mcp, 'DB', self.before_db)
        legal_mcp.DB = Path(self.tmp.name) / 'law.sqlite3'
        self.store = LegalStore(legal_mcp.DB)
        self.addCleanup(self.store.close)
        self.version = self.store.add(law_id='synthetic', title='虚构测试法规',
            text='第一条 临时测试正文。第二条 测试内容。', source_url='https://example.org/law',
            locator='全文', region='CN')
        self.root = Path(self.tmp.name).resolve() / 'hearing'
        create_session(self.root, dict(case_id='synthetic', procedure='civil_first_instance',
            our_role='plaintiff', materials=[], synthetic=True, human_review=None))
        self.turn = dict(case_id='synthetic', stage='issues', role='moderator',
            text='本轮命题：应核对适用条文。', material_ids=[], source_cards=[], unresolved=['原待核事项'])
        self.source = dict(claim='应核对适用条文', version_id=self.version, offset=2, length=8)

    def reject(self, turn=None, sources=None):
        before = (self.root / 'session.json').read_bytes()
        with self.assertRaises(ValueError):
            self.adapter.append_law_turn(self.root, self.turn if turn is None else turn,
                                         [self.source] if sources is None else sources)
        self.assertEqual((self.root / 'session.json').read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['.session.lock', 'session.json'])

    def test_real_fragment_complete_result_binding_digest_and_roundtrip(self):
        args = {k: self.source[k] for k in ('version_id', 'offset', 'length')}
        actual = legal_mcp.get_law_fragment(**args)
        original = copy.deepcopy(self.turn)
        with patch.object(legal_mcp, 'get_law_fragment', wraps=legal_mcp.get_law_fragment) as get:
            result = self.adapter.append_law_turn(self.root, self.turn, [self.source])
        get.assert_called_once_with(**args)
        card = result['turns'][0]['source_cards'][0]
        self.assertEqual(set(card), {'tool', 'arguments', 'result', 'claim', 'receipt_id'})
        self.assertEqual(card['result'], actual)
        self.assertEqual(card['arguments'], args)
        self.assertEqual(card['claim'], self.source['claim'])
        self.assertEqual(card['tool'], 'get_law_fragment')
        fields = {k: v for k, v in card.items() if k != 'receipt_id'}
        raw = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        self.assertEqual(card['receipt_id'], hashlib.sha256(raw.encode()).hexdigest())
        self.assertEqual(actual['citation']['review_state'], 'quarantine')
        self.assertIsNone(actual['citation']['effective_from'])
        self.assertFalse(actual['citation']['legal_applicability_verified'])
        self.assertEqual(result, load_session(self.root))
        self.assertEqual(result['turns'][0]['unresolved'], ['原待核事项', self.adapter.REVIEW_NOTICE])
        self.assertIsNone(result['turns'][0]['human_review'])
        self.assertEqual(self.turn, original)

    def test_all_requests_validated_before_retrieval(self):
        variants = [[], [self.source] * 11, {}, [None], (self.source,)]
        for extra in ({'claim': ''}, {'claim': '未出现'}, {'claim': 1}, {'version_id': ''},
                      {'version_id': False}, {'offset': True}, {'offset': -1}, {'offset': 1.0},
                      {'length': False}, {'length': 0}, {'length': 10001}, {'length': '8'},
                      {'result': {}}, {'receipt_id': 'forged'}):
            variants.append([self.source, {**self.source, **extra}])
        variants.append([{k: v for k, v in self.source.items() if k != 'length'}])
        with patch.object(legal_mcp, 'get_law_fragment') as get:
            for sources in variants:
                with self.subTest(sources=sources):
                    self.reject(sources=sources)
            get.assert_not_called()

    def test_handwritten_cards_and_invalid_turn_rejected_before_retrieval(self):
        with patch.object(legal_mcp, 'get_law_fragment') as get:
            for extra in ({'source_cards': [{}]}, {'source_cards': {}}, {'source_cards': ()}, {'text': 1},
                          {'unresolved': 'bad'}, {'extra': True}, {'human_review': 'signed'}):
                with self.subTest(extra=extra):
                    self.reject(turn={**self.turn, **extra})
            get.assert_not_called()

    def test_absent_empty_withdrawn_and_later_failure_preserve_bytes(self):
        for changes in ({'version_id': 'missing'}, {'offset': 9999}):
            self.reject(sources=[self.source, {**self.source, **changes}])
        self.store.revoke(self.version, reviewer='test', reason='synthetic withdrawal')
        self.reject()

    def test_malformed_returns_rejected_without_write(self):
        good = legal_mcp.get_law_fragment(self.version, offset=2, length=8)
        variants = [None, {}, {**good, 'found': 1}, {**good, 'text': ''},
                    {**good, 'citation': None}, {**good, 'version_id': 'other'},
                    {**good, 'offset': 3}, {**good, 'offset': True},
                    {**good, 'citation': {**good['citation'], 'version_id': 'other'}},
                    {**good, 'citation': {**good['citation'], 'character_range': {'start': 2, 'end': 3}}},
                    {**good, 'citation': {**good['citation'], 'character_range': {'start': True, 'end': 10}}}]
        for result in variants:
            with self.subTest(result=result), patch.object(legal_mcp, 'get_law_fragment', return_value=result):
                self.reject()
        with patch.object(legal_mcp, 'get_law_fragment', side_effect=ValueError('synthetic error')):
            self.reject()

    def test_legacy_and_completed_sessions_reject_before_retrieval(self):
        for stage, roles in [('issues', ['moderator', 'plaintiff', 'defendant']),
                             ('evidence', ['plaintiff', 'defendant']),
                             ('questions', ['moderator', 'plaintiff', 'defendant']),
                             ('debate', ['plaintiff', 'defendant']), ('review', ['reviewer'])]:
            for role in roles:
                append_turn(self.root, {**self.turn, 'stage': stage, 'role': role})
        with patch.object(legal_mcp, 'get_law_fragment') as get:
            self.reject()
            get.assert_not_called()
        session = load_session(self.root)
        session.pop('schema_version')
        session.pop('content_sha256')
        (self.root / 'session.json').write_text(json.dumps(session), encoding='utf-8')
        with patch.object(legal_mcp, 'get_law_fragment') as get:
            self.reject()
            get.assert_not_called()

    def test_cli_routes_synthetic_input_and_reports_failure(self):
        argv = ['mock_hearing_session.py', 'append-law', '--case-root', str(self.root), '--input', 'synthetic.json']
        payload = dict(turn=self.turn, sources=[self.source])
        with patch.object(sys, 'argv', argv), patch.object(Path, 'read_text', return_value=json.dumps(payload)), patch('sys.stdout', new_callable=io.StringIO) as out:
            cli.main()
        self.assertEqual(json.loads(out.getvalue()), load_session(self.root))
        for bad in ({**payload, 'result': {}}, {'turn': self.turn}, {**payload, 'sources': []}):
            before = (self.root / 'session.json').read_bytes()
            with patch.object(sys, 'argv', argv), patch.object(Path, 'read_text', return_value=json.dumps(bad)), patch('sys.stderr', new_callable=io.StringIO) as err:
                with self.assertRaises(SystemExit) as exit:
                    cli.main()
            self.assertEqual(exit.exception.code, 2)
            self.assertIn('未完成', err.getvalue())
            self.assertEqual((self.root / 'session.json').read_bytes(), before)

    def test_cli_sqlite_and_receipt_encoding_failures_preserve_bytes(self):
        argv = ['mock_hearing_session.py', 'append-law', '--case-root', str(self.root), '--input', 'synthetic.json']
        payload = json.dumps(dict(turn=self.turn, sources=[self.source]))
        actual = legal_mcp.get_law_fragment(self.version, offset=2, length=8)
        cases = [dict(side_effect=sqlite3.OperationalError('private database path')),
                 dict(return_value={**actual, 'unserializable': object()}),
                 dict(return_value={**actual, 'nonfinite': float('nan')})]
        for injected in cases:
            before = (self.root / 'session.json').read_bytes()
            with self.subTest(injected=injected), patch.object(sys, 'argv', argv), patch.object(Path, 'read_text', return_value=payload), patch.object(legal_mcp, 'get_law_fragment', **injected), patch('sys.stderr', new_callable=io.StringIO) as err:
                with self.assertRaises(SystemExit) as exit:
                    cli.main()
            self.assertEqual(exit.exception.code, 2)
            self.assertIn('未完成', err.getvalue())
            self.assertNotIn('Traceback', err.getvalue())
            self.assertNotIn('private database path', err.getvalue())
            self.assertEqual((self.root / 'session.json').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
