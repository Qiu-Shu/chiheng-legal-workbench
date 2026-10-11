"""Read-only adapter for the existing public-law index, not a new corpus copy."""
import hashlib
import json
from collections import Counter
from pathlib import Path
from threading import RLock


class PublicCorpus:
    def __init__(self, path):
        self.path = Path(path)
        self._signature = None
        self._laws = {}
        self._lock = RLock()

    def _load(self):
        stat = self.path.stat()
        signature = (stat.st_mtime_ns, stat.st_size)
        if signature != self._signature:
            raw = self.path.read_bytes()
            data = json.loads(raw)
            laws = data.get('laws')
            if not isinstance(laws, dict):
                raise ValueError('法规索引格式不符，不能当作空库')
            self._laws = laws
            self._sha256 = hashlib.sha256(raw).hexdigest()
            self._signature = signature

    def _fragment(self, law_id, law, index):
        item = law['provisions'][index]
        text = item.get('text', '')
        return {
            'law_id': law_id, 'title': law.get('title'), 'category': law.get('group'),
            'article': item.get('article'), 'chapter': item.get('chapter', ''),
            'text': text, 'source_urls': law.get('urls', []),
            'fragment_id': f'{self._sha256}:{law_id}:{index}',
            'corpus_sha256': self._sha256,
            'text_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'upstream_status': law.get('status'),
            'upstream_effective_date': law.get('effective_date'),
            'review_state': 'unverified_mirror', 'applicability_verified': False,
            'warning': '离线线索；原文缺失及拆条遗漏尚未排除。须在官方具体条文核验版本、效力和完整性。'
        }

    def inventory(self):
        with self._lock:
            try:
                self._load()
            except FileNotFoundError:
                return {'available': False, 'reason': 'corpus_missing'}
            return {
                'available': True, 'corpus_sha256': self._sha256,
                'law_versions': len(self._laws),
                'text_units': sum(len(law.get('provisions', [])) for law in self._laws.values()),
                'categories': dict(Counter(law.get('group', '未知') for law in self._laws.values())),
                'upstream_statuses': dict(Counter(law.get('status', '未知') for law in self._laws.values())),
                'review_state': 'unverified_mirror', 'coverage_complete': False,
                'notice': '数量为索引版本/文本单元，不等于独立现行法数量或完整法条数量。'
            }

    def search(self, query, *, law_title=None, category=None, limit=10):
        if not query.strip() or not 1 <= limit <= 50:
            raise ValueError('检索词不能为空，limit为1到50')
        with self._lock:
            self._load()
            results = []
            for law_id, law in self._laws.items():
                if law_title and law_title not in law.get('title', ''):
                    continue
                if category and category != law.get('group'):
                    continue
                for index, item in enumerate(law.get('provisions', [])):
                    if query not in item.get('text', '') and query not in item.get('article', ''):
                        continue
                    row = self._fragment(law_id, law, index)
                    text = row.pop('text')
                    pos = max(0, text.find(query) - 160)
                    row.update(excerpt=text[pos:pos + 1400], excerpt_offset=pos,
                               total_length=len(text))
                    results.append(row)
                    if len(results) == limit:
                        return results
            return results

    def article(self, law_id, article, *, offset=0, length=5000):
        if not article.strip() or offset < 0 or not 1 <= length <= 10000:
            raise ValueError('需要准确条号，offset非负，length为1到10000')
        with self._lock:
            self._load()
            law = self._laws.get(law_id)
            if not law:
                return []
            results = []
            for index, item in enumerate(law.get('provisions', [])):
                if item.get('article') == article:
                    row = self._fragment(law_id, law, index)
                    text = row.pop('text')
                    row.update(text=text[offset:offset + length], offset=offset, total_length=len(text))
                    results.append(row)
            return results
