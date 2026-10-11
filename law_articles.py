"""Conservative plain-text article boundaries, not a legal completeness decision."""
import hashlib
import re

NUMERALS = '零〇一二三四五六七八九十百千万两'
HEADING = re.compile(
    rf'^[ \t\u3000]*(?:(?P<article>第[{NUMERALS}]+[ \t\u3000]*条(?:之[{NUMERALS}]+)?)'
    rf'|第[{NUMERALS}]+(?:分编|编|章|节|目)(?=[ \t\u3000\r\n]|$))', re.MULTILINE)


def split_articles(text):
    """Return exact character spans; reject duplicate labels rather than guess past TOCs."""
    headings = list(HEADING.finditer(text))
    articles, seen = [], set()
    for index, heading in enumerate(headings):
        boundary = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        label = heading.group('article')
        if label is None:
            lines = text[heading.end():boundary].splitlines()
            if articles and any(line.strip() for line in lines[1:]):
                raise ValueError('结构标题后存在未归属正文，可能是引述、附件或换行标题，需人工定位')
            continue
        label = ''.join(label.split())
        if label in seen:
            raise ValueError(f'重复条号{label}：可能混入目录或多份文件，需人工定位正文')
        seen.add(label)
        start = heading.start('article')
        body = text[start:boundary].rstrip()
        if not text[heading.end():boundary].strip():
            raise ValueError(f'{label}空正文，不能构造完整条款')
        articles.append({'article': label, 'start': start, 'end': start + len(body),
                         'article_sha256': hashlib.sha256(body.encode()).hexdigest()})
    if not articles:
        raise ValueError('未识别到支持的条号，不能确认该文本有可分条正文')
    return articles
