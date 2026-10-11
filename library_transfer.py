"""Verified, offline, personal transfer of the public legal library. No code is run."""
import ctypes
import errno
import portable_lock as fcntl
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import sys
import tempfile
import unicodedata
import zipfile
from contextlib import ExitStack, closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path


MAX_ENTRIES = 100_000
MAX_FILE_BYTES = 2 * 1024 ** 3
MAX_TOTAL_BYTES = 10 * 1024 ** 3
MAX_MANIFEST_BYTES = 32 * 1024 ** 2
DATA_DIRS = {'quarantine', 'upstream-catalog', 'jilin-samples', 'discovery',
             'attachment-preflight', 'official-basic-laws', 'official-samples',
             'disclosure-preflight', 'official-monitor', 'public-corpus'}
CONFIG_FILES = {'shared-library.json', 'sources.json', 'official-monitor.json',
                'jilin-samples.json', 'jilin-disclosures.json', 'jilin-traffic.json', 'coverage-targets.yaml'}
LOCKS = ('scheduler', 'source-probes', 'official-monitor', 'law-discovery', 'jilin-samples')
DB_PATH = 'data/legal.sqlite3'
CORPUS_PATH = 'data/public-corpus/provision-index.json'
CONFIG_PATH = 'config/shared-library.json'
LEDGER_PATH = 'data/review-records.jsonl'
EXCLUDED = {'.DS_Store', '__pycache__'}
CORE_COLUMNS = {
    'versions': ['version_id', 'law_id', 'title', 'text', 'source_url', 'locator',
                 'region', 'sha256', 'fetched_at', 'review_state', 'reviewer',
                 'effective_from', 'effective_to'],
    'audit': ['id', 'at', 'version_id', 'action', 'actor', 'detail'],
    'provenance': ['version_id', 'metadata'],
    'search_index': ['version_id', 'title', 'text'],
}


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf-8')


def _digest(path):
    digest = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            size += len(chunk)
            if size > MAX_FILE_BYTES:
                raise ValueError('File size limit exceeded')
            digest.update(chunk)
    return {'size': size, 'sha256': digest.hexdigest()}


