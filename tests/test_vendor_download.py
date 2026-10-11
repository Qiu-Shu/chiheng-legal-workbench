"""Regression checks extract vendor functions without loading .env or starting MCP."""
import ast
import asyncio
import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit


VENDOR = Path(__file__).resolve().parents[1] / 'vendor/treasury/sources/legal-tools'


class VendorDownloadTests(unittest.TestCase):
    def test_article_split_preserves_chinese_zero_labels(self):
        source = VENDOR.parent / 'china-law/scripts/build_index.py'
        spec = importlib.util.spec_from_file_location('isolated_index_builder', source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        text = ('- **第一百条**　第一段。\n'
                '- **第一百零一条**　第二段。\n'
                '- **第一百〇二条**　第三段。')
        rows = module.split_articles(text)
        self.assertEqual([row['article'] for row in rows],
                         ['第一百条', '第一百零一条', '第一百〇二条'])
        self.assertEqual([row['text'] for row in rows], ['第一段。', '第二段。', '第三段。'])

    def test_legacy_search_does_not_claim_t1_verified(self):
        source = VENDOR.parent / 'china-law/scripts/search.py'
        run = subprocess.run([sys.executable, '-B', str(source),
                              '民事主体的人身权利', '--top', '1'],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertNotIn('T1=核心·已确认', run.stdout)
        self.assertIn('T1=核心·需核验', run.stdout)

    def test_download_uses_official_format_parameter(self):
        source = VENDOR / '国家法律法规数据库MCP/scripts/server.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        function = next(node for node in tree.body
                        if isinstance(node, ast.AsyncFunctionDef) and node.name == 'download')
        function.decorator_list = []
        calls = []

        async def fake_get(path):
            calls.append(path)
            return {'code': 200, 'data': {'url': 'https://example.org/law.docx'}}

        namespace = {'FlkDownloadInput': SimpleNamespace,
                     'client': SimpleNamespace(get=fake_get),
                     'format_download': lambda data: data,
                     '_handle_error': lambda error: str(error)}
        module = ast.Module(body=[function], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), str(source), 'exec'), namespace)
        result = asyncio.run(namespace['download'](SimpleNamespace(
            bbbs='ff808081729d1efe01729d50b5c500bf', file_type='docx')))
        self.assertEqual(result, {'url': 'https://example.org/law.docx'})
        self.assertEqual(len(calls), 1)
        parsed = urlsplit(calls[0])
        self.assertEqual(parsed.path, 'download/pc')
        params = parse_qs(parsed.query)
        self.assertEqual(params.get('format'), ['docx'])
        self.assertEqual(params.get('bbbs'), ['ff808081729d1efe01729d50b5c500bf'])
        self.assertNotIn('fileType', params)

    def test_case_client_requires_tls_verification(self):
        source = VENDOR / '人民法院案例库MCP/scripts/client.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        klass = next(node for node in tree.body
                     if isinstance(node, ast.ClassDef) and node.name == 'RmfyalkClient')
        function = next(node for node in klass.body
                        if isinstance(node, ast.FunctionDef) and node.name == '_get_client')
        function.returns = None
        calls = []

        def fake_client(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(headers=kwargs['headers'])

        namespace = {'httpx': SimpleNamespace(AsyncClient=fake_client),
                     'BASE_URL': 'https://rmfyalk.court.gov.cn/cpws_al_api/api/'}
        module = ast.Module(body=[function], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), str(source), 'exec'), namespace)
        namespace['_get_client'](SimpleNamespace(_client=None, _token=''))
        self.assertEqual(len(calls), 1)
        self.assertIs(calls[0].get('verify', True), True)
        self.assertNotIn('faxin-cpws-al-token', calls[0]['headers'])


if __name__ == '__main__':
    unittest.main()
