import unittest
import io
import gzip
import json
import logging
import tempfile
from pathlib import Path
from unittest.mock import patch
import httpx

from scripts.check_official_originals import fetch_original, main
from scripts import check_official_originals as monitor_script
from official_monitor import dashboard_lines


class DownloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_verbose_http_logging_cannot_leak_signed_url(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logger = logging.getLogger('httpx')
        previous = logger.level
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)
        try:
            await self.fetch()
            self.assertNotIn('SECRET', stream.getvalue())
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous)

    async def test_access_block_precedes_bad_configuration_and_preserves_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'config').mkdir()
            (root / 'config/official-monitor.json').write_text('{broken')
            (root / 'verification').mkdir()
            path = root / 'verification/official-monitor-latest.json'
            path.write_text(json.dumps({'ok': True, 'complete': True, 'at': 'old', 'results': [
                {'law_id': 'a' * 32, 'title': '测试法', 'status': 'unchanged',
                 'last_success': 'old-success', 'pending_snapshots': ['retained']}]}))
            old = path.read_bytes()
            with patch('scripts.check_official_originals.ROOT', root):
                result = await main()
            self.assertFalse(result['ok'])
            saved = json.loads(path.read_text())
            self.assertFalse(saved['ok'])
            self.assertFalse(saved['complete'])
            self.assertNotEqual(saved['at'], 'old')
            self.assertEqual(saved['status'], 'access_blocked')
            self.assertEqual((root / saved['previous_report']).read_bytes(), old)
            self.assertEqual(saved['results'], [])

    def setUp(self):
        self.target = {'law_id': 'a' * 32, 'title': '测试法', 'original_path': 'original.docx'}
        self.detail = {'bbbs': 'a' * 32, 'title': '测试法', 'sxx': 3,
                       'gbrq': '2020-01-01', 'sxrq': None, 'zdjgName': '制定机关',
                       'flxz': '法律', 'ossFile': {'ossWordPath': 'prod/test.docx'}}
        self.url = 'https://flkoss.obs-bj2.cucloud.cn/prod/test.docx?Signature=SECRET'
        self.status = 200
        self.body = b'PK\x03\x04fake-word'
        self.requests = []
        self.headers = {}

    async def get(self, path):
        if path.startswith('search/flfgDetails?bbbs='):
            self.assertEqual(path, 'search/flfgDetails?bbbs=' + self.target['law_id'])
            return {'data': self.detail}
        self.assertEqual(path, 'download/pc?bbbs=' + self.target['law_id'] + '&format=docx')
        return {'data': {'url': self.url}}

    async def fetch(self):
        def handler(request):
            self.requests.append(str(request.url))
            return httpx.Response(self.status, content=self.body,
                                  headers={'location': 'https://example.test/secret', **self.headers})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False) as download:
            return await fetch_original(self.target, self, download)

    async def test_valid_response_returns_only_bytes_and_selected_metadata(self):
        payload, metadata = await self.fetch()
        self.assertEqual(payload, b'PK\x03\x04fake-word')
        self.assertEqual(metadata['sxrq'], None)
        self.assertNotIn('SECRET', str(metadata))

    async def test_identity_and_title_mismatch_never_download(self):
        for key in ('bbbs', 'title'):
            original = self.detail[key]
            self.detail[key] = 'other'
            with self.assertRaises(ValueError):
                await self.fetch()
            self.detail[key] = original
        self.assertEqual(self.requests, [])

    async def test_off_domain_and_wrong_path_never_download(self):
        for url in ('https://example.test/prod/test.docx',
                    'http://flkoss.obs-bj2.cucloud.cn/prod/test.docx',
                    'https://flkoss.obs-bj2.cucloud.cn/prod/other.docx'):
            self.url = url
            with self.assertRaises(ValueError):
                await self.fetch()
        self.assertEqual(self.requests, [])

    async def test_redirect_http_error_html_and_size_limit_rejected(self):
        for status, body in ((302, b''), (403, b'denied'), (200, b'<html>captcha</html>'),
                             (200, b'PK\x03\x04' + b'x' * 10_000_000)):
            with self.subTest(status=status, length=len(body)):
                self.status, self.body = status, body
                with self.assertRaises((ValueError, httpx.HTTPError)):
                    await self.fetch()

    async def test_missing_or_structured_metadata_rejected(self):
        del self.detail['sxx']
        with self.assertRaises(ValueError):
            await self.fetch()
        self.detail['sxx'] = {'unexpected': 'value'}
        with self.assertRaises(ValueError):
            await self.fetch()

    async def test_unexpected_compression_rejected_before_reading_document(self):
        self.headers = {'content-encoding': 'gzip'}
        self.body = gzip.compress(b'PK\x03\x04fake-word')
        with self.assertRaises(ValueError):
            await self.fetch()

    async def test_json_api_is_size_bounded_and_checks_api_status(self):
        class Upstream:
            async def _rate_limit(self):
                pass
            def _get_client(self):
                return client
        for body, accepted in ((b'{"code":200,"data":{"ok":true}}', True),
                               (b'{"code":403,"data":{}}', False),
                               (b'{"code":200,"data":"' + b'x' * 2_000_000 + b'"}', False)):
            async with httpx.AsyncClient(base_url='https://flk.npc.gov.cn/law-search/',
                    transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body))) as client:
                api = monitor_script.BoundedAPI(Upstream())
                if accepted:
                    self.assertEqual(await api.get('search/test'), {'code': 200, 'data': {'ok': True}})
                else:
                    with self.assertRaises(ValueError):
                        await api.get('search/test')
    def test_dashboard_does_not_turn_incomplete_or_failed_into_success(self):
        text = '\n'.join(dashboard_lines({'at': 'test-time', 'complete': False, 'results': [
            {'status': 'failed', 'pending_snapshots': ['saved']}]}))
        self.assertIn('test-time', text)
        self.assertIn('False', text)
        self.assertIn('失败：1', text)
        self.assertIn('待审变化的文件：1', text)
        self.assertIn('尚未检查', '\n'.join(dashboard_lines({})))
