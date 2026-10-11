"""Offline artifact verification plus real loopback MCP round trips for the fixed batch."""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from legal_store import LegalStore
from official_docx import check_articles, extract_docx
from scripts.ingest_basic_laws import batch_targets, MISSING_CATALOG_TARGETS, UNNUMBERED_REPLY_ID, check_document
from legacy_doc import convert_legacy_doc
from scripts.smoke_shared_library import tool


def main(batch_name='basic-laws'):
    capture = json.loads((ROOT / f'verification/{batch_name}-ingestion-latest.json').read_text())
    assert [(row['title'], row['law_id']) for row in capture['results']] == batch_targets(batch_name)
    report = {'at': datetime.now(timezone.utc).isoformat(), 'passed': True, 'results': [],
              'batch': batch_name, 'pending': [],
              'human_law_review_performed': False, 'legal_applicability_verified': False}
    store = LegalStore(ROOT / 'data/legal.sqlite3', readonly=True)
    try:
        for row in capture['results']:
            if row['status'] == 'failed' and batch_name == 'supporting-rules':
                report['pending'].append({key: row.get(key) for key in ('title', 'law_id', 'phase', 'downloaded')})
                continue
            assert row['status'] == 'ingested_quarantine', row['title']
            folder = (ROOT / row['artifact_directory']).resolve()
            assert folder.is_relative_to(ROOT / 'data/official-basic-laws')
            original = (folder / row.get('original_file', 'original.docx')).read_bytes()
            assert hashlib.sha256(original).hexdigest() == row.get('original_sha256', row['docx_sha256'])
            legacy = row.get('source_format') == 'doc'
            docx = (folder / ('converted-libreoffice.docx' if legacy else 'original.docx')).read_bytes()
            assert hashlib.sha256(docx).hexdigest() == row['docx_sha256']
            raw, extraction = extract_docx(docx, row['title'])
            assert raw == (folder / row.get('raw_text_file', 'raw-body.txt')).read_text()
            assert hashlib.sha256(raw.encode()).hexdigest() == row['raw_text_sha256']
            if legacy:
                converted, direct = convert_legacy_doc(original)
                reconverted, _ = extract_docx(converted, row['title'])
                assert reconverted == raw
                assert direct == (folder / 'direct-libreoffice.txt').read_text()
                assert hashlib.sha256(direct.encode()).hexdigest() == row['conversion']['direct_text_sha256']
                assert ''.join(direct.split()) == ''.join(raw.split())
            text = (folder / row.get('text_file', 'body.txt')).read_text()
            assert hashlib.sha256(text.encode()).hexdigest() == row['text_sha256']
            reconstructed = raw
            for change in row['heading_normalization']:
                start, end = change['start'], change['end']
                assert raw[start:end] == change['original']
                assert change['normalized'] == change['original'].replace('\n', ' ')
                reconstructed = reconstructed[:start] + change['normalized'] + reconstructed[end:]
            assert reconstructed == text, 'unrecorded text transformation'
            unnumbered = row['law_id'] == UNNUMBERED_REPLY_ID
            if unnumbered:
                assert row['official_catalog_missing'] and row['official_article_labels'] == []
                checked = check_document(text, None, row['law_id'])
            else:
                checked = check_articles(text, row['official_article_labels'], allow_missing_catalog=(
                    row['law_id'] in MISSING_CATALOG_TARGETS and row.get('official_catalog_missing') is True))
            assert checked['articles'] == row['mechanical_check']['articles']
            assert checked['official_labels_match'] == row['mechanical_check']['official_labels_match']
            stored = store.detail(row['version_id'])
            assert stored['text'] == text and stored['sha256'] == row['text_sha256']
            assert stored['source_url'] == row['source_url'] and stored['review_state'] == 'quarantine'
            # Independent ordinal check: these six accepted versions have consecutive base articles.
            digits = dict(zip('零〇一二三四五六七八九', [0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9]))
            units = {'十': 10, '百': 100, '千': 1000}
            for expected, span in enumerate(checked['articles'], 1):
                number, digit = 0, 0
                for char in span['article'][1:-1]:
                    if char in digits:
                        digit = digits[char]
                    else:
                        number += (digit or 1) * units[char]
                        digit = 0
                assert number + digit == expected, span['article']
                original = raw[span['start']:span['end']]
                assert text[span['start']:span['end']] == original
                assert hashlib.sha256(original.encode()).hexdigest() == span['article_sha256']
            all_spans = checked['articles']
            selected = {0, len(all_spans) // 2, len(all_spans) - 1}
            selected.update(i for i, span in enumerate(all_spans) if '零' in span['article'])
            if batch_name == 'supporting-rules':
                selected = set(range(len(all_spans)))
            samples = []
            for index in sorted(selected):
                span = all_spans[index]
                response = tool('get_law_article', {'version_id': row['version_id'],
                                                    'article': span['article'], 'length': 10000})
                assert response['found'] and not response['truncated']
                assert response['text'] == raw[span['start']:span['end']]
                assert response['article_sha256'] == span['article_sha256']
                assert response['review_state'] == 'quarantine'
                samples.append(span['article'])
            fragment_calls = 0
            if unnumbered:
                fragments = []
                for offset in range(0, len(text), 200):
                    response = tool('get_law_fragment', {'version_id': row['version_id'], 'offset': offset, 'length': 200})
                    assert response['found'] and response['total_length'] == len(text)
                    assert response['review_state'] == 'quarantine'
                    fragments.append(response['text'])
                    fragment_calls += 1
                assert ''.join(fragments) == text
            hits = tool('search_law', {'query': row['title'], 'include_quarantine': True})['results']
            assert row['version_id'] in {hit['version_id'] for hit in hits}
            assert tool('search_law', {'query': row['title'], 'include_quarantine':False})['results'] == []
            report['results'].append({'title': row['title'], 'version_id': row['version_id'],
                'article_count': checked['article_count'], 'source_url': row['source_url'],
                'docx_sha256': row['docx_sha256'], 'text_sha256': row['text_sha256'],
                'all_article_hashes_and_offsets_match': True,
                'consecutive_numbering_checked': not unnumbered,
                'structure': 'unnumbered_document' if unnumbered else 'articles',
                'original_format': row.get('source_format', 'docx'),
                'mcp_fulltext_fragment_calls': fragment_calls,
                'original_sha256': row.get('original_sha256', row['docx_sha256']),
                'official_catalog_status': checked['catalog_status'],
                'raw_docx_extraction_round_trip': True,
                'heading_normalization_count': len(row['heading_normalization']),
                'mcp_round_trip_articles': samples, 'explicit_approved_search_excludes_quarantine': True})
        report['store_health'] = store.health()
    finally:
        store.close()
    report['total_articles'] = sum(row['article_count'] for row in report['results'])
    assert report['results'], 'No successfully ingested documents to verify'
    report['full_batch_complete'] = not report['pending']
    report['mcp_article_round_trips'] = sum(len(row['mcp_round_trip_articles']) for row in report['results'])
    report['mcp_fulltext_fragment_calls'] = sum(row['mcp_fulltext_fragment_calls'] for row in report['results'])
    (ROOT / f'verification/{batch_name}-acceptance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'results'}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch', choices=('basic-laws', 'supporting-rules'), default='basic-laws')
    main(parser.parse_args().batch)
