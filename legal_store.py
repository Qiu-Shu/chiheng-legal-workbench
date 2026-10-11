"""Local public-law versions. Storage approval is not lawyer sign-off of a case."""
import hashlib
import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


def now():
    return datetime.now(timezone.utc).isoformat()


class LegalStore:
    def __init__(self, path, *, readonly=False):
        if readonly:
            self.db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=15)
            self.db.row_factory = sqlite3.Row
            return
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS versions (
                version_id TEXT PRIMARY KEY, law_id TEXT NOT NULL,
                title TEXT NOT NULL, text TEXT NOT NULL, source_url TEXT NOT NULL,
                locator TEXT NOT NULL, region TEXT NOT NULL, sha256 TEXT NOT NULL,
                fetched_at TEXT NOT NULL, review_state TEXT NOT NULL DEFAULT 'quarantine',
                reviewer TEXT, effective_from TEXT, effective_to TEXT);
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY, at TEXT NOT NULL, version_id TEXT NOT NULL,
                action TEXT NOT NULL, actor TEXT NOT NULL, detail TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS provenance (
                version_id TEXT PRIMARY KEY, metadata TEXT NOT NULL);
            CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
                version_id UNINDEXED, title, text, tokenize='trigram');
        ''')

    def close(self):
        self.db.close()

    def add(self, *, law_id, title, text, source_url, locator, region, provenance=None):
        if not all(isinstance(x, str) and x.strip() for x in
                   (law_id, title, text, source_url, locator, region)):
            raise ValueError('来源、正文、定位和地域不能为空')
        if urlsplit(source_url).scheme not in ('http', 'https'):
            raise ValueError('只接收有公开来源URL的法律资料')
        digest = hashlib.sha256(text.encode()).hexdigest()
        identity = json.dumps([law_id, title, digest, source_url, locator, region], ensure_ascii=False)
        version = hashlib.sha256(identity.encode()).hexdigest()
        with self.db:
            added = self.db.execute('''INSERT OR IGNORE INTO versions
                (version_id,law_id,title,text,source_url,locator,region,sha256,fetched_at)
                VALUES (?,?,?,?,?,?,?,?,?)''',
                (version, law_id, title, text, source_url, locator, region, digest, now())).rowcount
            if added:
                self.db.execute('INSERT INTO search_index VALUES (?,?,?)', (version, title, text))
                self._audit(version, 'ingest', 'system', 'quarantine')
            if provenance is not None:
                self._set_provenance(version, provenance)
                stored = self.detail(version)
                if stored['text'] != text or stored['sha256'] != digest or stored['provenance'] != provenance:
                    raise ValueError('正文或来源字段入库回读不一致')
        return version

    def _audit(self, version, action, actor, detail):
        self.db.execute('INSERT INTO audit(at,version_id,action,actor,detail) VALUES (?,?,?,?,?)',
                        (now(), version, action, actor, detail))

    def detail(self, version):
        row = self.db.execute('SELECT * FROM versions WHERE version_id=?', (version,)).fetchone()
        return self._source_fields(dict(row)) if row else None

    def _source_fields(self, row):
        metadata = self.db.execute('SELECT metadata FROM provenance WHERE version_id=?',
                                   (row['version_id'],)).fetchone()
        row['provenance'] = json.loads(metadata[0]) if metadata else {}
        state = self.db.execute("""SELECT action FROM audit WHERE version_id=?
            AND action IN ('approve','revoke') ORDER BY id DESC LIMIT 1""", (row['version_id'],)).fetchone()
        row['availability'] = 'withdrawn' if state and state[0] == 'revoke' else 'searchable'
        return row

    def set_provenance(self, version, metadata):
        """Attach immutable observed source facts; never mark legal dates as approved."""
        with self.db:
            self._set_provenance(version, metadata)

    def _set_provenance(self, version, metadata):
        """Caller owns the transaction, including when creating a new version."""
        row = self.detail(version)
        if row is None or not isinstance(metadata, dict):
            raise ValueError('来源字段需要已存在版本和字段对象')
        previous_end = 0
        for index, page in enumerate(metadata.get('pages', []), 1):
            start, end = page['start'], page['end']
            if (page['page'] != index or type(start) is not int or type(end) is not int
                    or not previous_end <= start < end <= len(row['text'])
                    or row['text'][previous_end:start].strip()):
                raise ValueError('PDF页码或正文定位不符合')
            previous_end = end
        if metadata.get('pages') and row['text'][previous_end:].strip():
            raise ValueError('PDF页码未覆盖正文')
        encoded = json.dumps(metadata, ensure_ascii=False, sort_keys=True, allow_nan=False)
        existing = self.db.execute('SELECT metadata FROM provenance WHERE version_id=?', (version,)).fetchone()
        if existing and existing[0] != encoded:
            raise ValueError('版本来源字段不同，拒绝覆盖已留证来源')
        if not existing:
            self.db.execute('INSERT INTO provenance VALUES (?,?)', (version, encoded))
            self._audit(version, 'source_metadata', 'system', '来源字段补充；非法律审核')

    def approve(self, version, *, reviewer, effective_from, effective_to=None):
        if not reviewer.strip() or not self.detail(version):
            raise ValueError('需要审核人和已存在版本')
        start = date.fromisoformat(effective_from)
        if effective_to and date.fromisoformat(effective_to) <= start:
            raise ValueError('失效日期必须晚于生效日期；期间为左闭右开')
        with self.db:
            self.db.execute('''UPDATE versions SET review_state='published',reviewer=?,
                effective_from=?,effective_to=? WHERE version_id=?''',
                (reviewer, effective_from, effective_to, version))
            self._audit(version, 'approve', reviewer,
                        json.dumps([effective_from, effective_to]))

    def revoke(self, version, *, reviewer, reason):
        if not reviewer.strip() or not reason.strip() or not self.detail(version):
            raise ValueError('撤回需要存在版本、审核人和原因')
        with self.db:
            self.db.execute("UPDATE versions SET review_state='quarantine' WHERE version_id=?", (version,))
            self._audit(version, 'revoke', reviewer, reason)

    def search(self, query, *, as_of=None, region=None, include_quarantine=True, limit=20):
        if not query.strip() or not 1 <= limit <= 100:
            raise ValueError('查询不能为空，数量必须为1到100')
        clauses, params = [], []
        if len(query) >= 3:
            clauses.append('v.version_id IN (SELECT version_id FROM search_index WHERE search_index MATCH ?)')
            params.append('"' + query.replace('"', '""') + '"')
        else:
            clauses.append('(instr(v.title,?)>0 OR instr(v.text,?)>0)')
            params.extend([query, query])
        if not include_quarantine:
            clauses.append("v.review_state='published'")
        clauses.append("""COALESCE((SELECT a.action FROM audit a WHERE a.version_id=v.version_id
            AND a.action IN ('approve','revoke') ORDER BY a.id DESC LIMIT 1),'ingest') != 'revoke'""")
        if as_of:
            date.fromisoformat(as_of)
            clauses.extend(['v.effective_from<=?', '(v.effective_to IS NULL OR v.effective_to>?)'])
            params.extend([as_of, as_of])
        if region:
            # Include national and parent-region rules, never unrelated regions.
            parts = region.split('-')
            regions = ['-'.join(parts[:i]) for i in range(1, len(parts)+1)]
            clauses.append('v.region IN (' + ','.join('?' for _ in regions) + ')')
            params.extend(regions)
        params.append(limit)
        sql = 'SELECT v.* FROM versions v WHERE ' + ' AND '.join(clauses) + ' ORDER BY v.fetched_at DESC, v.version_id LIMIT ?'
        return [self._source_fields(dict(row)) for row in self.db.execute(sql, params)]

    def health(self):
        return {'integrity': self.db.execute('PRAGMA quick_check').fetchone()[0],
                'versions': self.db.execute('SELECT count(*) FROM versions').fetchone()[0],
                'published': self.db.execute("SELECT count(*) FROM versions WHERE review_state='published'").fetchone()[0]}
