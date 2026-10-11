"""Confirm robots response format before using the standard-library rules parser."""
from urllib.robotparser import RobotFileParser


def confirmed_robots(response):
    parser = RobotFileParser()
    if response.status in (404, 410):
        parser.parse([])
        return parser
    if response.status != 200:
        raise ValueError(f'robots未确认，状态{response.status}')
    headers = {key.lower(): value for key, value in getattr(response, 'headers', {}).items()}
    content_type = headers.get('content-type', '').split(';', 1)[0].strip().lower()
    if content_type and content_type != 'text/plain':
        raise ValueError('robots未确认，响应不是纯文本')
    try:
        text = response.body.decode('utf-8-sig')
    except UnicodeDecodeError as error:
        raise ValueError('robots未确认，响应不是有效UTF-8') from error
    if '\ufffd' in text or any((ord(char) < 32 and char not in '\t\r\n')
                               or 127 <= ord(char) <= 159 for char in text):
        raise ValueError('robots未确认，响应含替换字符或二进制控制字符')
    for raw in text.splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        name, separator, value = line.partition(':')
        name = name.strip().lower()
        if (not separator or '<' in line or '>' in line
                or name not in ('user-agent', 'allow', 'disallow', 'sitemap', 'crawl-delay', 'request-rate')
                or (name == 'user-agent' and not value.strip())):
            raise ValueError('robots未确认，响应含无法确认的规则行')
    parser.parse(text.splitlines())
    entries = parser.entries + ([parser.default_entry] if parser.default_entry else [])
    if not any(entry.rulelines for entry in entries):
        raise ValueError('robots未确认，未解析到有效访问规则')
    return parser
