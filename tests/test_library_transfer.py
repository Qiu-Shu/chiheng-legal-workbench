import portable_lock as fcntl
import hashlib
import importlib
import json
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from legal_store import LegalStore


class LibraryTransferTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('library_transfer'),
                             'library transfer API must exist')
        self.api = importlib.import_module('library_transfer')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'source'
        (self.root / 'config').mkdir(parents=True)
        (self.root / 'verification').mkdir()
        self.store = LegalStore(self.root / 'data/legal.sqlite3')
        self.addCleanup(self.store.close)
        self.version = self.store.add(law_id='test', title='公开测试法', text='第一条 公开法律正文。',
            source_url='https://example.org/law', locator='第一条', region='CN',
            provenance={'original_path': '/old/mac/original.docx'})
        self.store.approve(self.version, reviewer='human', effective_from='2020-01-01')
        self.store.revoke(self.version, reviewer='human', reason='需重新核验')
        self.corpus = self.base / 'external/provision-index.json'
        self.corpus.parent.mkdir()
        self.corpus.write_text(json.dumps({'laws': {'one': {'title': '测试法',
            'urls': ['https://example.org/law'], 'provisions': [{'text': '第一条', 'article': '第一条'}]}}}))
        self.corpus.with_name('LICENSE').write_text('Observed upstream license text')
        self.config = {'corpus_path': str(self.corpus), 'corpus_origin': 'existing_bundle',
                       'upstream': 'https://example.org/public', 'redistribution': 'not_enabled',
                       'offline_review_state': 'unverified_mirror'}
        (self.root / 'config/shared-library.json').write_text(json.dumps(self.config))
        (self.root / 'verification/scheduler-state.json').write_text('{"last_run":"old"}')
        (self.root / 'data/review-records.jsonl').write_text('{"record_id":"one"}\n')
        for folder in ('quarantine', 'upstream-catalog', 'jilin-samples', 'discovery',
                       'attachment-preflight', 'official-basic-laws', 'official-samples',
                       'disclosure-preflight'):
            path = self.root / 'data' / folder
            path.mkdir()
            (path / 'original.bin').write_bytes(b'public original')
        (self.root / 'config/machine-secret.json').write_text('secret')
        (self.root / 'verification/debug.log').write_text('private log')
        self.archive = self.base / 'library.zip'

    def export(self):
        return self.api.export_library(self.root, self.archive)

    def test_traffic_manifest_and_originals_survive_transfer(self):
        config = self.root / 'config/jilin-traffic.json'
        config.write_text('{"collection_id":"jilin-traffic-2026-2"}')
        folder = self.root / 'data/jilin-samples/traffic'
        folder.mkdir()
        (folder / 'original.xlsx').write_bytes(b'public traffic original')
        manifest = self.export()
        self.assertIn('config/jilin-traffic.json', manifest['files'])
        target = self.base / 'restored-traffic'
        self.api.restore_library(self.archive, target)
        self.assertEqual((target / 'config/jilin-traffic.json').read_bytes(), config.read_bytes())
        self.assertEqual((target / 'data/jilin-samples/traffic/original.xlsx').read_bytes(), b'public traffic original')

    def rewrite(self, transform):
        with zipfile.ZipFile(self.archive) as source:
            rows = [(entry, source.read(entry)) for entry in source.infolist()]
        with zipfile.ZipFile(self.archive, 'w') as target:
            for entry, body in transform(rows):
                target.writestr(entry, body)

    def test_roundtrip_preserves_public_evidence_review_withdrawal_and_checkpoint(self):
        manifest = self.export()
        self.assertEqual(manifest['format_version'], 1)
        self.assertEqual(manifest['corpus']['law_versions'], 1)
        self.assertEqual(manifest['corpus']['review_state'], 'unverified_mirror')
        self.assertEqual(manifest['ledger_counts']['data/review-records.jsonl'], 1)
        self.assertEqual(self.api.verify_archive(self.archive), manifest)
        target = self.base / 'restored'
        self.api.restore_library(self.archive, target)
        config = json.loads((target / 'config/shared-library.json').read_text())
        self.assertEqual(config['corpus_path'], '../data/public-corpus/provision-index.json')
        self.assertEqual(config['corpus_origin'], self.config['corpus_origin'])
        restored = LegalStore(target / 'data/legal.sqlite3', readonly=True)
        try:
            self.assertEqual(restored.detail(self.version), self.store.detail(self.version))
            self.assertEqual(restored.search('公开'), [])
        finally:
            restored.close()
        for original in (self.root / 'data').rglob('original.bin'):
            self.assertEqual((target / original.relative_to(self.root)).read_bytes(), original.read_bytes())
        self.assertEqual((target / 'verification/scheduler-state.json').read_bytes(),
                         (self.root / 'verification/scheduler-state.json').read_bytes())
        self.assertEqual((target / 'data/public-corpus/provision-index.json').read_bytes(), self.corpus.read_bytes())
        self.assertFalse((target / 'config/machine-secret.json').exists())
        self.assertFalse((target / 'verification/debug.log').exists())
        self.assertFalse((target / 'data/legal.sqlite3-wal').exists())
        self.assertEqual(json.loads((self.root / 'config/shared-library.json').read_text()), self.config)
        self.assertTrue(manifest['corpus']['license_evidence'])

    def test_export_and_restore_never_overwrite(self):
        self.export()
        before = self.archive.read_bytes()
        with self.assertRaises((ValueError, FileExistsError)):
            self.export()
        self.assertEqual(self.archive.read_bytes(), before)
        target = self.base / 'existing'
        target.mkdir()
        (target / 'keep').write_text('untouched')
        with self.assertRaises((ValueError, FileExistsError)):
            self.api.restore_library(self.archive, target)
        self.assertEqual((target / 'keep').read_text(), 'untouched')

    def test_optional_disclosure_config_roundtrips_byte_for_byte(self):
        payload = (Path(__file__).resolve().parents[1]/'config/jilin-disclosures.json').read_bytes()
        (self.root/'config/jilin-disclosures.json').write_bytes(payload)
        self.export()
        target = self.base/'restored-disclosures'
        self.api.restore_library(self.archive, target)
        self.assertTrue((target/'config/jilin-disclosures.json').exists(), 'new disclosure config omitted')
        self.assertEqual((target/'config/jilin-disclosures.json').read_bytes(), payload)

    def test_unknown_data_root_refused(self):
        (self.root / 'data/private-cases').mkdir()
        with self.assertRaisesRegex(ValueError, 'unknown|Unknown|未知'):
            self.export()
        self.assertFalse(self.archive.exists())

    def test_source_symlink_refused(self):
        (self.root / 'data/quarantine/linked').symlink_to(self.corpus)
        with self.assertRaisesRegex(ValueError, '[Ss]ymlink|symbolic|符号'):
            self.export()

    def test_each_existing_writer_lock_blocks_export(self):
        for name in ('scheduler', 'source-probes', 'official-monitor', 'law-discovery', 'jilin-samples'):
            with self.subTest(name=name), (self.root / f'verification/{name}.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaisesRegex((ValueError, BlockingIOError), 'lock|锁'):
                    self.export()
                self.assertFalse(self.archive.exists())

    def test_file_change_during_snapshot_refused(self):
        original = self.api._backup_database
        def mutate(source, target):
            original(source, target)
            (self.root / 'data/quarantine/new.bin').write_bytes(b'new')
        with patch.object(self.api, '_backup_database', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'chang|变'):
                self.export()
        self.assertFalse(self.archive.exists())

    def test_database_change_during_snapshot_refused(self):
        original = self.api._backup_database
        def mutate(source, target):
            original(source, target)
            self.store.revoke(self.version, reviewer='human', reason='new audit')
        with patch.object(self.api, '_backup_database', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'chang|变'):
                self.export()
        self.assertFalse(self.archive.exists())

    def test_unsafe_members_refused_before_restore(self):
        self.export()
        original = self.archive.read_bytes()
        for name in ('../escape', '/absolute', 'data\\escape', 'data/quarantine/../escape',
                     'data/quarantine//bad', 'data/quarantine/./bad', 'C:/bad'):
            with self.subTest(name=name):
                self.archive.write_bytes(original)
                self.rewrite(lambda rows: rows + [(zipfile.ZipInfo(name), b'bad')])
                target = self.base / 'refused'
                with self.assertRaises(ValueError):
                    self.api.restore_library(self.archive, target)
                self.assertFalse(target.exists())

    def test_duplicate_case_unicode_and_symlink_members_refused(self):
        self.export()
        original = self.archive.read_bytes()
        pairs = [('data/quarantine/A', 'data/quarantine/a'),
                 ('data/quarantine/é', 'data/quarantine/e\u0301')]
        for names in pairs:
            self.archive.write_bytes(original)
            self.rewrite(lambda rows: rows + [(zipfile.ZipInfo(n), b'x') for n in names])
            with self.assertRaises(ValueError):
                self.api.verify_archive(self.archive)
        self.archive.write_bytes(original)
        info = zipfile.ZipInfo('data/quarantine/link')
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.rewrite(lambda rows: rows + [(info, b'/etc/passwd')])
        with self.assertRaises(ValueError):
            self.api.verify_archive(self.archive)

    def test_corrupt_missing_unlisted_and_unsupported_manifest_refused(self):
        self.export()
        original = self.archive.read_bytes()
        transforms = [
            lambda rows: [(entry, b'corrupt' if entry.filename.endswith('original.bin') else body) for entry, body in rows],
            lambda rows: [(entry, body) for entry, body in rows if not entry.filename.endswith('original.bin')],
            lambda rows: rows + [(zipfile.ZipInfo('data/quarantine/unlisted'), b'x')],
            lambda rows: [(entry, json.dumps({**json.loads(body), 'format_version': 999}).encode()
                          if entry.filename == 'manifest.json' else body) for entry, body in rows],
        ]
        for transform in transforms:
            self.archive.write_bytes(original)
            self.rewrite(transform)
            with self.assertRaises(ValueError):
                self.api.verify_archive(self.archive)

    def test_database_text_or_fts_mismatch_refused(self):
        self.store.db.execute("UPDATE versions SET text='changed'")
        self.store.db.commit()
        with self.assertRaisesRegex(ValueError, 'hash|text|正文'):
            self.export()

    def test_bounds_enforced(self):
        self.export()
        with patch.object(self.api, 'MAX_ENTRIES', 2):
            with self.assertRaises(ValueError):
                self.api.verify_archive(self.archive)
        with patch.object(self.api, 'MAX_FILE_BYTES', 4):
            with self.assertRaises(ValueError):
                self.api.verify_archive(self.archive)

    def test_case_colliding_directory_prefixes_refused(self):
        self.export()
        def add_collision(rows):
            manifest_entry, raw = next((e, b) for e, b in rows if e.filename == 'manifest.json')
            manifest = json.loads(raw)
            additions = [('data/quarantine/A/one', b'x'), ('data/quarantine/a/two', b'y')]
            for name, body in additions:
                manifest['files'][name] = {'size': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
            return [(e, b) for e, b in rows if e.filename != 'manifest.json'] + [
                (manifest_entry, json.dumps(manifest).encode())] + [(zipfile.ZipInfo(n), b) for n, b in additions]
        self.rewrite(add_collision)
        with self.assertRaises(ValueError):
            self.api.verify_archive(self.archive)

    def test_malformed_manifest_rejected_as_value_error(self):
        self.export()
        self.rewrite(lambda rows: [(e, b'[]' if e.filename == 'manifest.json' else b) for e, b in rows])
        with self.assertRaises(ValueError):
            self.api.verify_archive(self.archive)

    def test_missing_fts_entries_refused(self):
        self.store.db.execute('DELETE FROM search_index')
        self.store.db.commit()
        with self.assertRaisesRegex(ValueError, 'FTS|integrity|SQLite'):
            self.export()

    def test_core_column_types_are_checked(self):
        schema = self.store.db.execute("SELECT sql FROM sqlite_master WHERE name='versions'").fetchone()[0]
        rows = self.store.db.execute('SELECT * FROM versions').fetchall()
        self.store.db.execute('DROP TABLE versions')
        self.store.db.execute(schema.replace('law_id TEXT', 'law_id BLOB'))
        self.store.db.executemany('INSERT INTO versions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', rows)
        self.store.db.commit()
        with self.assertRaisesRegex(ValueError, 'schema'):
            self.export()

    def test_sensitive_descendant_names_are_refused_on_export(self):
        for name in ('debug.log', '.env.local', 'credentials.json', 'private-cases/client.txt',
                     'cache/response.json', 'secrets/api-key.txt'):
            with self.subTest(name=name):
                candidate = self.root / 'data/quarantine' / name
                candidate.parent.mkdir(parents=True, exist_ok=True)
                candidate.write_text('sensitive test fixture')
                try:
                    with self.assertRaisesRegex(ValueError, 'sensitive|private|secret|cache|log'):
                        self.export()
                    self.assertFalse(self.archive.exists())
                finally:
                    candidate.unlink()
                    self.archive.unlink(missing_ok=True)
                    if candidate.parent != self.root / 'data/quarantine':
                        candidate.parent.rmdir()

    def test_sensitive_descendant_names_are_refused_in_manifested_archives(self):
        self.export()
        original = self.archive.read_bytes()
        for suffix in ('debug.log', '.env.local', 'credentials.json', 'private-cases/client.txt', 'cache/x'):
            self.archive.write_bytes(original)
            name, body = 'data/quarantine/' + suffix, b'sensitive'
            def inject(rows):
                result = []
                for entry, raw in rows:
                    if entry.filename == 'manifest.json':
                        manifest = json.loads(raw)
                        manifest['files'][name] = {'size': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
                        raw = json.dumps(manifest).encode()
                    result.append((entry, raw))
                return result + [(zipfile.ZipInfo(name), body)]
            self.rewrite(inject)
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.api.verify_archive(self.archive)

    def test_fts_tokenizer_and_unindexed_identifier_are_required(self):
        for declaration in ("version_id UNINDEXED, title, text, tokenize='unicode61'",
                            "version_id, title, text, tokenize='trigram'"):
            self.archive.unlink(missing_ok=True)
            self.store.db.execute('DROP TABLE search_index')
            self.store.db.execute('CREATE VIRTUAL TABLE search_index USING fts5(' + declaration + ')')
            self.store.db.execute('INSERT INTO search_index SELECT version_id,title,text FROM versions')
            self.store.db.commit()
            with self.subTest(declaration=declaration), self.assertRaisesRegex(ValueError, 'FTS|schema'):
                self.export()

    def test_official_monitor_originals_are_included(self):
        original = self.root / 'data/official-monitor/id/hash/original.html'
        original.parent.mkdir(parents=True)
        original.write_bytes(b'official public content')
        manifest = self.export()
        self.assertIn(original.relative_to(self.root).as_posix(), manifest['files'])

    def test_staged_database_is_delete_mode_with_no_generated_sidecars(self):
        manifest = self.export()
        self.assertFalse(any(n.endswith(('-wal', '-shm')) for n in manifest['files']))
        target = self.base / 'restored'
        self.api.restore_library(self.archive, target)
        db = target / 'data/legal.sqlite3'
        self.assertEqual(db.read_bytes()[18:20], b'\x01\x01')
        self.assertFalse(db.with_name('legal.sqlite3-wal').exists())
        self.assertFalse(db.with_name('legal.sqlite3-shm').exists())

    def test_restored_library_can_be_exported_again(self):
        first = self.export()
        target = self.base / 'restored'
        self.api.restore_library(self.archive, target)
        second = self.api.export_library(target, self.base / 'again.zip')
        for key in ('database', 'corpus', 'ledger_counts'):
            self.assertEqual(first[key], second[key])
        self.assertEqual({k: v for k, v in first['files'].items() if k != 'data/legal.sqlite3'},
                         {k: v for k, v in second['files'].items() if k != 'data/legal.sqlite3'})

    def test_restore_publication_race_does_not_replace_existing_empty_target(self):
        self.export()
        target = self.base / 'racing'
        original = self.api._rename_directory_no_replace
        def race(source, destination):
            target.mkdir()
            original(source, destination)
        with patch.object(self.api, '_rename_directory_no_replace', side_effect=race):
            with self.assertRaises(FileExistsError):
                self.api.restore_library(self.archive, target)
        self.assertEqual(list(target.iterdir()), [])

    def test_cli_export_verify_restore(self):
        script = Path(__file__).resolve().parents[1] / 'scripts/transfer_library.py'
        target = self.base / 'cli-restored'
        for arguments in [('export', '--root', str(self.root)), ('verify',),
                          ('restore', '--target', str(target))]:
            result = subprocess.run([sys.executable, str(script), *arguments, '--archive', str(self.archive)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['format_version'], 1)


if __name__ == '__main__':
    unittest.main()
