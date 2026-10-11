import base64
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/refresh_upstream_catalog.py'
API = 'https://api.github.com/repos/lawtext/law-flk-vol1'


def remote_fixture(ids, commit='a' * 40, corrupt=False):
    records = json.dumps({'update': '20260927', 'stats': {'total': len(ids)},
                          'data': [{'bbbs': key, 'title': '示例法规', 'flxz': '法律'} for key in ids]}).encode()
    files = {'records.json': records, 'LOG.md': b'# upstream notes\n'}
    responses = {API + '/commits/main': {'sha': commit, 'commit': {'committer': {'date': '2026-09-27T00:00:00Z'}}}}
    listing = []
    for name, raw in files.items():
        sha = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        listing.append({'name': name, 'type': 'file', 'size': len(raw), 'sha': sha})
        responses[API + '/git/blobs/' + sha] = {'sha': sha, 'size': len(raw), 'encoding': 'base64',
                                               'content': base64.b64encode(raw + (b'x' if corrupt else b'')).decode()}
    responses[API + '/contents/?ref=' + commit] = listing
    return responses.__getitem__


class UpstreamCatalogTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.exists(), '目录刷新脚本尚未实现')
        spec = importlib.util.spec_from_file_location('refresh_upstream_catalog', SCRIPT)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.local = self.root / 'local.json'
        self.local.write_text(json.dumps({'laws': {'1' * 32: {'title': '本地法规', 'provisions': [{'text': '正文不应导出'}]}}}))
        self.config = self.root / 'config.json'
        self.config.write_text(json.dumps({'corpus_path': str(self.local)}))
        self.output = self.root / 'catalog'

    def run_refresh(self, fetch):
        return self.module.refresh(self.config, self.output, fetch_json=fetch)

    def test_pinned_snapshot_has_exact_gap_hash_and_no_local_body(self):
        result = self.run_refresh(remote_fixture(['1' * 32, '2' * 32]))
        self.assertEqual(result['upstream_only_ids'], 1)
        self.assertEqual(result['local_only_ids'], 0)
        snapshot = self.output / result['snapshot']
        gap = json.loads((snapshot / 'catalog-gap.json').read_text())
        self.assertEqual([row['bbbs'] for row in gap['upstream_only']], ['2' * 32])
        manifest = json.loads((snapshot / 'manifest.json').read_text())
        self.assertEqual(manifest['upstream_commit'], 'a' * 40)
        self.assertFalse(manifest['readme_present'])
        self.assertNotIn('正文不应导出', (snapshot / 'catalog-gap.json').read_text())
        for name, item in manifest['files'].items():
            self.assertEqual(hashlib.sha256((snapshot / name).read_bytes()).hexdigest(), item['sha256'])

    def test_empty_duplicate_corrupt_and_network_failure_preserve_last_good(self):
        self.run_refresh(remote_fixture(['1' * 32]))
        before = (self.output / 'latest.json').read_bytes()
        failures = [remote_fixture([], 'b' * 40), remote_fixture(['2' * 32, '2' * 32], 'b' * 40),
                    remote_fixture(['2' * 32], 'b' * 40, corrupt=True)]
        def offline(url):
            raise OSError('network unavailable')
        for fetch in failures + [offline]:
            with self.subTest(fetch=fetch):
                with self.assertRaises((ValueError, OSError)):
                    self.run_refresh(fetch)
                self.assertEqual((self.output / 'latest.json').read_bytes(), before)

    def test_new_commit_reports_incremental_ids_and_retains_previous_snapshot(self):
        first = self.run_refresh(remote_fixture(['1' * 32]))
        second = self.run_refresh(remote_fixture(['1' * 32, '2' * 32], 'b' * 40))
        self.assertEqual(second['new_upstream_ids'], ['2' * 32])
        self.assertTrue((self.output / first['snapshot'] / 'records.json').exists())
        third = self.run_refresh(remote_fixture(['1' * 32, '2' * 32], 'b' * 40))
        self.assertEqual(third['status'], 'unchanged')
        self.assertEqual(third['new_upstream_ids'], [])

    def test_local_corpus_change_recomputes_gap_without_new_upstream_commit(self):
        remote = remote_fixture(['1' * 32, '2' * 32])
        first = self.run_refresh(remote)
        self.local.write_text(json.dumps({'laws': {key: {'title': '法规'} for key in ['1' * 32, '2' * 32]}}))
        second = self.run_refresh(remote)
        self.assertEqual(second['upstream_only_ids'], 0)
        self.assertNotEqual(first['snapshot'], second['snapshot'])
