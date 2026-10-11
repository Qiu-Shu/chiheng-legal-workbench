"""Credential recovery checks: real client, synthetic files, no live requests."""

import asyncio
import base64
import contextlib
import importlib.util
import inspect
import io
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / 'vendor/treasury/sources/legal-tools/人民法院案例库MCP'
DEPS = Path(os.environ.get('CHIHENG_TEST_SDK1_SITE', str(
    ROOT / '.venv-mcp1' / ('Lib/site-packages' if os.name == 'nt' else
                          f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages'))))
import httpx

sys.path.insert(0, str(DEPS))
try:
    import dotenv
finally:
    sys.path.remove(str(DEPS))


SECRET_A = 'synthetic-secret-A-never-display'
SECRET_B = 'synthetic-secret-B-never-display'


def write_credentials(path, token=SECRET_A, text=None):
    if os.name == 'nt':
        import windows_private
        windows_private.private_directory(path.parent, create=True)
        fd = windows_private.open_file(path, private=True, writable=True, create=True)
        os.close(fd)
    else:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(text if text is not None else f'RMFYALK_TOKEN={token}\n',
                    encoding='utf-8')
    path.chmod(0o600)


def load_client(startup_file):
    """Redirect the unique startup access path before loading the real vendor."""
    source = UPSTREAM / 'scripts/client.py'
    spec = importlib.util.spec_from_file_location('isolated_rmfyalk_client', source)
    module = importlib.util.module_from_spec(spec)
    with patch('windows_case_access.access_path', return_value=startup_file):
        spec.loader.exec_module(module)
    return module


def make_client(module, path):
    # The legacy branch permits an assertion-based RED before the API is added.
    if 'credential_path' in inspect.signature(module.RmfyalkClient).parameters:
        return module.RmfyalkClient(credential_path=path)
    return module.RmfyalkClient()


def jwt(payload):
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
    return 'synthetic.' + encoded + '.signature'


class CredentialFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'private' / 'case-access.env'
        if os.name != 'nt':
            self.path.parent.mkdir(mode=0o700)
        write_credentials(self.path, SECRET_B)
        self.module = load_client(self.path)

    def client(self):
        return make_client(self.module, self.path)

    def assert_credential_error(self, text, kind):
        write_credentials(self.path, text=text)
        with self.assertRaises(self.module.CredentialError) as caught:
            self.client().token
        self.assertEqual(caught.exception.kind, kind)
        self.assertNotIn(SECRET_A, str(caught.exception))

    def test_file_token_overrides_environment_and_refreshes(self):
        with patch.dict(os.environ, {'RMFYALK_TOKEN': SECRET_A}):
            client = self.client()
            self.assertEqual(client.token, SECRET_B)
            write_credentials(self.path, SECRET_A)
            self.assertEqual(client.token, SECRET_A)

    def test_same_size_mtime_replacement_and_atomic_replacement(self):
        client = self.client()
        self.assertEqual(client.token, SECRET_B)
        saved = self.path.stat()
        write_credentials(self.path, SECRET_A)
        os.utime(self.path, ns=(saved.st_atime_ns, saved.st_mtime_ns))
        self.assertEqual(client.token, SECRET_A)
        replacement = self.path.with_name('replacement')
        write_credentials(replacement, SECRET_B)
        os.replace(replacement, self.path)
        self.assertEqual(client.token, SECRET_B)

    def test_missing_empty_removed_and_broken_files_have_no_cached_fallback(self):
        client = self.client()
        self.assertEqual(client.token, SECRET_B)
        self.path.unlink()
        with self.assertRaises(self.module.CredentialError) as missing:
            client.token
        self.assertEqual(missing.exception.kind, 'missing')
        for text in ('', '# only a comment\n', 'RMFYALK_TOKEN=\n'):
            write_credentials(self.path, text=text)
            with self.assertRaises(self.module.CredentialError) as empty:
                client.token
            self.assertEqual(empty.exception.kind, 'empty')
        write_credentials(self.path, text='RMFYALK_TOKEN="unclosed\n')
        with self.assertRaises(self.module.CredentialError):
            client.token

    def test_dotenv_quotes_comments_and_interpolation_disabled(self):
        for text, expected in (
            ('RMFYALK_TOKEN="quoted-token" # comment\n', 'quoted-token'),
            ("export RMFYALK_TOKEN='single-token'\n", 'single-token'),
            ('RMFYALK_TOKEN=${SYNTHETIC_VARIABLE}\n', '${SYNTHETIC_VARIABLE}'),
            ('OTHER="other value"\nRMFYALK_TOKEN=abc # comment\n', 'abc'),
        ):
            with self.subTest(text=text), patch.dict(os.environ, {'SYNTHETIC_VARIABLE': SECRET_A}):
                write_credentials(self.path, text=text)
                self.assertEqual(self.client().token, expected)

    def test_duplicate_malformed_target_and_controls_are_rejected(self):
        cases = (
            ('RMFYALK_TOKEN=a\nRMFYALK_TOKEN=b\n', 'duplicate'),
            ('export RMFYALK_TOKEN=a\nRMFYALK_TOKEN=b\n', 'duplicate'),
            ('RMFYALK_TOKEN\n', 'malformed'),
            ('RMFYALK_TOKEN = "unclosed\n', 'malformed'),
            ('RMFYALK_TOKEN: a\n', 'malformed'),
            ('RMFYALK_TOKEN=a\x00b\n', 'malformed'),
            ('RMFYALK_TOKEN="a\\nb"\n', 'malformed'),
            ('RMFYALK_TOKEN="a\\tb"\n', 'malformed'),
            ('RMFYALK_TOKEN=a\x7fb\n', 'malformed'),
        )
        for text, kind in cases:
            with self.subTest(kind=kind, text=repr(text)):
                self.assert_credential_error(text, kind)

    def test_malformed_target_that_dotenv_reads_as_another_key_is_rejected(self):
        for text in ('RMFYALK_TOKEN:=abc\n', "'RMFYALK_TOKEN:'=abc\n", '"RMFYALK_TOKEN"=abc\n'):
            with self.subTest(text=text):
                self.assert_credential_error(text, 'malformed')

    def test_open_permission_failure_is_classified_without_file_contents(self):
        open_target = 'windows_private.open_file' if os.name == 'nt' else 'os.open'
        with patch(open_target, side_effect=PermissionError(SECRET_A)):
            with self.assertRaises(self.module.CredentialError) as caught:
                self.client().token
        self.assertEqual(caught.exception.kind, 'unreadable')
        self.assertNotIn(SECRET_A, str(caught.exception))

    @unittest.skipIf(os.name == 'nt', 'POSIX FIFO/mode/owner; native Windows ACL suite is separate')
    def test_symlink_fifo_directory_permissions_owner_and_size_are_rejected(self):
        other = self.path.with_name('target')
        write_credentials(other)
        self.path.unlink()
        self.path.symlink_to(other)
        with self.assertRaises(self.module.CredentialError) as caught:
            self.client().token
        self.assertEqual(caught.exception.kind, 'unsafe')
        self.path.unlink()
        os.mkfifo(self.path, 0o600)
        with self.assertRaises(self.module.CredentialError) as caught:
            self.client().token
        self.assertEqual(caught.exception.kind, 'unsafe')
        self.path.unlink()
        self.path.mkdir()
        with self.assertRaises(self.module.CredentialError):
            self.client().token
        self.path.rmdir()
        for mode, kind in ((0o644, 'unsafe'), (0o660, 'unsafe'), (0o200, 'unreadable')):
            write_credentials(self.path)
            self.path.chmod(mode)
            with self.subTest(mode=mode), self.assertRaises(self.module.CredentialError) as caught:
                self.client().token
            self.assertEqual(caught.exception.kind, kind)
        write_credentials(self.path)
        with patch.object(self.module.os, 'getuid', return_value=os.getuid() + 1):
            with self.assertRaises(self.module.CredentialError) as caught:
                self.client().token
            self.assertEqual(caught.exception.kind, 'unsafe')
        write_credentials(self.path, text='RMFYALK_TOKEN=' + 'x' * 65536)
        with self.assertRaises(self.module.CredentialError) as caught:
            self.client().token
        self.assertEqual(caught.exception.kind, 'oversize')

    @unittest.skipIf(os.name == 'nt', 'POSIX open flags; native Windows handle checks are separate')
    def test_reader_uses_nofollow_open_and_fstat_not_path_stat(self):
        calls = []
        real_open = self.module.os.open

        def observed_open(path, flags, *args, **kwargs):
            calls.append(flags)
            return real_open(path, flags, *args, **kwargs)

        with patch.object(self.module.os, 'open', side_effect=observed_open), \
                patch.object(Path, 'stat', side_effect=AssertionError('unsafe stat before open')):
            self.assertEqual(self.client().token, SECRET_B)
        self.assertTrue(calls)
        self.assertTrue(all(flags & os.O_NOFOLLOW for flags in calls))
        self.assertTrue(all(flags & os.O_NONBLOCK for flags in calls))

    def test_startup_does_not_inject_secrets_and_preserves_export_dir(self):
        write_credentials(self.path, text=f'RMFYALK_TOKEN={SECRET_B}\nEXPORT_DIR=/synthetic/export\n')
        with patch.dict(os.environ, {}, clear=True):
            module = load_client(self.path)
            self.assertNotIn('RMFYALK_TOKEN', os.environ)
            self.assertEqual(module.DEFAULT_EXPORT_DIR, '/synthetic/export')
        with patch.dict(os.environ, {'EXPORT_DIR': '/already/configured'}):
            module = load_client(self.path)
            self.assertEqual(module.DEFAULT_EXPORT_DIR, '/already/configured')

    def test_startup_export_setting_survives_invalid_token_binding(self):
        for auth in ('RMFYALK_TOKEN=a\nRMFYALK_TOKEN=b\n', 'RMFYALK_TOKEN:=broken\n'):
            write_credentials(self.path, text=auth + 'EXPORT_DIR=/synthetic/export\n')
            with self.subTest(auth=auth), patch.dict(os.environ, {}, clear=True):
                module = load_client(self.path)
                self.assertEqual(module.DEFAULT_EXPORT_DIR, '/synthetic/export')
            with self.assertRaises(module.CredentialError):
                make_client(module, self.path).token

    def test_only_export_path_expands_variables_and_empty_env_override_wins(self):
        write_credentials(self.path, text='RMFYALK_TOKEN=${SYNTHETIC_VARIABLE}\n'
                          'EXPORT_DIR=${SYNTHETIC_EXPORT_BASE}/export\n')
        with patch.dict(os.environ, {'SYNTHETIC_VARIABLE': SECRET_A,
                                    'SYNTHETIC_EXPORT_BASE': '/synthetic/base'}, clear=True):
            module = load_client(self.path)
            self.assertEqual(module.DEFAULT_EXPORT_DIR, '/synthetic/base/export')
            self.assertEqual(make_client(module, self.path).token, '${SYNTHETIC_VARIABLE}')
            self.assertNotIn('RMFYALK_TOKEN', os.environ)
        with patch.dict(os.environ, {'EXPORT_DIR': ''}, clear=True):
            self.assertEqual(load_client(self.path).DEFAULT_EXPORT_DIR, '')
        write_credentials(self.path, text=f'RMFYALK_TOKEN={SECRET_A}\nEXPORT_DIR=${{RMFYALK_TOKEN}}/export\n')
        with patch.dict(os.environ, {'RMFYALK_TOKEN': SECRET_B}, clear=True):
            self.assertNotIn(SECRET_A, load_client(self.path).DEFAULT_EXPORT_DIR)
            self.assertNotIn(SECRET_B, load_client(self.path).DEFAULT_EXPORT_DIR)

    def test_startup_export_path_preserves_ordered_dependency_expansion(self):
        write_credentials(self.path, text='RMFYALK_TOKEN=${SYNTHETIC_VARIABLE}\n'
                          'BASE=${SYNTHETIC_EXPORT_ROOT}/vendor\nEXPORT_DIR=${BASE}/export\n')
        with patch.dict(os.environ, {'SYNTHETIC_EXPORT_ROOT': '/synthetic'}, clear=True):
            self.assertEqual(load_client(self.path).DEFAULT_EXPORT_DIR, '/synthetic/vendor/export')
        with patch.dict(os.environ, {'SYNTHETIC_EXPORT_ROOT': '/synthetic',
                                    'BASE': '/environment/override'}, clear=True):
            self.assertEqual(load_client(self.path).DEFAULT_EXPORT_DIR, '/environment/override/export')
        write_credentials(self.path, text='EXPORT_DIR=${AFTER}/export\nAFTER=/too/late\n')
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(load_client(self.path).DEFAULT_EXPORT_DIR, '/export')

    def test_startup_export_preserves_repeated_non_auth_binding_order(self):
        cases = (
            ('BASE=/first\nEXPORT_DIR=${BASE}/export\nBASE=/second\n', '/first/export'),
            ('EXPORT_DIR=${BASE}/early\nBASE=/introduced\nEXPORT_DIR=${BASE}/later\n',
             '/introduced/later'),
            ('BASE=/first\nEXPORT_DIR=${BASE}/early\nBASE=/second\nEXPORT_DIR=${BASE}/later\n',
             '/second/later'),
        )
        for settings, expected in cases:
            write_credentials(self.path, text='RMFYALK_TOKEN=${SYNTHETIC_VARIABLE}\n' + settings)
            with self.subTest(settings=settings), patch.dict(os.environ, {}, clear=True):
                module = load_client(self.path)
                self.assertEqual(module.DEFAULT_EXPORT_DIR, expected)
                self.assertEqual(make_client(module, self.path).token, '${SYNTHETIC_VARIABLE}')

    def test_default_path_is_redirected_private_file_and_headers_have_no_auth(self):
        client = self.module.RmfyalkClient()
        self.assertEqual(Path(client.credential_path), self.path)
        recorded = []

        def fake_client(**kwargs):
            recorded.append(kwargs)
            return object()

        with patch.object(self.module.httpx, 'AsyncClient', side_effect=fake_client):
            client._get_client()
        self.assertIs(recorded[0]['verify'], True)
        self.assertEqual(recorded[0]['base_url'], self.module.BASE_URL)
        self.assertNotIn('faxin-cpws-al-token', recorded[0]['headers'])


class RequestTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'private' / 'case-access.env'
        write_credentials(self.path)
        self.module = load_client(self.path)
        self.client = make_client(self.module, self.path)
        self.requests = []
        self.clients = []

    async def asyncTearDown(self):
        for client in self.clients:
            await client.aclose()

    def transport(self, handler):
        async def record(request):
            self.requests.append(request)
            response = handler(request)
            if inspect.isawaitable(response):
                response = await response
            return response

        c = httpx.AsyncClient(base_url=self.module.BASE_URL,
                              transport=httpx.MockTransport(record))
        self.clients.append(c)
        self.client._client = c
        return c

    async def test_each_request_uses_fresh_file_token_and_encoded_get_params(self):
        c = self.transport(lambda request: httpx.Response(200, json={'code': 0, 'data': {}}))
        await self.client.post('one')
        write_credentials(self.path, SECRET_B)
        await self.client.get('common/getXmlToTree', params={'nodeId': 'A&B 中文'})
        self.assertEqual([r.headers.get('faxin-cpws-al-token') for r in self.requests],
                         [SECRET_A, SECRET_B])
        self.assertEqual(self.requests[1].url.params['nodeId'], 'A&B 中文')
        self.assertNotIn('faxin-cpws-al-token', c.headers)

    async def test_expected_token_guard_and_request_share_one_actual_capture(self):
        self.transport(lambda request: httpx.Response(200, json={'code': 0}))
        actual_reader = self.module.RmfyalkClient.token.fget
        reads = []

        def rotate_after_read(instance):
            token = actual_reader(instance)
            reads.append(token)
            write_credentials(self.path, SECRET_B)
            return token

        with patch.object(self.module.RmfyalkClient, 'token', property(rotate_after_read)):
            await self.client.post('one', expected_token=SECRET_A)
        self.assertEqual(reads, [SECRET_A])
        self.assertEqual(self.requests[0].headers['faxin-cpws-al-token'], SECRET_A)
        with self.assertRaises(self.module.CredentialError) as caught:
            await self.client.post('two', expected_token=SECRET_A)
        self.assertEqual(caught.exception.kind, 'changed')
        self.assertEqual(len(self.requests), 1)

    async def test_http_and_business_401_block_generation_until_different_token(self):
        for status, code in ((401, 0), (200, 401)):
            with self.subTest(status=status, code=code):
                self.client = make_client(self.module, self.path)
                write_credentials(self.path, SECRET_A)
                self.requests.clear()
                self.transport(lambda request: httpx.Response(status, json={'code': code, 'msg': SECRET_A}))
                with self.assertRaises(self.module.TokenExpiredError):
                    await self.client.post('one')
                for text in (f'RMFYALK_TOKEN={SECRET_A}\n', f'# edited\nRMFYALK_TOKEN="{SECRET_A}"\n'):
                    write_credentials(self.path, text=text)
                    with self.assertRaises(self.module.TokenExpiredError):
                        await self.client.post('two')
                self.assertEqual(len(self.requests), 1)
                write_credentials(self.path, SECRET_B)
                self.transport(lambda request: httpx.Response(200, json={'code': 0}))
                await self.client.post('three')
                self.assertEqual(self.requests[-1].headers['faxin-cpws-al-token'], SECRET_B)

    async def test_numeric_jwt_exp_blocks_locally_other_exp_values_use_website(self):
        self.transport(lambda request: httpx.Response(200, json={'code': 0}))
        for exp in (int(time.time()) - 60, str(int(time.time()) - 60)):
            write_credentials(self.path, jwt({'exp': exp, 'userId': SECRET_A}))
            with self.assertRaises(self.module.TokenExpiredError) as caught:
                await self.client.post('one')
            self.assertNotIn(SECRET_A, str(caught.exception))
        self.assertEqual(len(self.requests), 0)
        for exp in (None, 'not-a-number', True, {'bad': 1}):
            write_credentials(self.path, jwt({'exp': exp}))
            await self.client.post('one')
        self.assertEqual(len(self.requests), 4)

    async def test_late_old_401_does_not_poison_replacement_or_close_inflight_client(self):
        started = asyncio.Event()
        release = asyncio.Event()

        async def handler(request):
            if request.headers['faxin-cpws-al-token'] == SECRET_A:
                started.set()
                await release.wait()
                return httpx.Response(401, json={'code': 401})
            return httpx.Response(200, json={'code': 0})

        c = self.transport(handler)
        old = asyncio.create_task(self.client.post('old'))
        await asyncio.wait_for(started.wait(), 1)
        write_credentials(self.path, SECRET_B)
        await self.client.post('new')
        release.set()
        with self.assertRaises(self.module.TokenExpiredError):
            await old
        await self.client.post('still-new')
        self.assertFalse(c.is_closed)
        self.assertEqual([r.headers['faxin-cpws-al-token'] for r in self.requests],
                         [SECRET_A, SECRET_B, SECRET_B])

    async def test_failure_categories_are_safe_do_not_expire_or_alter_file(self):
        cases = (
            (lambda r: httpx.Response(403, json={'msg': SECRET_A}), 'forbidden'),
            (lambda r: httpx.Response(500, json={'msg': SECRET_A}), 'http'),
            (lambda r: httpx.Response(200, content=SECRET_A), 'response'),
            (lambda r: httpx.Response(200, json=['unexpected', SECRET_A]), 'response'),
            (lambda r: httpx.Response(200, json={'code': 5, 'msg': SECRET_A}), 'business'),
        )
        for handler, kind in cases:
            with self.subTest(kind=kind):
                self.transport(handler)
                with self.assertRaises(self.module.ApiError) as caught:
                    await self.client.post('one')
                self.assertEqual(caught.exception.kind, kind)
                self.assertNotIn(SECRET_A, str(caught.exception))
                self.assertEqual(self.client.token, SECRET_A)
        for error, kind in ((httpx.ReadTimeout(SECRET_A), 'timeout'),
                            (httpx.ConnectError('SSL ' + SECRET_A), 'network')):
            def fail(request):
                raise error
            self.transport(fail)
            with self.assertRaises(self.module.ApiError) as caught:
                await self.client.post('one')
            self.assertEqual(caught.exception.kind, kind)
            self.assertNotIn(SECRET_A, str(caught.exception))
        self.assertEqual(self.path.read_text(), f'RMFYALK_TOKEN={SECRET_A}\n')

    async def test_false_missing_or_noninteger_api_codes_cannot_mean_success(self):
        for code in (False, True, None, '0', 0.0):
            self.transport(lambda r: httpx.Response(200, json={'code': code, 'data': {'ok': True}}))
            with self.subTest(code=code), self.assertRaises(self.module.ApiError) as caught:
                await self.client.post('one')
            self.assertEqual(caught.exception.kind, 'response')
        self.assertEqual(self.client.token, SECRET_A)

    async def test_bad_file_prevents_network_even_after_success(self):
        self.transport(lambda request: httpx.Response(200, json={'code': 0}))
        await self.client.post('one')
        self.path.unlink()
        with self.assertRaises(self.module.CredentialError):
            await self.client.post('two')
        self.assertEqual(len(self.requests), 1)

    async def test_temporary_verify_never_changes_source_or_normal_auth(self):
        main = self.transport(lambda request: httpx.Response(200, json={'code': 0}))
        temporary_requests = []
        real_async_client = httpx.AsyncClient

        def separate_client(**kwargs):
            self.assertIs(kwargs.get('verify'), True)
            kwargs['transport'] = httpx.MockTransport(
                lambda r: temporary_requests.append(r) or httpx.Response(
                    200, json={'code': 0, 'data': {'userId': SECRET_B}}))
            return real_async_client(**kwargs)

        with patch.object(self.module.httpx, 'AsyncClient', side_effect=separate_client):
            await self.client.verify_token(SECRET_B)
        self.assertEqual(temporary_requests[0].headers['faxin-cpws-al-token'], SECRET_B)
        self.assertEqual(self.client.token, SECRET_A)
        self.assertIs(self.client._client, main)
        self.assertNotIn('faxin-cpws-al-token', main.headers)
        self.assertEqual(self.path.read_text(), f'RMFYALK_TOKEN={SECRET_A}\n')

    async def test_temporary_failure_never_blocks_normal_generation(self):
        self.transport(lambda r: httpx.Response(200, json={'code': 0}))
        real_async_client = httpx.AsyncClient

        def separate_client(**kwargs):
            kwargs['transport'] = httpx.MockTransport(lambda r: httpx.Response(401))
            return real_async_client(**kwargs)

        with patch.object(self.module.httpx, 'AsyncClient', side_effect=separate_client):
            with self.assertRaises(self.module.TokenExpiredError):
                await self.client.verify_token(SECRET_A)
        await self.client.post('normal')
        self.assertEqual(len(self.requests), 1)

    async def test_temporary_input_validation_does_not_read_file_or_make_request(self):
        self.path.unlink()
        with patch.object(self.module.httpx, 'AsyncClient', side_effect=AssertionError('unexpected network')):
            for token in ('', 'token\n', ' token', 'a\x00b'):
                with self.subTest(token=repr(token)), self.assertRaises(self.module.CredentialError):
                    await self.client.verify_token(token)

    async def test_errors_and_default_logging_never_print_synthetic_secret(self):
        stream = io.StringIO()
        root = logging.getLogger()
        handler = logging.StreamHandler(stream)
        root.addHandler(handler)
        old_level = root.level
        root.setLevel(logging.DEBUG)
        self.addCleanup(root.removeHandler, handler)
        self.addCleanup(root.setLevel, old_level)
        self.transport(lambda r: httpx.Response(200, json={'code': 401, 'msg': SECRET_A}))
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            with self.assertRaises(self.module.TokenExpiredError) as caught:
                await self.client.post('normal')
            stream.write(str(caught.exception))
        self.assertNotIn(SECRET_A, stream.getvalue())


if __name__ == '__main__':
    unittest.main()
