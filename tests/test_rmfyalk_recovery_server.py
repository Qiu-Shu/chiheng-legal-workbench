"""MCP behavior checks with the real server and client, using synthetic transport."""

import asyncio
import importlib.util
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_rmfyalk_recovery import (UPSTREAM, SECRET_A, SECRET_B, httpx,
                                  DEPS, load_client, make_client, write_credentials)


def load_server(client_module):
    source = UPSTREAM / 'scripts/server.py'
    spec = importlib.util.spec_from_file_location('isolated_rmfyalk_server', source)
    module = importlib.util.module_from_spec(spec)
    scripts = str(source.parent)
    previous_client = sys.modules.get('client')
    previous_mcp = {name: value for name, value in sys.modules.items()
                    if name == 'mcp' or name.startswith('mcp.')}
    for name in previous_mcp:
        sys.modules.pop(name)
    sys.modules['client'] = client_module
    sys.path.insert(0, str(DEPS))
    sys.path.insert(0, scripts)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(scripts)
        sys.path.remove(str(DEPS))
        for name in list(sys.modules):
            if name == 'mcp' or name.startswith('mcp.'):
                sys.modules.pop(name)
        sys.modules.update(previous_mcp)
        if previous_client is None:
            sys.modules.pop('client', None)
        else:
            sys.modules['client'] = previous_client
    return module


def valid_payloads():
    return [
        {'code': 0, 'data': {'userId': SECRET_A, 'phone': SECRET_B}},
        {'code': 0, 'data': {'datas': [
            {'cpws_al_id': 'search-encoded-id', 'cpws_al_no': '2026-synthetic-case',
             'cpws_al_ajzh': 'synthetic-reference'}], 'totalCount': 1}},
        {'code': 0, 'data': {'data': {
            'cpws_al_id': 'detail-encoded-id', 'cpws_al_no': '2026-synthetic-case',
            'cpws_al_ajzh': 'synthetic-reference', 'cpws_al_cpyz': '<p>公开裁判要点</p>'}}},
    ]


