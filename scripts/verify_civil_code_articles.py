"""Reproducible mechanical acceptance of one pinned official sample, not legal review."""
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from law_articles import split_articles
from legal_store import LegalStore


def main():
    base = ROOT / 'data/official-samples/civil-code-ff808081729d1efe01729d50b5c500bf'
    metadata = json.loads(base.with_suffix('.metadata.json').read_text())
    text_bytes = base.with_suffix('.txt').read_bytes()
    text = text_bytes.decode('utf-8')
    docx_hash = hashlib.sha256(base.with_suffix('.docx').read_bytes()).hexdigest()
    text_hash = hashlib.sha256(text_bytes).hexdigest()
    assert docx_hash == metadata['docx_sha256'], 'DOCX hash changed'
    assert text_hash == metadata['text_sha256'], 'extracted text hash changed'
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    with ZipFile(base.with_suffix('.docx')) as archive:
        assert archive.testzip() is None, 'DOCX CRC failure'
        document = ElementTree.fromstring(archive.read('word/document.xml'))
    assert not document.findall('.//w:tbl', ns), 'table extraction not accepted'
    assert not document.findall('.//w:drawing', ns), 'drawing extraction not accepted'
    paragraphs = []
    for paragraph in document.findall('.//w:body/w:p', ns):
        parts = []
        for element in paragraph.iter():
            tag = element.tag.rsplit('}', 1)[-1]
            if tag == 't':
                parts.append(element.text or '')
            elif tag == 'tab':
                parts.append('\t')
            elif tag in ('br', 'cr'):
                parts.append('\n')
        paragraphs.append(''.join(parts))
    assert '\n\n'.join(paragraphs) + '\n' == text, 'DOCX/text round trip failed'
    spans = split_articles(text)
    assert len(spans) == 1260, 'sample expected 1260 distinct articles'
    # Independent ordinal check; this intentionally does not use the parser regex.
    digits = dict(zip('零〇一二三四五六七八九', [0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9]))
    units = {'十': 10, '百': 100, '千': 1000}
    for expected, span in enumerate(spans, 1):
        label = span['article']
        number, digit = 0, 0
        for char in label[1:-1]:
            if char in digits:
                digit = digits[char]
            else:
                number += (digit or 1) * units[char]
                digit = 0
        assert number + digit == expected, f'nonsequential label: {label}'
        piece = text[span['start']:span['end']]
        assert piece.startswith(label)
        assert hashlib.sha256(piece.encode()).hexdigest() == span['article_sha256']
    heading_line = re.compile(r'第[零〇一二三四五六七八九十百千]+(?:分编|编|章|节|目)[\s\u3000]+[^\n]+')
    structural_lines = []
    for before, after in zip(spans, spans[1:]):
        assert before['end'] <= after['start']
        for line in text[before['end']:after['start']].splitlines():
            if line.strip():
                assert heading_line.fullmatch(line.strip()), f'unassigned text: {line!r}'
                structural_lines.append(line.strip())
    assert not text[spans[-1]['end']:].strip(), 'unassigned tail'
    store = LegalStore(ROOT / 'data/legal.sqlite3', readonly=True)
    try:
        version = store.db.execute('SELECT version_id FROM versions WHERE sha256=?', (text_hash,)).fetchall()
        assert len(version) == 1, 'sample must resolve to exactly one stored version'
        row = store.detail(version[0]['version_id'])
        assert row['text'] == text and row['source_url'] == metadata['source_entry_url']
        health = store.health()
    finally:
        store.close()
    report = {'at': datetime.now(timezone.utc).isoformat(), 'passed': True,
              'version_id': row['version_id'], 'source_url': row['source_url'],
              'fetched_at': metadata['fetched_at'], 'docx_sha256': docx_hash, 'text_sha256': text_hash,
              'article_count': len(spans), 'zero_labels': sum('零' in x['article'] for x in spans),
              'docx_text_exact_match': True, 'all_labels_sequential_1_to_1260': True,
              'all_article_offsets_and_hashes_match': True,
              'inter_article_structural_lines': len(structural_lines),
              'unassigned_body_content': 0, 'preamble_end': spans[0]['start'],
              'review_state': row['review_state'], 'store_health': health,
              'human_review_performed': False, 'legal_completeness_reviewed': False,
              'legal_applicability_verified': False,
              'scope': '仅对固定DOCX的正文段落和已抽取文本做机械校验；未校验页眉页脚、脚注、版式、其他版本或法律适用。',
              'articles': spans}
    target = ROOT / 'verification/civil-code-article-acceptance.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'articles'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
