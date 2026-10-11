"""Both acquisition gates must confirm robots before fetching any document."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from scrapling.engines.toolbelt.custom import Response

from jilin_sources import PublicReader
from scripts.probe_sources import probe_source


class RobotsValidationTests(unittest.TestCase):
    url = 'https://xxgk.jl.gov.cn/szf/gzk/example.html'
    robots_url = 'https://xxgk.jl.gov.cn/robots.txt'

    def check_gates(self, body, *, allowed=False, status=200, headers=None, denied=False):
        for entry in ('probe', 'jilin'):
            with self.subTest(entry=entry), tempfile.TemporaryDirectory() as tmp:
                calls, cache = [], {}
                def fetch(url):
                    calls.append(url)
                    if url == self.robots_url:
                        return SimpleNamespace(status=status, body=body, headers=headers or {})
                    return Response(url=url, content=('<title>Fixture</title><main>' +
                        'Public document. ' * 100 + '</main>').encode(), status=200,
                        reason='fixture', cookies={}, headers={}, request_headers={})
                if entry == 'probe':
                    row = probe_source({'source_id':'fixture', 'url':self.url, 'region':'CN-JL',
                        'fallback_urls':['https://fallback.invalid/law']}, directory=Path(tmp),
                        store=None, fetch=fetch, delay=0, robots_cache=cache)
                    outcome = row['state']
                else:
                    reader = PublicReader(fetch=fetch, delay=0)
                    cache = reader.robots
                    try:
                        reader.get(self.url)
                        outcome = 'quarantined'
                    except ValueError as error:
                        outcome = str(error)
                self.assertEqual(calls, [self.robots_url, self.url] if allowed else [self.robots_url])
                if allowed:
                    self.assertEqual(outcome, 'quarantined')
                    self.assertTrue(cache)
                elif denied:
                    self.assertEqual(outcome, 'robots_disallowed' if entry == 'probe' else 'robots禁止读取')
                else:
                    self.assertFalse(cache, 'Unconfirmed robots must never be cached as permission')
                    if entry == 'probe':
                        self.assertEqual(outcome, 'manual_required')
                        self.assertIn('robots未确认', row['error'])
                        self.assertEqual(len(row['attempts']), 1)
                    else:
                        self.assertIn('robots未确认', outcome)

    def test_real_court_soft404_blocks_both_entries_before_document(self):
        body = (Path(__file__).parent / 'fixtures/robots-court-soft404.html').read_bytes()
        self.assertEqual(len(body), 3144)
        self.check_gates(body, headers={'content-type':'text/html; charset=utf-8'})

    def test_html_is_blocked_even_with_plain_or_missing_content_type(self):
        for headers in ({}, {'Content-Type':'text/plain'}):
            with self.subTest(headers=headers):
                self.check_gates(b'<html><title>Error</title></html>', headers=headers)

    def test_non_text_mime_cannot_override_valid_looking_directives(self):
        for content_type in ('text/html', 'application/json', 'application/octet-stream'):
            with self.subTest(content_type=content_type):
                self.check_gates(b'User-agent: *\nAllow: /', headers={'Content-Type':content_type})

    def test_error_json_and_binary_are_not_empty_rules(self):
        for body in (b'Service unavailable', b'Error: unavailable', b'{"error":"failed"}',
                     b'\x00\x01', b'User-agent: *\nAllow: /\x00'):
            with self.subTest(body=body):
                self.check_gates(body)

    def test_invalid_utf8_and_replacement_characters_fail_closed(self):
        for body in (b'User-agent: *\nDisallow: /\xff',
                     'User-agent: *\nAllow: /\n# \ufffd'.encode()):
            with self.subTest(body=body):
                self.check_gates(body)

    def test_empty_comments_and_unusable_directives_remain_unconfirmed(self):
        for body in (b'', b'# Nothing confirmed', b'User-agent: *', b'Disallow: /',
                     b'User-agent: *\nDisallow /', b'User-agent: \nAllow: /'):
            with self.subTest(body=body):
                self.check_gates(body)

    def test_valid_allow_and_empty_disallow_are_preserved(self):
        for body in (b'User-agent: *\nAllow: /', b'User-agent: *\nDisallow:',
                     b'User-agent: OtherBot\nDisallow: /'):
            with self.subTest(body=body):
                self.check_gates(body, allowed=True, headers={'content-type':'text/plain; charset=utf-8'})

    def test_bom_comments_case_and_line_endings_preserve_disallow(self):
        self.check_gates('\ufeff# 注释\r\nUsEr-AgEnT: * # all\r\nDisallow: /\r\n'.encode(), denied=True)

    def test_bom_comments_preserve_allow(self):
        self.check_gates('\ufeff# 注释\nUser-agent: *\nAllow: / # public\n'.encode(), allowed=True)

    def test_confirmed_404_and_410_preserve_absence_semantics(self):
        for status in (404, 410):
            with self.subTest(status=status):
                self.check_gates(b'<html>Not found</html>', status=status, allowed=True,
                                 headers={'content-type':'text/html'})

    def test_forbidden_throttled_redirect_and_server_errors_stop(self):
        for status in (301, 302, 401, 403, 429, 500, 503):
            with self.subTest(status=status):
                self.check_gates(b'User-agent: *\nAllow: /', status=status)


if __name__ == '__main__':
    unittest.main()
