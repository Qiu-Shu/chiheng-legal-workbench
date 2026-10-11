import json
import multiprocessing
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from review_records import append_record, validate_record


ROOT = Path(__file__).resolve().parents[1]


def sample_record(**changes):
    record = {
        'source_kind': 'statute',
        'source_url': 'https://example.org/public-law',
        'locator': '第三条；本次只核对该条文本',
        'content_sha256': 'a' * 64,
        'reviewer': '自动测试程序',
        'reviewer_kind': 'automated',
        'checked_at': '2026-09-27T10:00:00+08:00',
        'result': 'match',
        'scope': 'fragment',
    }
    return {**record, **changes}


def append_many(path, count):
    for _ in range(count):
        append_record(path, sample_record())


class ReviewRecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = Path(self.tmp.name) / 'data' / 'review-records.jsonl'

    def tearDown(self):
        self.tmp.cleanup()

    def test_fragment_never_becomes_entire_law_or_human_review(self):
        record = append_record(self.ledger, sample_record())
        self.assertEqual(record['scope'], 'fragment')
        self.assertEqual(record['reviewer_kind'], 'automated')
        self.assertNotIn('published', record)
        self.assertNotIn('applicability_verified', record)
        whole = validate_record(sample_record(scope='entire_law', locator='该版本完整正文'))
        self.assertEqual(whole['scope'], 'entire_law')

    def test_missing_or_blank_required_fields_are_rejected_before_writing(self):
        for field in sample_record():
            for value in (None, ''):
                with self.subTest(field=field, value=value):
                    record = sample_record()
                    if value is None:
                        del record[field]
                    else:
                        record[field] = value
                    with self.assertRaises(ValueError):
                        append_record(self.ledger, record)
                    self.assertFalse(self.ledger.exists())

    def test_bad_enums_and_mutually_exclusive_scopes_are_rejected(self):
        for changes in ({'source_kind': 'secret_case'}, {'scope': 'all_laws'},
                        {'result': 'approved'}, {'reviewer_kind': 'unspecified'},
                        {'scope': 'entire_case'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_record(sample_record(**changes))

    def test_non_reference_status_does_not_revoke_judgment(self):
        case = sample_record(source_kind='guiding_case', scope='entire_case',
                             case_reference_status='no_longer_referable',
                             judgment_validity='effective')
        stored = append_record(self.ledger, case)
        self.assertEqual(stored['case_reference_status'], 'no_longer_referable')
        self.assertEqual(stored['judgment_validity'], 'effective')

    def test_all_case_kinds_require_separate_statuses(self):
        for kind in ('guiding_case', 'reference_case', 'ordinary_judgment', 'typical_case'):
            case = sample_record(source_kind=kind, case_reference_status='unverified',
                                 judgment_validity='unverified')
            self.assertEqual(validate_record(case)['source_kind'], kind)
            for field in ('case_reference_status', 'judgment_validity'):
                missing = dict(case)
                del missing[field]
                with self.subTest(kind=kind, field=field), self.assertRaises(ValueError):
                    validate_record(missing)
            with self.assertRaises(ValueError):
                validate_record({**case, 'scope': 'entire_law'})

    def test_case_only_fields_are_forbidden_on_statutes(self):
        for field in ('case_reference_status', 'judgment_validity'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_record(sample_record(**{field: 'unverified'}))
        case = sample_record(source_kind='reference_case', case_reference_status='unverified',
                             judgment_validity='unverified')
        for field in ('case_reference_status', 'judgment_validity'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_record({**case, field: 'invalid_status'})

    def test_invalid_hash_timestamp_or_nonpublic_url_is_rejected(self):
        invalid = [
            {'content_sha256': 'not-a-hash'}, {'checked_at': '2026-09-27'},
            {'checked_at': '2026-09-27T10:00:00'}, {'source_url': 'file:///private/case'},
            {'source_url': 'https://user:password@example.org/law'},
            {'source_url': 'http://127.0.0.1/law'}, {'source_url': 'http://localhost/law'},
        ]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_record(sample_record(**changes))

    def test_full_text_and_caller_supplied_audit_metadata_are_not_accepted(self):
        for field in ('text', 'body', 'record_id', 'recorded_at', 'published'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_record(sample_record(**{field: 'not allowed'}))

    def test_append_preserves_prior_bytes_and_input(self):
        original = sample_record()
        before_input = dict(original)
        first = append_record(self.ledger, original)
        previous = self.ledger.read_bytes()
        second = append_record(self.ledger, sample_record(result='inconclusive'))
        self.assertTrue(self.ledger.read_bytes().startswith(previous))
        self.assertEqual(original, before_input)
        self.assertNotEqual(first['record_id'], second['record_id'])
        self.assertEqual(len(self.ledger.read_text().splitlines()), 2)
        self.assertIn('recorded_at', first)

    def test_partial_last_record_is_not_silently_extended(self):
        self.ledger.parent.mkdir()
        self.ledger.write_bytes(b'{"interrupted":')
        with self.assertRaises(ValueError):
            append_record(self.ledger, sample_record())
        self.assertEqual(self.ledger.read_bytes(), b'{"interrupted":')

    def test_concurrent_processes_append_complete_distinct_records(self):
        context = multiprocessing.get_context('spawn')
        workers = [context.Process(target=append_many, args=(str(self.ledger), 8))
                   for _ in range(3)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=15)
            self.assertEqual(worker.exitcode, 0)
        rows = [json.loads(line) for line in self.ledger.read_text().splitlines()]
        self.assertEqual(len(rows), 24)
        self.assertEqual(len({row['record_id'] for row in rows}), 24)

    def test_cli_explicit_input_is_required_and_invalid_input_does_not_write(self):
        command = [sys.executable, '-B', str(ROOT / 'scripts/review_record.py'),
                   '--input', '-', '--ledger', str(self.ledger)]
        bad = subprocess.run(command, input='{}', text=True, capture_output=True)
        self.assertNotEqual(bad.returncode, 0)
        self.assertFalse(self.ledger.exists())
        good = subprocess.run(command, input=json.dumps(sample_record()), text=True,
                              capture_output=True)
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertEqual(json.loads(good.stdout)['reviewer_kind'], 'automated')
        missing = subprocess.run(command[:3], text=True, capture_output=True)
        self.assertNotEqual(missing.returncode, 0)


if __name__ == '__main__':
    unittest.main()