class SdkIsolationTests(unittest.TestCase):
    def test_cached_sdk2_is_restored_after_real_vendor_sdk1_registration(self):
        script = '''
import sys
import tempfile
from pathlib import Path
import mcp
from mcp.server.mcpserver import MCPServer
assert "site-packages" in mcp.__file__
cached = {name: module for name, module in sys.modules.items()
          if name == "mcp" or name.startswith("mcp.")}
sys.path.insert(0, "tests")
from test_rmfyalk_recovery import load_client, write_credentials
from test_rmfyalk_recovery_server import load_server
path_before = list(sys.path)
with tempfile.TemporaryDirectory() as temp:
    path = Path(temp) / "private" / "case-access.env"
    write_credentials(path)
    server = load_server(load_client(path))
    assert server.mcp.__class__.__module__ == "mcp.server.fastmcp.server"
assert list(sys.path) == path_before
restored = {name: module for name, module in sys.modules.items()
            if name == "mcp" or name.startswith("mcp.")}
assert restored.keys() == cached.keys()
assert all(restored[name] is module for name, module in cached.items())
from mcp.server.mcpserver import MCPServer as restored_server
assert restored_server is MCPServer
assert "formatters" in sys.modules
'''
        run = subprocess.run([sys.executable, '-B', '-c', script],
                             cwd=Path(__file__).resolve().parents[1],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_vendor_fixture_first_does_not_change_later_project_sdk_selection(self):
        script = '''
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, "tests")
path_before = list(sys.path)
from test_rmfyalk_recovery import load_client, write_credentials
from test_rmfyalk_recovery_server import load_server
assert list(sys.path) == path_before
with tempfile.TemporaryDirectory() as temp:
    path = Path(temp) / "private" / "case-access.env"
    write_credentials(path)
    server = load_server(load_client(path))
    assert server.mcp.__class__.__module__ == "mcp.server.fastmcp.server"
assert not any(name == "mcp" or name.startswith("mcp.") for name in sys.modules)
assert list(sys.path) == path_before
import legal_mcp
import mcp
from mcp.server.mcpserver import MCPServer
assert "site-packages" in mcp.__file__
assert isinstance(legal_mcp.server, MCPServer)
'''
        run = subprocess.run([sys.executable, '-B', '-c', script],
                             cwd=Path(__file__).resolve().parents[1],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'private' / 'case-access.env'
        write_credentials(self.path)
        with patch.dict(os.environ, {'RMFYALK_TOKEN': SECRET_A}):
            self.client_module = load_client(self.path)
            self.client = make_client(self.client_module, self.path)
        self.server = load_server(self.client_module)
        self.server.client = self.client
        self.requests = []
        self.clients = []

    async def asyncTearDown(self):
        for client in self.clients:
            await client.aclose()

    def transport(self, payloads, after_response=None):
        def response(request):
            index = len(self.requests)
            self.requests.append(request)
            item = payloads[index]
            if after_response:
                after_response(index)
            if isinstance(item, Exception):
                raise item
            if isinstance(item, httpx.Response):
                return item
            return httpx.Response(200, json=item)

        c = httpx.AsyncClient(base_url=self.client_module.BASE_URL,
                              transport=httpx.MockTransport(response))
        self.clients.append(c)
        self.client._client = c

    def assert_safe(self, output):
        self.assertNotIn(SECRET_A, output)
        self.assertNotIn(SECRET_B, output)
        self.assertNotIn('rmfyalk_set_token', output)
        self.assertNotIn('用户ID', output)
        self.assertNotIn('手机号', output)
        self.assertNotIn('小时', output)

    async def test_expiry_error_explicitly_requests_official_relogin_and_local_update(self):
        output = self.server._handle_error(self.client_module.TokenExpiredError(SECRET_A))
        self.assertIn('需要您重新登录官网', output)
        self.assertIn('https://rmfyalk.court.gov.cn/', output)
        self.assertIn('现有本地', output)
        self.assert_safe(output)

    async def test_classified_file_network_and_unknown_errors_are_distinct_and_safe(self):
        file_outputs = []
        for kind in ('missing', 'empty', 'unreadable', 'unsafe', 'oversize', 'malformed', 'duplicate', 'changed'):
            error = self.client_module.CredentialError(kind)
            output = self.server._handle_error(error)
            file_outputs.append(output)
            self.assert_safe(output)
            self.assertNotIn('重新登录', output)
        self.assertEqual(len(set(file_outputs)), len(file_outputs))
        for error in (self.client_module.ApiError('network'),
                      self.client_module.ApiError('timeout'),
                      self.client_module.ApiError('forbidden'),
                      RuntimeError('401 SSL ' + SECRET_A)):
            output = self.server._handle_error(error)
            self.assert_safe(output)
            self.assertNotIn('重新登录', output)

    async def test_enumeration_uses_shared_fresh_authenticated_encoded_get(self):
        write_credentials(self.path, SECRET_B)
        self.transport([{'code': 0, 'data': [{'id': '1', 'title': '分类', 'last': True}]}])
        output = await self.server.get_enum(self.server.EnumInput(field='court', parent_id='A&B 中文'))
        self.assertIn('分类', output)
        self.assertEqual(len(self.requests), 1)
        request = self.requests[0]
        self.assertEqual(request.method, 'GET')
        self.assertTrue(request.url.path.endswith('/common/getXmlToTree'))
        self.assertEqual(request.url.params['xmlName'], 'cpal_fcourt_id.xml')
        self.assertEqual(request.url.params['nodeId'], 'A&B 中文')
        self.assertEqual(request.headers['faxin-cpws-al-token'], SECRET_B)

    async def test_enumeration_and_check_file_errors_prevent_network(self):
        self.transport(valid_payloads())
        self.path.unlink()
        output = await self.server.get_enum(self.server.EnumInput(field='sort'))
        self.assertIn('本地', output)
        output = await self.server.check_token()
        self.assertIn('本地', output)
        self.assertEqual(len(self.requests), 0)
        self.assert_safe(output)

    async def test_check_ready_requires_all_three_actual_stages_and_hides_identity(self):
        self.transport(valid_payloads())
        output = await self.server.check_token()
        self.assertIn('网站实际可用', output)
        for stage in ('账号接口', '检索', '详情'):
            self.assertIn(stage, output)
        self.assert_safe(output)
        self.assertEqual(len(self.requests), 3)
        self.assertEqual([r.url.path.rsplit('/', 2)[-2:] for r in self.requests],
                         [['user', 'getUserInfo'], ['cpwsAl', 'search'], ['cpwsAl', 'content']])
        bodies = [json.loads(r.content) for r in self.requests]
        self.assertEqual(bodies[0], {'state': ''})
        self.assertEqual(bodies[1]['page'], 1)
        self.assertEqual(bodies[1]['size'], 1)
        self.assertEqual(bodies[1]['searchParams']['keyTitle'], ['买卖合同'])
        self.assertEqual(bodies[2], {'gid': 'search-encoded-id'})

    async def test_check_does_not_claim_ready_for_empty_or_malformed_user(self):
        for user_data in ({}, None, [], '', SECRET_A):
            self.requests.clear()
            self.transport([{'code': 0, 'data': user_data}])
            with self.subTest(user_data=type(user_data).__name__):
                output = await self.server.check_token()
                self.assertNotIn('网站实际可用', output)
                self.assertIn('账号接口', output)
                self.assertEqual(len(self.requests), 1)
                self.assert_safe(output)

    async def test_check_does_not_claim_ready_for_empty_invalid_search_or_id(self):
        for data in ({}, {'datas': []}, {'datas': None}, {'datas': [{}]},
                     {'datas': [{'cpws_al_id': ''}]}, {'datas': [SECRET_A]}, [],
                     {'datas': [{'cpws_al_id': None}]}):
            self.requests.clear()
            payloads = valid_payloads()
            payloads[1] = {'code': 0, 'data': data}
            self.transport(payloads)
            with self.subTest(data=data):
                output = await self.server.check_token()
                self.assertNotIn('网站实际可用', output)
                self.assertIn('检索', output)
                self.assertEqual(len(self.requests), 2)
                self.assert_safe(output)

    async def test_check_does_not_claim_ready_for_empty_invalid_detail_or_text(self):
        for data in ({}, {'data': {}}, {'data': None}, {'data': []},
                     {'data': {'cpws_al_cpyz': '', 'cpws_al_jbaq': '  ', 'cpws_al_cply': '<p> </p>'}},
                     {'data': {'cpws_al_cpyz': {'private': SECRET_A}}}):
            self.requests.clear()
            payloads = valid_payloads()
            payloads[2] = {'code': 0, 'data': data}
            self.transport(payloads)
            with self.subTest(data=data):
                output = await self.server.check_token()
                self.assertNotIn('网站实际可用', output)
                self.assertIn('详情', output)
                self.assertEqual(len(self.requests), 3)
                self.assert_safe(output)

    async def test_check_compares_stable_case_reference_not_encoded_id(self):
        for field in ('cpws_al_no', 'cpws_al_ajzh'):
            self.requests.clear()
            payloads = valid_payloads()
            payloads[2]['data']['data'][field] = 'contradiction'
            self.transport(payloads)
            output = await self.server.check_token()
            self.assertNotIn('网站实际可用', output)
            self.assertIn('不一致', output)
            self.assert_safe(output)
        self.requests.clear()
        payloads = valid_payloads()
        payloads[2]['data']['data'].pop('cpws_al_no')
        payloads[2]['data']['data'].pop('cpws_al_ajzh')
        self.transport(payloads)
        self.assertIn('网站实际可用', await self.server.check_token())

    async def test_check_malformed_case_number_never_means_ready(self):
        for side in ('search', 'detail'):
            self.requests.clear()
            payloads = valid_payloads()
            case = payloads[1]['data']['datas'][0] if side == 'search' else payloads[2]['data']['data']
            case['cpws_al_no'] = 7
            self.transport(payloads)
            output = await self.server.check_token()
            self.assertNotIn('网站实际可用', output)
            self.assertIn('详情', output)
            self.assertIn('格式', output)
            self.assert_safe(output)

    async def test_check_malformed_case_reference_never_means_ready(self):
        for side in ('search', 'detail'):
            self.requests.clear()
            payloads = valid_payloads()
            case = payloads[1]['data']['datas'][0] if side == 'search' else payloads[2]['data']['data']
            case['cpws_al_ajzh'] = 7
            self.transport(payloads)
            output = await self.server.check_token()
            self.assertNotIn('网站实际可用', output)
            self.assertIn('详情', output)
            self.assertIn('格式', output)
            self.assert_safe(output)

    async def test_check_credential_change_during_verification_is_not_ready(self):
        for changed_stage in range(3):
            write_credentials(self.path, SECRET_A)
            self.requests.clear()
            self.transport(valid_payloads(), after_response=lambda index:
                           write_credentials(self.path, SECRET_B) if index == changed_stage else None)
            output = await self.server.check_token()
            self.assertNotIn('网站实际可用', output)
            self.assertIn('验证期间', output)
            self.assertIn('已变化', output)
            self.assertEqual(len(self.requests), changed_stage + 1)
            self.assert_safe(output)

    async def test_check_a_to_b_to_a_never_combines_different_credentials(self):
        def rotate(index):
            if index == 0:
                write_credentials(self.path, SECRET_B)
            elif index == 2:
                write_credentials(self.path, SECRET_A)

        self.transport(valid_payloads(), after_response=rotate)
        output = await self.server.check_token()
        self.assertNotIn('网站实际可用', output)
        self.assertIn('验证期间', output)
        self.assertIn('已变化', output)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0].headers['faxin-cpws-al-token'], SECRET_A)
        self.assert_safe(output)

    async def test_check_boundary_race_is_checked_on_actual_request_capture(self):
        original_post = self.client.post

        async def rotate_before_capture(path, body=None, **kwargs):
            if path == 'cpwsAl/search':
                write_credentials(self.path, SECRET_B)
            return await original_post(path, body, **kwargs)

        self.transport(valid_payloads(), after_response=lambda index:
                       write_credentials(self.path, SECRET_A) if index == 2 else None)
        with patch.object(self.client, 'post', side_effect=rotate_before_capture):
            output = await self.server.check_token()
        self.assertNotIn('网站实际可用', output)
        self.assertIn('检索', output)
        self.assertIn('已变化', output)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0].headers['faxin-cpws-al-token'], SECRET_A)
        self.assert_safe(output)

    async def test_check_false_api_code_never_means_ready(self):
        for failed_stage in range(3):
            self.requests.clear()
            payloads = valid_payloads()
            payloads[failed_stage]['code'] = False
            self.transport(payloads)
            output = await self.server.check_token()
            self.assertNotIn('网站实际可用', output)
            self.assertIn(('账号接口', '检索', '详情')[failed_stage], output)
            self.assertEqual(len(self.requests), failed_stage + 1)

    async def test_check_network_and_auth_failures_stop_at_stage(self):
        for failed_stage in range(3):
            for failure in (httpx.ReadTimeout(SECRET_A),
                            {'code': 401, 'msg': SECRET_A},
                            httpx.Response(200, content=SECRET_A)):
                write_credentials(self.path, SECRET_A)
                self.client = make_client(self.client_module, self.path)
                self.server.client = self.client
                self.requests.clear()
                payloads = valid_payloads()
                payloads[failed_stage] = failure
                self.transport(payloads)
                with self.subTest(stage=failed_stage, failure=type(failure).__name__):
                    output = await self.server.check_token()
                    self.assertNotIn('网站实际可用', output)
                    self.assertIn(('账号接口', '检索', '详情')[failed_stage], output)
                    self.assertEqual(len(self.requests), failed_stage + 1)
                    self.assert_safe(output)

    async def test_compatibility_set_token_checks_separately_and_never_claims_file_ready(self):
        original = self.client.token
        explicit = []

        async def verify(token):
            explicit.append(token)
            return {'code': 0, 'data': {'userId': SECRET_A, 'phone': SECRET_B}}

        with patch.object(self.client, 'verify_token', side_effect=verify):
            output = await self.server.set_token(self.server.SetTokenInput(token=SECRET_B))
        self.assertEqual(explicit, [SECRET_B])
        self.assertEqual(self.client.token, original)
        self.assertNotIn('网站实际可用', output)
        self.assertIn('临时', output)
        self.assertIn('本地', output)
        self.assert_safe(output)

    async def test_compatibility_failure_does_not_clear_file_and_is_safe(self):
        original = self.path.read_text()
        with patch.object(self.client, 'verify_token', side_effect=RuntimeError(SECRET_A)):
            output = await self.server.set_token(self.server.SetTokenInput(token=SECRET_B))
        self.assertEqual(self.path.read_text(), original)
        self.assert_safe(output)

    async def test_statistics_optional_branches_propagate_auth_and_file_failure(self):
        for branch in (1, 2):
            for failure in ('auth', 'file'):
                write_credentials(self.path, SECRET_A)
                self.client = make_client(self.client_module, self.path)
                self.server.client = self.client
                self.requests.clear()
                payloads = [{'code': 0, 'data': []}] * 3
                payloads[branch] = {'code': 401, 'msg': SECRET_A}
                remove = lambda i: self.path.unlink() if failure == 'file' and i == branch - 1 else None
                self.transport(payloads, after_response=remove)
                output = await self.server.get_statistics(self.server.StatisticsInput(keyword='买卖合同'))
                self.assertNotIn('## 案例库统计', output)
                self.assertIn('认证' if failure == 'auth' else '本地', output)
                self.assertEqual(len(self.requests), branch + (failure == 'auth'))
                self.assert_safe(output)

    async def test_batch_export_halts_on_auth_or_file_failure_with_completed_count(self):
        # Mock filesystem writes/formatter: no actual export or ingestion occurs.
        sys.path.insert(0, str(UPSTREAM / 'scripts'))
        try:
            import export_formatter
        finally:
            sys.path.remove(str(UPSTREAM / 'scripts'))
        for failure in ('auth', 'file'):
            write_credentials(self.path)
            self.client = make_client(self.client_module, self.path)
            self.server.client = self.client
            self.requests.clear()
            payloads = [
                {'code': 0, 'data': {'datas': [{'cpws_al_id': str(i)} for i in range(3)], 'totalCount': 3}},
                {'code': 0, 'data': {'data': {'cpws_al_cpyz': '公开文本'}}},
                {'code': 401, 'msg': SECRET_A},
            ]
            self.transport(payloads, after_response=lambda i:
                           self.path.unlink() if failure == 'file' and i == 1 else None)
            with patch.object(export_formatter, 'format_obsidian_case',
                              return_value=('IP类型: "综合"\n公开文本', 'case.md', 'synthetic')), \
                    patch('builtins.open', unittest.mock.mock_open()) as writes, \
                    patch('os.path.exists', return_value=False), patch('os.makedirs'), \
                    patch('asyncio.sleep', new=unittest.mock.AsyncMock()):
                output = await self.server.export_case(self.server.ExportInput(
                    keyword='买卖合同', target_dir='/synthetic/export'))
            self.assertIn('已完成: 1 条', output)
            self.assertIn('停止', output)
            self.assertNotIn('导出完成', output)
            self.assertEqual(writes.call_count, 1)
            self.assertEqual(len(self.requests), 3 if failure == 'auth' else 2)
            self.assert_safe(output)

    async def test_normal_search_does_not_claim_full_readiness(self):
        self.transport([{'code': 0, 'data': {'datas': [], 'totalCount': 0}}])
        output = await self.server.search(self.server.SearchInput(keyword='买卖合同'))
        self.assertNotIn('网站实际可用', output)


if __name__ == '__main__':
    unittest.main()