def _safe_name(name):
    if (not isinstance(name, str) or not name or any(c in name for c in '\\:<>"|?*')
            or any(ord(c) < 32 for c in name)
            or any(part in ('', '.', '..') for part in name.split('/'))):
        raise ValueError('Unsafe archive path')
    for part in name.split('/'):
        base = part.split('.')[0].rstrip(' ').upper()
        if (part.endswith(('.', ' ')) or base in {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$'}
                or re.fullmatch(r'(COM|LPT)[1-9¹²³]', base)):
            raise ValueError('Unsafe Windows archive path')
    return unicodedata.normalize('NFC', name).casefold()


def _allowed(name):
    _reject_sensitive_name(name)
    parts = name.split('/')
    if any(p in EXCLUDED or p.endswith('.pyc') for p in parts):
        return False
    return (name in (DB_PATH, LEDGER_PATH, 'verification/scheduler-state.json')
            or len(parts) == 2 and parts[0] == 'config' and parts[1] in CONFIG_FILES
            or len(parts) >= 3 and parts[0] == 'data' and parts[1] in DATA_DIRS)


def _reject_sensitive_name(name):
    for part in unicodedata.normalize('NFC', name).casefold().split('/'):
        if (part.startswith('.env') or re.search(r'(^|[._-])(credentials?|secrets?|passwords?|tokens?|private[-_]cases?)([._-]|$)', part)
                or part in {'.git', '.venv', 'venv', '.cache', 'cache', 'caches', 'logs', 'node_modules'}
                or re.search(r'\.log(?:\.|$)|(?:^|[._-])cache(?:[._-]|$)', part)
                or part.endswith(('.pem', '.key', '.p12', '.pfx'))):
            raise ValueError(f'Suspected sensitive/private/secret/cache/log path refused: {name}')


def _regular(path):
    if path.is_symlink():
        raise ValueError(f'Symlink refused: {path}')
    if not path.is_file():
        raise ValueError(f'Not a regular file: {path}')


def _source_files(root):
    for part in ('data', 'config', 'verification'):
        if (root / part).is_symlink():
            raise ValueError('Symlink source directory refused')
    files = {}
    for item in (root / 'data').iterdir():
        if item.name in ('.DS_Store', 'legal.sqlite3-wal', 'legal.sqlite3-shm'):
            continue
        if item.name not in DATA_DIRS | {'legal.sqlite3', 'review-records.jsonl'}:
            raise ValueError(f'Unknown data root: {item.name}')
        if item.is_symlink():
            raise ValueError('Symlink source refused')
        candidates = item.rglob('*') if item.is_dir() else [item]
        for candidate in candidates:
            if candidate.is_symlink():
                raise ValueError('Symlink source refused')
            name = candidate.relative_to(root).as_posix()
            _reject_sensitive_name(name)
            if candidate.is_dir() or not _allowed(name) or name == DB_PATH:
                continue
            _regular(candidate)
            files[name] = candidate
    for name in [*(f'config/{f}' for f in CONFIG_FILES), 'verification/scheduler-state.json']:
        path = root / name
        if path.exists() or path.is_symlink():
            _regular(path)
            files[name] = path
    config = _json((root / CONFIG_PATH).read_bytes())
    corpus = Path(config['corpus_path'])
    if not corpus.is_absolute():
        corpus = root / 'config' / corpus
    _regular(corpus)
    files[CORPUS_PATH] = corpus
    # Only named public license/origin documents beside the corpus or its source root.
    if corpus.resolve() != (root / CORPUS_PATH).resolve():
        for level, folder in enumerate((corpus.parent, corpus.parent.parent)):
            for name in ('LICENSE', 'LICENSE.md', 'LICENSE.txt', 'COPYING', 'NOTICE', 'README.md'):
                evidence = folder / name
                if evidence.exists() or evidence.is_symlink():
                    _regular(evidence)
                    files[f'data/public-corpus/context/{level}-{name}'] = evidence
    _regular(root / DB_PATH)
    names = set()
    for name in files:
        key = _safe_name(name)
        if key in names:
            raise ValueError('Case or Unicode collision')
        names.add(key)
    return files


@contextmanager
def _locks(root):
    with ExitStack() as stack:
        for name in LOCKS:
            path = root / f'verification/{name}.lock'
            if path.is_symlink():
                raise ValueError('Symlink lock refused')
            lock = stack.enter_context(path.open('a+b'))
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ValueError(f'Writer lock busy: {name}') from error
        ledger = root / LEDGER_PATH
        if ledger.exists():
            _regular(ledger)
            lock = stack.enter_context(ledger.open('rb'))
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ValueError('Review ledger lock busy') from error
        yield


def _readonly(path):
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
    db.execute('PRAGMA query_only=ON')
    db.execute('PRAGMA trusted_schema=OFF')
    return db


def _database_info(path):
    try:
        with closing(_readonly(path)) as db:
            try:
                db.execute('BEGIN')
                if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                    raise ValueError('SQLite integrity check failed')
                schema = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
                allowed = set(CORE_COLUMNS) | {'search_index_data', 'search_index_idx',
                    'search_index_content', 'search_index_docsize', 'search_index_config'}
                for kind, name, table, sql in schema:
                    if kind not in ('table', 'index') or table not in allowed:
                        raise ValueError('Unsupported SQLite schema')
                for table, columns in CORE_COLUMNS.items():
                    metadata = db.execute(f'PRAGMA table_info({table})').fetchall()
                    actual = [row[1] for row in metadata]
                    if actual != columns:
                        raise ValueError(f'Unsupported core table schema: {table}')
                    for column in metadata:
                        expected_type = ('' if table == 'search_index' else
                                         'INTEGER' if table == 'audit' and column[1] == 'id' else 'TEXT')
                        if column[2].upper() != expected_type:
                            raise ValueError(f'Unsupported core column schema: {table}.{column[1]}')
                fts_sql = next(row[3] for row in schema if row[1] == 'search_index')
                if not re.fullmatch(r"CREATE\s+VIRTUAL\s+TABLE\s+search_index\s+USING\s+fts5\s*\(\s*"
                        r"version_id\s+UNINDEXED\s*,\s*title\s*,\s*text\s*,\s*tokenize\s*=\s*'trigram'\s*\)",
                        fts_sql.strip(), re.I):
                    raise ValueError('Unsupported FTS5 schema: require trigram and version_id UNINDEXED')
                digest = hashlib.sha256(_encoded(schema))
                counts = {}
                for table in CORE_COLUMNS:
                    rows = db.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall()
                    counts[table] = len(rows)
                    for row in rows:
                        digest.update(_encoded([table, row]) + b'\n')
                        if table == 'versions' and hashlib.sha256(row[3].encode()).hexdigest() != row[7]:
                            raise ValueError('Database text hash mismatch')
                mismatches = db.execute('''SELECT version_id,title,text FROM versions
                    EXCEPT SELECT version_id,title,text FROM search_index''').fetchall()
                reverse = db.execute('''SELECT version_id,title,text FROM search_index
                    EXCEPT SELECT version_id,title,text FROM versions''').fetchall()
                if mismatches or reverse or counts['versions'] != counts['search_index']:
                    raise ValueError('Database FTS text mismatch')
                counts['published'] = db.execute("SELECT count(*) FROM versions WHERE review_state='published'").fetchone()[0]
                counts['withdrawn'] = db.execute("""SELECT count(*) FROM versions v WHERE
                    (SELECT action FROM audit a WHERE a.version_id=v.version_id AND
                     action IN ('approve','revoke') ORDER BY id DESC LIMIT 1)='revoke'""").fetchone()[0]
                return {'logical_sha256': digest.hexdigest(), 'counts': counts}
            finally:
                db.rollback()
    except sqlite3.Error as error:
        raise ValueError(f'Invalid SQLite database: {error}') from error


def _backup_database(source, target):
    source_db = _readonly(source)
    target_db = sqlite3.connect(target)
    try:
        source_db.backup(target_db)
    finally:
        source_db.close()
        target_db.close()
    # A fresh connection observes the copied WAL header even on SQLite 3.51;
    # the backup connection can still report its pre-backup DELETE mode.
    with closing(sqlite3.connect(target)) as normalized:
        if normalized.execute('PRAGMA journal_mode=DELETE').fetchone() != ('delete',):
            raise ValueError('Cannot normalize backup journal mode')
    with target.open('rb') as snapshot:
        if snapshot.read(20)[18:20] != b'\x01\x01':
            raise ValueError('Backup still has WAL journal header')
    # These are generated only inside our private staging directory. SQLite
    # 3.51 on macOS can leave SHM after switching the closed backup to DELETE.
    wal = target.with_name(target.name + '-wal')
    if wal.exists() and wal.stat().st_size:
        raise ValueError('Backup retained nonempty WAL after normalization')
    wal.unlink(missing_ok=True)
    target.with_name(target.name + '-shm').unlink(missing_ok=True)


def _content_info(root):
    with (root / DB_PATH).open('rb') as database:
        if database.read(20)[18:20] != b'\x01\x01':
            raise ValueError('Packed database must use standalone DELETE journal mode')
    corpus_file = root / CORPUS_PATH
    data = _json(corpus_file.read_bytes())
    laws = data.get('laws')
    if not isinstance(laws, dict) or any(not isinstance(v, dict) or
            not isinstance(v.get('provisions'), list) for v in laws.values()):
        raise ValueError('Invalid public corpus schema')
    config = _json((root / CONFIG_PATH).read_bytes())
    if config.get('corpus_path') != '../data/public-corpus/provision-index.json':
        raise ValueError('Packed corpus path must be relative')
    if config.get('offline_review_state', 'unverified_mirror') != 'unverified_mirror':
        raise ValueError('Mirror must remain unverified')
    context = root / 'data/public-corpus/context'
    evidence = sorted(p.relative_to(root).as_posix() for p in context.rglob('*') if p.is_file())
    corpus = {'sha256': _digest(corpus_file)['sha256'], 'law_versions': len(laws),
              'text_units': sum(len(v['provisions']) for v in laws.values()),
              'review_state': 'unverified_mirror', 'license_evidence': evidence,
              'license_status': 'observed_documents_only; no redistribution grant inferred',
              'origin': {key: config[key] for key in ('corpus_origin', 'upstream', 'redistribution',
                         'purpose', 'scope', 'notice') if key in config}}
    ledger_counts = {}
    for path in (root / 'data').rglob('*.jsonl'):
        count = 0
        with path.open('rb') as stream:
            for line in stream:
                if line.strip():
                    _json(line)
                    count += 1
        ledger_counts[path.relative_to(root).as_posix()] = count
    return {'database': _database_info(root / DB_PATH), 'corpus': corpus,
            'ledger_counts': ledger_counts}


def _snapshot(files):
    return {name: _digest(path) for name, path in sorted(files.items())}


def _rename_directory_no_replace(source, target):
    if sys.platform == 'win32':
        os.rename(source, target)  # Windows rename never replaces an existing destination.
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == 'darwin':
        result = libc.renamex_np(os.fsencode(source), os.fsencode(target), 4)
    elif sys.platform.startswith('linux') and hasattr(libc, 'renameat2'):
        result = libc.renameat2(-100, os.fsencode(source), -100, os.fsencode(target), 1)
    else:
        raise ValueError('Atomic no-overwrite directory publication unsupported on this platform')
    if result:
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise FileExistsError(target)
        raise OSError(code, os.strerror(code), str(target))


def export_library(root, archive):
    """Snapshot public data under writer locks and publish a verified new ZIP."""
    root, archive = Path(root).absolute(), Path(archive).absolute()
    if archive.exists() or archive.is_symlink():
        raise FileExistsError(archive)
    if archive.is_relative_to(root / 'data'):
        raise ValueError('Archive must be outside data directory')
    with _locks(root), tempfile.TemporaryDirectory(prefix='.library-export-', dir=archive.parent) as temporary:
        stage = Path(temporary)
        payload = stage / 'payload'
        payload.mkdir()
        files = _source_files(root)
        before = _snapshot(files)
        database_before = _database_info(root / DB_PATH)
        for name, source in files.items():
            target = payload / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            if _digest(target) != before[name]:
                raise ValueError('Source content changed during snapshot')
        config = _json((payload / CONFIG_PATH).read_bytes())
        config['corpus_path'] = '../data/public-corpus/provision-index.json'
        (payload / CONFIG_PATH).write_bytes(_encoded(config))
        (payload / DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        _backup_database(root / DB_PATH, payload / DB_PATH)
        info = _content_info(payload)
        if database_before != info['database']:
            raise ValueError('Database changed during snapshot')
        manifest = {'format_version': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
                    'personal_use_only': True,
                    'exclusions': ['credentials', 'private_cases', 'logs', 'caches', 'virtual_environments',
                                   'machine_configuration', 'SQLite WAL/SHM files'],
                    'scope_check': 'Public-directory allowlist and suspicious-name rejection; '
                                   'cannot classify arbitrary renamed private content. '
                                   'Only use with a public-law source library.',
                    **info, 'files': _snapshot({p.relative_to(payload).as_posix(): p
                                              for p in payload.rglob('*') if p.is_file()})}
        packed = stage / 'library.zip'
        with zipfile.ZipFile(packed, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr('manifest.json', _encoded(manifest))
            for name in manifest['files']:
                bundle.write(payload / name, name)
        verify_archive(packed)
        if before != _snapshot(_source_files(root)) or database_before != _database_info(root / DB_PATH):
            raise ValueError('Source files or database changed during snapshot')
        os.link(packed, archive)  # Atomic creation: unlike rename(), never replaces a file.
        return manifest


def _unpack_verified(archive, target):
    try:
        with zipfile.ZipFile(archive) as bundle:
            entries = bundle.infolist()
            if len(entries) > MAX_ENTRIES or sum(e.file_size for e in entries) > MAX_TOTAL_BYTES:
                raise ValueError('Archive size or entry limit exceeded')
            names, normalized, prefixes = {}, set(), {}
            for entry in entries:
                name = entry.filename
                key = _safe_name(name)
                parts = name.split('/')
                for length in range(1, len(parts) + 1):
                    prefix = '/'.join(parts[:length])
                    normalized_prefix = _safe_name(prefix)
                    if normalized_prefix in prefixes and prefixes[normalized_prefix] != prefix:
                        raise ValueError('Case or Unicode directory collision')
                    prefixes[normalized_prefix] = prefix
                mode = entry.external_attr >> 16
                if (key in normalized or entry.is_dir() or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                        or entry.flag_bits & 1 or entry.file_size > MAX_FILE_BYTES):
                    raise ValueError('Duplicate, symlink, special or oversized archive member')
                if name != 'manifest.json' and not _allowed(name):
                    raise ValueError('Unlisted public-data archive path')
                normalized.add(key)
                names[name] = entry
            for key in normalized:
                if any('/'.join(key.split('/')[:i]) in normalized for i in range(1, len(key.split('/')))):
                    raise ValueError('Archive file/directory collision')
            if 'manifest.json' not in names or names['manifest.json'].file_size > MAX_MANIFEST_BYTES:
                raise ValueError('Missing or oversized manifest')
            manifest = _json(bundle.read(names['manifest.json']))
            if (not isinstance(manifest, dict) or type(manifest.get('format_version')) is not int
                    or manifest['format_version'] != 1):
                raise ValueError('Unsupported archive format version')
            files = manifest.get('files')
            if not isinstance(files, dict) or set(files) != set(names) - {'manifest.json'}:
                raise ValueError('Unlisted or absent payload members')
            if not {DB_PATH, CORPUS_PATH, CONFIG_PATH} <= files.keys() or manifest.get('personal_use_only') is not True:
                raise ValueError('Missing required public library payload')
            for name, expected in files.items():
                if (not isinstance(expected, dict) or type(expected.get('size')) is not int
                        or expected['size'] != names[name].file_size
                        or not re.fullmatch('[0-9a-f]{64}', str(expected.get('sha256', '')))):
                    raise ValueError('Invalid manifest file size/hash')
                path = target / name
                path.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(names[name]) as source, path.open('xb') as output:
                    shutil.copyfileobj(source, output, 1024 * 1024)
                if _digest(path) != expected:
                    raise ValueError('Archive content hash mismatch')
            info = _content_info(target)
            if any(manifest.get(key) != value for key, value in info.items()):
                raise ValueError('Database/corpus identity or ledger count mismatch')
            return manifest
    except (zipfile.BadZipFile, KeyError, TypeError, UnicodeError, sqlite3.Error) as error:
        raise ValueError(f'Invalid library archive: {error}') from error


def verify_archive(archive):
    """Validate all members and contents without restoring or running anything."""
    with tempfile.TemporaryDirectory(prefix='library-verify-') as temporary:
        return _unpack_verified(Path(archive), Path(temporary))


def restore_library(archive, target):
    """Restore into a new directory; an existing destination is never changed."""
    target = Path(target).absolute()
    if sys.platform == 'win32':
        _safe_name(target.name)
        for ancestor in (target, *target.parents):
            try:
                info = ancestor.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('Symlink or reparse destination ancestry refused')
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    with tempfile.TemporaryDirectory(prefix='.library-restore-', dir=target.parent) as temporary:
        payload = Path(temporary) / 'payload'
        payload.mkdir()
        manifest = _unpack_verified(Path(archive), payload)
        (payload / 'manifest.json').write_bytes(_encoded(manifest))
        _rename_directory_no_replace(payload, target)
        return manifest
