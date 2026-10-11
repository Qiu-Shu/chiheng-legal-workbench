import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import legal_mcp
from legal_store import LegalStore
from hearing_sources import append_law_turn
import mock_hearing
from mock_hearing import append_turn, create_session, load_session


ROOT = Path(__file__).resolve().parents[1]


class HearingTrackingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        material = self.root / 'material.txt'
        material.write_text('虚构材料。', encoding='utf-8')
        create_session(self.root, dict(case_id='synthetic', procedure='civil_first_instance',
            our_role='plaintiff', synthetic=True, human_review=None,
            materials=[dict(id='M1', relative_path=material.name,
                            sha256=hashlib.sha256(material.read_bytes()).hexdigest())]))
        self.path = self.root / 'session.json'
        self.turn = dict(case_id='synthetic', stage='issues', role='moderator',
            text='是否收到？已收到。暂无法回答。核对适用条文。补充材料。', material_ids=['M1'],
            source_cards=[], unresolved=['未核实'], tracking=self.tracking())

    def tracking(self, **changes):
        return dict(issue_id='I1', questions=[], responses=[], tasks=[], law_checks=[], **changes)

    def question(self, identifier='Q1'):
        return dict(question_id=identifier, text='是否收到？', addressed_to='plaintiff')

    def response(self, identifier='Q1', kind='answer'):
        return dict(question_id=identifier, kind=kind, text='已收到。')

    def task(self, **changes):
        return dict(dict(task_id='T1', text='补充材料。', kind='evidence', status='open',
                         material_ids=[], review_note=None), **changes)

    def law_check(self, **changes):
        return dict(dict(claim='核对适用条文', source_card_index=None, fact_date=None,
            research_as_of=None, temporal_note=None, transition_note=None,
            applicability_note=None, status='needs_review'), **changes)

    def value(self, role='moderator', issue='I1', **sections):
        value = copy.deepcopy(self.turn)
        value['role'] = role
        value['tracking'].update(issue_id=issue, **sections)
        return value

    def reject(self, value):
        before = self.path.read_bytes()
        names = set(self.root.iterdir())
        with self.assertRaises(ValueError):
            append_turn(self.root, value)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(set(self.root.iterdir()), names)

    def save_rehashed(self, session):
        session['content_sha256'] = mock_hearing._manifest_hash(
            {key: value for key, value in session.items() if key != 'content_sha256'})
        self.path.write_text(json.dumps(session, ensure_ascii=False), encoding='utf-8')

    def test_valid_tracking_roundtrip_without_sidecars_or_input_mutation(self):
        value = self.value(questions=[self.question()], tasks=[self.task()],
                           law_checks=[self.law_check()])
        original = copy.deepcopy(value)
        names = set(self.root.iterdir())
        try:
            session = append_turn(self.root, value)
        except ValueError as error:
            self.fail(f'有效 tracking 应能保存和读回：{error}')
        self.assertEqual(session, load_session(self.root))
        self.assertEqual(session['turns'][0]['tracking'], value['tracking'])
        self.assertEqual(value, original)
        self.assertEqual(set(self.root.iterdir()), names)

    def test_exact_fields_and_native_list_types(self):
        full = self.value(questions=[self.question()], responses=[self.response()],
                          tasks=[self.task()], law_checks=[self.law_check()])
        append_turn(self.root, self.value(questions=[self.question()]))
        full['role'] = 'plaintiff'
        full['tracking']['questions'][0]['question_id'] = 'Q2'
        for path in [(), ('questions', 0), ('responses', 0), ('tasks', 0), ('law_checks', 0)]:
            for operation in ('missing', 'extra', 'not_object'):
                value = copy.deepcopy(full)
                parent = value
                key = 'tracking'
                for part in path:
                    parent, key = parent[key], part
                target = parent[key]
                if operation == 'missing':
                    target.pop(next(iter(target)))
                elif operation == 'extra':
                    target['extra'] = None
                else:
                    parent[key] = []
                with self.subTest(path=path, operation=operation):
                    self.reject(value)
        for path in [(key,) for key in ('questions', 'responses', 'tasks', 'law_checks')] + [('tasks', 0, 'material_ids')]:
            for invalid in (None, {}, 'bad', True, ()):
                value = copy.deepcopy(full)
                parent = value['tracking']
                for key in path[:-1]:
                    parent = parent[key]
                parent[path[-1]] = invalid
                with self.subTest(path=path, invalid=invalid):
                    self.reject(value)
        for bad in ('', ' ', None, 1, [], {}):
            self.reject(self.value(issue=bad))

    def test_questions_require_literal_text_unique_global_ids_and_party(self):
        variants = [(field, bad) for field in ('question_id', 'text')
                    for bad in ('', ' ', None, 1, [], {})]
        variants += [('text', '未在发言中'), ('addressed_to', 'moderator'), ('addressed_to', []),
                     ('addressed_to', None)]
        for field, bad in variants:
            question = self.question()
            question[field] = bad
            with self.subTest(field=field, bad=bad):
                self.reject(self.value(questions=[question]))
        self.reject(self.value(questions=[self.question()] * 2))
        append_turn(self.root, self.value(questions=[self.question()]))
        self.reject(self.value(questions=[self.question()]))
        self.reject(self.value(issue='I2', questions=[self.question()]))

    def test_responses_reject_dangling_future_same_turn_cross_issue_and_wrong_role(self):
        self.reject(self.value('plaintiff', responses=[self.response()]))
        self.reject(self.value('plaintiff', questions=[self.question()], responses=[self.response()]))
        append_turn(self.root, self.value(questions=[self.question()]))
        self.reject(self.value('plaintiff', issue='I2', responses=[self.response()]))
        for role in ('defendant', 'moderator'):
            self.reject(self.value(role, responses=[self.response()]))
        self.reject(self.value('plaintiff', responses=[self.response()] * 2))
        variants = [(field, bad) for field in ('question_id', 'text')
                    for bad in ('', ' ', None, 1, [], {})]
        variants += [('kind', 'verified'), ('kind', []), ('text', '未在发言中')]
        for field, bad in variants:
            response = self.response()
            response[field] = bad
            with self.subTest(field=field, bad=bad):
                self.reject(self.value('plaintiff', responses=[response]))

    def test_progress_preserves_question_history_and_latest_response_kind(self):
        append_turn(self.root, self.value(questions=[self.question()]))
        append_turn(self.root, self.value('plaintiff', responses=[self.response()]))
        first = mock_hearing.hearing_progress(self.root)
        self.assertEqual(first['issues'][0]['unanswered_question_ids'], [])
        append_turn(self.root, self.value('plaintiff', responses=[self.response(kind='unable_to_answer')]))
        append_turn(self.root, self.value(issue='I2', questions=[self.question('Q2')]))
        append_turn(self.root, self.value(issue='I1'))
        before = self.path.read_bytes()
        progress = mock_hearing.hearing_progress(self.root)
        self.assertEqual(set(progress), {'case_id', 'structural_completed', 'tracking_recorded', 'issues', 'notice'})
        self.assertEqual(progress['case_id'], 'synthetic')
        self.assertFalse(progress['structural_completed'])
        self.assertTrue(progress['tracking_recorded'])
        self.assertEqual([issue['issue_id'] for issue in progress['issues']], ['I1', 'I2'])
        issue = progress['issues'][0]
        self.assertEqual(set(issue), {'issue_id', 'questions', 'unanswered_question_ids', 'tasks',
                                     'pending_review_task_ids', 'law_checks'})
        self.assertEqual(issue['questions'], [{**self.question(), 'question_turn_index': 0,
            'latest_response_kind': 'unable_to_answer', 'response_turn_indices': [1, 2]}])
        self.assertEqual(issue['unanswered_question_ids'], ['Q1'])
        self.assertEqual(progress['issues'][1]['questions'][0]['latest_response_kind'], None)
        self.assertEqual(progress['issues'][1]['questions'][0]['response_turn_indices'], [])
        self.assertEqual(progress['issues'][1]['unanswered_question_ids'], ['Q2'])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertIn('律师', progress['notice'])

    def test_task_updates_keep_identity_support_pending_review_and_reopening(self):
        append_turn(self.root, self.value(tasks=[self.task()]))
        for changes in ({'text': '新内容'}, {'kind': 'wording'}):
            self.reject(self.value(tasks=[self.task(**changes)]))
        self.reject(self.value(issue='I2', tasks=[self.task()]))
        addressed = self.task(status='addressed_pending_review', review_note='已补材料，待核验', material_ids=['M1'])
        append_turn(self.root, self.value(tasks=[addressed]))
        progress = mock_hearing.hearing_progress(self.root)['issues'][0]
        self.assertEqual(progress['tasks'], [{**addressed, 'turn_index': 1}])
        self.assertEqual(progress['pending_review_task_ids'], ['T1'])
        append_turn(self.root, self.value(tasks=[self.task()]))
        append_turn(self.root, self.value())
        progress = mock_hearing.hearing_progress(self.root)['issues'][0]
        self.assertEqual(progress['tasks'], [{**self.task(), 'turn_index': 2}])
        self.assertEqual(progress['pending_review_task_ids'], [])
        self.assertEqual(len(load_session(self.root)['turns']), 4)

    def test_task_invalid_fields_and_pending_review_requirements(self):
        variants = [(field, bad) for field in ('task_id', 'text')
                    for bad in ('', ' ', None, 1, [], {})]
        variants += [('kind', 'other'), ('kind', []), ('status', 'approved'), ('status', 'deleted'),
                     ('status', []), ('material_ids', ['unknown']), ('material_ids', ['M1', 'M1']),
                     ('material_ids', [None]), ('material_ids', [[]])]
        variants += [('review_note', bad) for bad in ('', ' ', 1, [], {})]
        for field, bad in variants:
            task = self.task(**{field: bad})
            with self.subTest(field=field, bad=bad):
                self.reject(self.value(tasks=[task]))
        self.reject(self.value(tasks=[self.task()] * 2))
        value = self.value(tasks=[self.task(material_ids=['M1'])])
        value['material_ids'] = []
        self.reject(value)
        for task in (self.task(status='addressed_pending_review'),
                     self.task(status='addressed_pending_review', review_note='待复核'),
                     self.task(kind='law', status='addressed_pending_review', review_note='待复核')):
            self.reject(self.value(tasks=[task]))
        append_turn(self.root, self.value(tasks=[self.task(kind='wording', status='addressed_pending_review', review_note='待复核')]))
        append_turn(self.root, self.value(tasks=[self.task(task_id='T2', kind='law', status='addressed_pending_review', review_note='待复核')], law_checks=[self.law_check()]))

    def test_law_checks_validate_strict_dates_indices_notes_and_unverified_status(self):
        variants = [('claim', bad) for bad in ('', ' ', None, 1, [], {}, '未出现')]
        variants += [('source_card_index', bad) for bad in (-1, True, False, 0.0, '0', 1, [], {})]
        variants += [(field, bad) for field in ('fact_date', 'research_as_of')
                     for bad in ('2026-2-03', '2026-02-30', '2025-02-29', '20261009',
                                 '2026-10-09T00:00:00', '0000-01-01', '', True, [], 123)]
        variants += [(field, bad) for field in ('temporal_note', 'transition_note', 'applicability_note')
                     for bad in ('', ' ', 1, [], {}, False)]
        variants += [('status', bad) for bad in ('verified', 'approved', 'applicable', None, [], {})]
        for field, bad in variants:
            value = self.value(law_checks=[self.law_check(**{field: bad})])
            value['source_cards'] = [{'caller_supplied': True}]
            with self.subTest(field=field, bad=bad):
                self.reject(value)
        self.reject(self.value(law_checks=[self.law_check(source_card_index=0)]))
        check = self.law_check(source_card_index=0, fact_date='2024-02-29', research_as_of='2026-10-09',
                               temporal_note='待核时效', transition_note='待查衔接', applicability_note='待核适用', status='blocked')
        value = self.value(law_checks=[check])
        value['source_cards'] = [{'caller_supplied': True}]
        append_turn(self.root, value)
        self.assertEqual(mock_hearing.hearing_progress(self.root)['issues'][0]['law_checks'],
                         [{**check, 'turn_index': 0}])

    def test_recomputed_hash_does_not_bypass_cross_turn_and_law_validation(self):
        append_turn(self.root, self.value(questions=[self.question()], tasks=[self.task()]))
        session = append_turn(self.root, self.value('plaintiff', responses=[self.response()],
                                                  tasks=[self.task()], law_checks=[self.law_check()]))
        variants = []
        for section, field, bad in [('responses', 'question_id', 'future'), ('tasks', 'kind', 'law'),
                                  ('law_checks', 'status', 'verified'), ('law_checks', 'research_as_of', '2026-02-30')]:
            changed = copy.deepcopy(session)
            changed['turns'][1]['tracking'][section][0][field] = bad
            variants.append(changed)
        changed = copy.deepcopy(session)
        changed['turns'][0]['tracking']['responses'] = [self.response('Q2')]
        changed['turns'][0]['role'] = 'plaintiff'
        changed['turns'][1]['tracking']['questions'] = [self.question('Q2')]
        variants.append(changed)
        for changed in variants:
            self.save_rehashed(changed)
            before = self.path.read_bytes()
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                load_session(self.root)
            with self.assertRaises(ValueError):
                mock_hearing.hearing_progress(self.root)
            self.reject(self.turn)
            self.assertEqual(self.path.read_bytes(), before)

    def test_empty_no_tracking_legacy_and_structural_completion(self):
        progress = mock_hearing.hearing_progress(self.root)
        self.assertFalse(progress['tracking_recorded'])
        self.assertEqual(progress['issues'], [])
        plain = {key: value for key, value in self.turn.items() if key != 'tracking'}
        for stage, roles in [('issues', ['moderator', 'plaintiff', 'defendant']),
                             ('evidence', ['plaintiff', 'defendant']),
                             ('questions', ['moderator', 'plaintiff', 'defendant']),
                             ('debate', ['plaintiff', 'defendant']), ('review', ['reviewer'])]:
            for role in roles:
                append_turn(self.root, {**plain, 'stage': stage, 'role': role})
        progress = mock_hearing.hearing_progress(self.root)
        self.assertTrue(progress['structural_completed'])
        self.assertFalse(progress['tracking_recorded'])
        self.assertEqual(progress['issues'], [])
        session = load_session(self.root)
        session.pop('schema_version')
        session.pop('content_sha256')
        self.path.write_text(json.dumps(session), encoding='utf-8')
        self.assertEqual(load_session(self.root), session)
        self.assertEqual(mock_hearing.hearing_progress(self.root), progress)
        self.reject(self.turn)
        session['turns'][0]['tracking'] = self.tracking()
        self.path.write_text(json.dumps(session), encoding='utf-8')
        with self.assertRaises(ValueError):
            load_session(self.root)

    def test_cli_progress_without_input_is_read_only_and_reports_validation_failure(self):
        append_turn(self.root, self.value(questions=[self.question()]))
        before = self.path.read_bytes()
        command = [sys.executable, str(ROOT / 'scripts/mock_hearing_session.py'), 'progress', '--case-root', str(self.root)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), mock_hearing.hearing_progress(self.root))
        self.assertEqual(self.path.read_bytes(), before)
        session = load_session(self.root)
        session['turns'][0]['tracking']['issue_id'] = ''
        self.save_rehashed(session)
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('未完成', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_structural_completion_keeps_unanswered_questions_tasks_and_law_checks(self):
        append_turn(self.root, self.value(questions=[self.question()], tasks=[self.task()],
                                          law_checks=[self.law_check()]))
        plain = {key: value for key, value in self.turn.items() if key != 'tracking'}
        for stage, roles in [('issues', ['plaintiff', 'defendant']),
                             ('evidence', ['plaintiff', 'defendant']),
                             ('questions', ['moderator', 'plaintiff', 'defendant']),
                             ('debate', ['plaintiff', 'defendant']), ('review', ['reviewer'])]:
            for role in roles:
                append_turn(self.root, {**plain, 'stage': stage, 'role': role})
        progress = mock_hearing.hearing_progress(self.root)
        self.assertTrue(progress['structural_completed'])
        self.assertTrue(progress['tracking_recorded'])
        issue = progress['issues'][0]
        self.assertEqual(issue['unanswered_question_ids'], ['Q1'])
        self.assertEqual(issue['tasks'], [{**self.task(), 'turn_index': 0}])
        self.assertEqual(issue['law_checks'], [{**self.law_check(), 'turn_index': 0}])
        self.assertIn('不代表风险消除', progress['notice'])
        self.reject(self.value('plaintiff', responses=[self.response()]))

    def test_atomic_failure_preserves_existing_session_and_cleans_temp(self):
        append_turn(self.root, self.value(questions=[self.question()]))
        before = self.path.read_bytes()
        names = set(self.root.iterdir())
        with patch('mock_hearing.os.replace', side_effect=OSError('synthetic failure')):
            with self.assertRaises(OSError):
                append_turn(self.root, self.value('plaintiff', responses=[self.response()]))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(set(self.root.iterdir()), names)
        self.assertEqual(mock_hearing.hearing_progress(self.root)['issues'][0]['unanswered_question_ids'], ['Q1'])

    def test_append_law_accepts_tracking_index_after_receipt_is_attached(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.addCleanup(setattr, legal_mcp, 'DB', legal_mcp.DB)
        legal_mcp.DB = Path(temporary.name) / 'law.sqlite3'
        store = LegalStore(legal_mcp.DB)
        self.addCleanup(store.close)
        version = store.add(law_id='synthetic', title='虚构法规', text='第一条 虚构测试。',
                            source_url='https://example.org/law', locator='全文', region='CN')
        value = self.value(law_checks=[self.law_check(source_card_index=0)],
            tasks=[self.task(kind='law', status='addressed_pending_review', review_note='待律师核验')])
        result = append_law_turn(self.root, value,
            [dict(claim='核对适用条文', version_id=version, offset=0, length=8)])
        self.assertEqual(load_session(self.root), result)
        self.assertEqual(result['turns'][0]['source_cards'][0]['tool'], 'get_law_fragment')
        self.assertEqual(result['turns'][0]['tracking'], value['tracking'])
        self.assertEqual(value['source_cards'], [])


if __name__ == '__main__':
    unittest.main()
