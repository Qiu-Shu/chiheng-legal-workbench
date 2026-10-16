import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
from urllib.request import url2pathname
from scripts import export_obsidian_library as exporter
from scripts.export_obsidian_library import export, MARKER


class ObsidianExportTests(unittest.TestCase):
    def test_blocked_history_links_open_project_reports_from_another_vault(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / '项目 空间'
            (root / 'config').mkdir(parents=True)
            (root / 'config/shared-library.json').write_text('{"corpus_path":"unused"}')
            folder = root / 'verification/access-blocked-history'
            folder.mkdir(parents=True)
            expected = set()
            saved = {}
            for name in ('official-monitor', 'law-discovery'):
                previous = folder / (name + '-旧 报告.json')
                previous.write_text('{"historical":true}')
                expected.add(previous.resolve())
                latest = root / 'verification' / (name + '-latest.json')
                latest.write_text(json.dumps({'status': 'access_blocked',
                    'reason': '来源禁止自动化采集',
                    'evidence': {'url': 'https://flk.npc.gov.cn/robots.txt'},
                    'previous_report': str(previous.relative_to(root))}))
                saved[latest] = latest.read_bytes()
            target = Path(tmp) / '另一个 知识库/看板.md'
            with patch.object(exporter, 'ROOT', root), \
                    patch.object(exporter, 'PublicCorpus') as corpus, \
                    patch.object(exporter, 'LegalStore') as store:
                corpus.return_value.inventory.return_value = {}
                store.return_value.health.return_value = {'versions': 0, 'published': 0}
                export(target)
            links = re.findall(r'\[旧报告\]\(([^)]+)\)', target.read_text())
            self.assertEqual(len(links), 2)
            opened = set()
            for link in links:
                parsed = urlsplit(link)
                self.assertEqual(parsed.scheme, 'file')
                self.assertNotIn(' ', link)
                self.assertNotIn('旧', link)
                opened_path = Path(url2pathname(parsed.path))
                self.assertEqual(opened_path.read_text(), '{"historical":true}')
                opened.add(opened_path.resolve())
            self.assertEqual(opened, expected)
            self.assertEqual({path: path.read_bytes() for path in saved}, saved)

    def test_refuse_to_overwrite_unmanaged_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'user.md'
            target.write_text('用户笔记')
            with self.assertRaises(ValueError):
                export(target)
            self.assertEqual(target.read_text(), '用户笔记')

    def test_export_measured_public_inventory_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'managed.md'
            export(target)
            text = target.read_text()
            self.assertTrue(text.startswith(MARKER))
            self.assertIn('unverified_mirror', text)
            self.assertIn('SQLite已入库', text)
            export(target)
