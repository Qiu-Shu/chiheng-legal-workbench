"""Verified offline core install for Windows 10 x64. Never overwrite an install."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from library_transfer import _digest, _json, _safe_name, _reject_sensitive_name, restore_library
from local_settings import load_machine_config

PYTHON_ARCHIVE = 'python-3.13.16-amd64.zip'
PYTHON_SHA256 = 'bbf675bb5e763c1efbb09a3a461b259d81598a63c30c4b0d7ea11b9f063df159'
SKILLS = {'cn-litigation-redteam', 'menglu-legal-treasury', 'scrapling-official'}


def allowed_payload(name):
    """Shared builder/installer contract, relative paths only; raises on refusal."""
    _safe_name(name)
    _reject_sensitive_name(name)
    parts = name.split('/')
    if any(part in {'__pycache__', '.DS_Store', 'behavior/runs'} for part in parts):
        raise ValueError('Generated/private payload refused: ' + name)
    allowed = name in {'install.cmd', 'windows_bootstrap.ps1', 'data/personal-public-library.zip'}
    if parts[0] == 'source' and len(parts) > 1:
        allowed = (len(parts) == 2 and (parts[1].endswith('.py') or
                   re.fullmatch(r'requirements[\w.-]*\.txt', parts[1]) is not None)
                   or len(parts) > 2 and parts[1] in {'scripts', 'tests', 'docs'}
                   or name in {'source/dist/cn-litigation-redteam.zip',
                               'source/upstream/original/LICENSE', 'source/upstream/original/NOTICE'})
        if '/behavior/runs/' in name or name.endswith(('.pyc', '.pyo')):
            allowed = False
    elif parts[0] == 'runtime':
        allowed = (name in {f'runtime/{PYTHON_ARCHIVE}', 'runtime/node-v22.23.3-win-x64.zip',
                           'runtime/pnpm-11.25.0.tgz'} or
                   len(parts) == 3 and parts[1] in {'wheels-main', 'wheels-mcp1', 'wheels-dev'} and name.endswith('.whl'))
    elif parts[0] == 'skills':
        allowed = len(parts) > 2 and parts[1] in SKILLS
    elif parts[0] == 'plugins':
        allowed = len(parts) > 2 and parts[1] == 'chiheng-legal'
    elif parts[0] == 'vendor':
        allowed = len(parts) > 2 and parts[1] in {'treasury', 'bb-browser'}
    elif parts[0] in {'docs', 'memory'}:
        allowed = len(parts) > 1
    if not allowed:
        raise ValueError('Unlisted bundle path: ' + name)
    return True


def reject_link(path):
    info = Path(path).lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise ValueError('Symlink/reparse path refused: ' + str(path))
    return info


def verify_bundle(bundle):
    """Integrity only, not publisher authentication. Outer ZIP hash is supplied separately."""
    bundle = Path(bundle).absolute()
    for parent in (bundle, *bundle.parents):
        reject_link(parent)
    manifest_path = bundle / 'manifest.json'
    if reject_link(manifest_path).st_size > 16 * 1024 * 1024:
        raise ValueError('Oversized manifest')
    manifest = _json(manifest_path.read_bytes())
    if (not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int
            or manifest['schema_version'] != 1 or not isinstance(manifest.get('files'), dict)):
        raise ValueError('Unsupported bundle manifest')
    files = manifest['files']
    required = {'source/scripts/install_windows.py', 'source/legal_mcp.py',
                'source/requirements-windows.lock.txt', 'data/personal-public-library.zip',
                f'runtime/{PYTHON_ARCHIVE}'}
    if not required <= files.keys():
        raise ValueError('Required core payload missing')
    normalized = {}
    for name, expected in files.items():
        allowed_payload(name)
        parts = name.split('/')
        for length in range(1, len(parts) + 1):
            prefix = '/'.join(parts[:length])
            key = _safe_name(prefix)
            if key in normalized and normalized[key] != prefix:
                raise ValueError('Case/Unicode collision')
            normalized[key] = prefix
        if (not isinstance(expected, dict) or set(expected) != {'size', 'sha256'} or
                type(expected['size']) is not int or expected['size'] < 0 or
                not re.fullmatch('[0-9a-f]{64}', str(expected['sha256']))):
            raise ValueError('Invalid manifest size/hash')
    found = set()
    for directory, dirs, names in os.walk(bundle, followlinks=False):
        for child in dirs + names:
            path = Path(directory) / child
            info = reject_link(path)
            relative = path.relative_to(bundle).as_posix()
            if stat.S_ISDIR(info.st_mode):
                _safe_name(relative)
                if not any(name.startswith(relative + '/') for name in files):
                    raise ValueError('Undeclared bundle directory: ' + relative)
            elif not stat.S_ISREG(info.st_mode):
                raise ValueError('Non-regular payload')
            elif relative != 'manifest.json':
                if relative not in files or _digest(path) != files[relative]:
                    raise ValueError('Undeclared or changed bundle file: ' + relative)
                found.add(relative)
    if found != files.keys():
        raise ValueError('Missing manifest files')
    return manifest


def check_host():
    if platform.system() != 'Windows' or platform.machine().upper() not in {'AMD64', 'X86_64'}:
        raise ValueError('Requires native Windows 10 x64 (Intel/AMD), not ARM or macOS')
    version = sys.getwindowsversion()
    if version.major != 10 or not 17763 <= version.build < 22000 or version.product_type != 1:
        raise ValueError('Requires Windows 10 build 17763–19045; 22H2/19045 recommended')
    return {'build': version.build, 'machine': platform.machine(), 'support': 'best_effort'}


def run(command, *, cwd=None, timeout=60, check=True, log=None):
    env = {key: value for key, value in os.environ.items()
           if key not in {'PYTHONPATH', 'PYTHONHOME', 'MENGLU_PDF_PYTHON', 'MENGLU_SOFFICE'}}
    env.update(PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1',
               PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
    if log is not None:
        with Path(log).open('a', encoding='utf-8') as output:
            return subprocess.run([str(item) for item in command], cwd=cwd, env=env,
                stdout=output, stderr=subprocess.STDOUT, check=check, timeout=timeout)
    return subprocess.run([str(item) for item in command], cwd=cwd, env=env,
                          capture_output=True, text=True, encoding='utf-8', errors='replace',
                          check=check, timeout=timeout)


def error_detail(error):
    stderr = getattr(error, 'stderr', '') or ''
    if isinstance(stderr, bytes):
        stderr = stderr.decode('utf-8', errors='replace')
    return (str(error) + ('\n' + stderr if stderr else ''))[-12000:]


PROBE = '''
import importlib, json, platform, sqlite3, struct, sys
from zoneinfo import ZoneInfo
result = dict(system=platform.system(), machine=platform.machine(),
              version=list(sys.version_info[:3]), bits=struct.calcsize('P')*8,
              utf8=bool(sys.flags.utf8_mode), timezone=False, fts5_trigram=False,
              dependencies={})
try:
    result['timezone'] = ZoneInfo('Asia/Shanghai').key == 'Asia/Shanghai'
except Exception:
    pass
try:
    with sqlite3.connect(':memory:') as db:
        db.execute("CREATE VIRTUAL TABLE probe USING fts5(text, tokenize='trigram')")
    result['fts5_trigram'] = True
except sqlite3.Error:
    pass
for name, module in [('mcp', 'mcp.server.mcpserver'), ('yaml', 'yaml'),
                     ('pypdf', 'pypdf'), ('pdfplumber', 'pdfplumber'),
                     ('scrapling', 'scrapling.fetchers'), ('httpx', 'httpx')]:
    try:
        importlib.import_module(module)
        result['dependencies'][name] = True
    except Exception:
        result['dependencies'][name] = False
print(json.dumps(result))
'''


def probe_runtime(python):
    return json.loads(run([python, '-X', 'utf8', '-c', PROBE]).stdout)


def validate_runtime(report):
    if (report['system'] != 'Windows' or report['machine'].upper() not in {'AMD64', 'X86_64'}
            or report['bits'] != 64 or tuple(report['version']) != (3, 13, 16)
            or not all(report.get(key) for key in ('fts5_trigram', 'utf8', 'timezone'))):
        raise ValueError('Runtime requires CPython 3.13.16 x64, FTS5/trigram, UTF-8, Asia/Shanghai')


def extract_runtime(archive, target, *, expected_hash=PYTHON_SHA256, required_entry='python.exe'):
    if _digest(Path(archive))['sha256'] != expected_hash:
        raise ValueError('Official Python archive hash mismatch')
    with zipfile.ZipFile(archive) as source:
        entries = source.infolist()
        if len(entries) > 20000 or sum(item.file_size for item in entries) > 2 * 1024**3:
            raise ValueError('Runtime archive too large')
        seen, prefixes = set(), {}
        for entry in entries:
            name = entry.filename.rstrip('/') if entry.is_dir() else entry.filename
            key = _safe_name(name)
            mode = stat.S_IFMT(entry.external_attr >> 16)
            if key in seen or mode not in (0, stat.S_IFREG, stat.S_IFDIR) or entry.flag_bits & 1:
                raise ValueError('Unsafe runtime entry')
            seen.add(key)
            for i in range(1, len(name.split('/')) + 1):
                prefix = '/'.join(name.split('/')[:i])
                normalized = _safe_name(prefix)
                if normalized in prefixes and prefixes[normalized] != prefix:
                    raise ValueError('Runtime path collision')
                prefixes[normalized] = prefix
        Path(target).mkdir(parents=True, exist_ok=False)
        for entry in entries:
            destination = Path(target) / entry.filename
            if entry.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with source.open(entry) as input_file, destination.open('xb') as output:
                    shutil.copyfileobj(input_file, output)
    if not (Path(target) / required_entry).is_file():
        raise ValueError('Runtime missing required executable')


SMOKE = '''
import hashlib, json
from pathlib import Path
from legal_store import LegalStore
import legal_mcp as mcp
from library_transfer import _digest
manifest = json.loads(Path('manifest.json').read_text(encoding='utf-8'))
store = LegalStore('data/legal.sqlite3', readonly=True)
try:
    health = store.health()
    assert health['integrity'] == 'ok'
    sample = next(store.detail(row[0]) for row in store.db.execute('SELECT version_id FROM versions')
                  if store.detail(row[0])['availability'] != 'withdrawn')
    hits = mcp.search_law(sample['title'], include_quarantine=True, limit=100)['results']
    assert any(row['version_id'] == sample['version_id'] for row in hits)
    fragment = mcp.get_law_fragment(sample['version_id'])
    assert fragment['found'] and fragment['text'] == sample['text'][:3000]
    card = fragment['citation']
    assert card['version_id'] == sample['version_id'] and card['source_url'] == sample['source_url']
    assert card['text_sha256'] == hashlib.sha256(sample['text'].encode()).hexdigest()
    assert card['review_at_use_required'] and isinstance(card['missing_fields'], list)
finally:
    store.close()
mirror = json.loads(mcp.corpus.path.read_text(encoding='utf-8'))['laws']
law_id, law, provision = next((key, law, p) for key, law in mirror.items()
                            for p in law.get('provisions', []) if p.get('text', '').strip())
mirror_hits = mcp.search_public_corpus(provision['text'][:32], law_title=law['title'], limit=50)['results']
assert any(row['law_id'] == law_id and row['text_sha256'] == hashlib.sha256(provision['text'].encode()).hexdigest()
           for row in mirror_hits)
raw = next(name for name in manifest['files'] if name.startswith('data/')
           and not name.startswith('data/public-corpus/')
           and name.lower().endswith(('.html', '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.bin')))
assert _digest(Path(raw)) == manifest['files'][raw]
print(json.dumps(dict(ok=True, versions=health['versions'], fragment=True,
                     source_card=True, raw_file=raw, mirror=True)))
'''

PDF_PROBE = '''
from io import BytesIO
import json
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
import pdfplumber
out = BytesIO()
writer = PdfWriter()
page = writer.add_blank_page(width=300, height=200)
font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                         NameObject('/Subtype'): NameObject('/Type1'),
                         NameObject('/BaseFont'): NameObject('/Helvetica')})
page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
    DictionaryObject({NameObject('/F1'): font})})
content = DecodedStreamObject()
content.set_data(b'BT /F1 12 Tf 30 100 Td (Chiheng PDF probe) Tj ET')
page[NameObject('/Contents')] = writer._add_object(content)
writer.write(out)
pypdf_text = PdfReader(BytesIO(out.getvalue())).pages[0].extract_text().strip()
with pdfplumber.open(BytesIO(out.getvalue())) as pdf:
    pdfplumber_text = pdf.pages[0].extract_text().strip()
assert pypdf_text == pdfplumber_text == 'Chiheng PDF probe'
print(json.dumps(dict(pypdf_text=pypdf_text, pdfplumber_text=pdfplumber_text)))
'''


def port_free(port=18063):
    with socket.socket() as listener:
        try:
            listener.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False


def doctor(target):
    target = Path(target).absolute()
    python = target / '.venv/Scripts/python.exe'
    report = dict(ready_search=False, ready_pdf=False, ready_doc=False, ready_update=False,
                  ready_mock_hearing=False, browser='pending_native_test',
                  update='pending_external_adapter_and_network_test',
                  autostart='not_checked', login_restart_verified=False,
                  http_ready_verified=False, port_conflict=not port_free(), errors=[])
    try:
        runtime = probe_runtime(python)
        report['runtime'] = runtime
        validate_runtime(runtime)
        load_machine_config(target / 'config/local-machine.json')
        deps = runtime['dependencies']
        if all(deps.get(name) for name in ('mcp', 'yaml')):
            report['library'] = json.loads(run([python, '-X', 'utf8', '-c', SMOKE], cwd=target, timeout=180).stdout)
            report['ready_search'] = report['library']['ok'] is True
        else:
            report['errors'].append('Missing MCP/YAML imports')
        if all(deps.get(name) for name in ('pypdf', 'pdfplumber')):
            report['pdf'] = json.loads(run([python, '-X', 'utf8', '-c', PDF_PROBE], cwd=target).stdout)
            report['ready_pdf'] = True
        # A native-only suite creates and removes its own synthetic temp directory.
        native = run([python, '-X', 'utf8', '-m', 'unittest',
            'tests.test_windows_private.WindowsPrivateNativeTests', '-v'], cwd=target, timeout=180, check=False)
        report['mock_hearing_output'] = native.stdout + native.stderr
        report['ready_mock_hearing'] = (native.returncode == 0 and
            'Ran 0 tests' not in report['mock_hearing_output'] and
            'skipped' not in report['mock_hearing_output'].lower() and
            'test_synthetic_full_hearing' in report['mock_hearing_output'])
        report['doc'] = 'pending_real_conversion'
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        report['errors'].append(error_detail(error))
    from windows_external import doctor as external_doctor
    report['external'] = external_doctor(target)
    return report


def save_state(target, state):
    path = Path(target) / 'verification/install/state.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, ensure_ascii=False, indent=2) + '\n'
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                prefix='.state-', suffix='.tmp', delete=False) as output:
            temporary = Path(output.name)
            output.write(payload)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def copy_payload(bundle, target, manifest):
    for name, expected in manifest['files'].items():
        parts = name.split('/')
        if parts[0] not in {'source', 'skills', 'plugins', 'vendor', 'memory', 'docs'}:
            continue
        relative = Path(*parts[1:]) if parts[0] == 'source' else Path(*parts)
        # Root docs are delivery docs, separate from source docs to avoid collisions.
        if parts[0] == 'docs':
            relative = Path('delivery-docs', *parts[1:])
        source = Path(bundle) / name
        reject_link(source)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with source.open('rb') as original, destination.open('xb') as output:
            shutil.copyfileobj(original, output)
        if _digest(destination) != expected:
            raise ValueError('Source changed during copy: ' + name)


def install(bundle, target, *, obsidian_vault=None, soffice=None):
    host = check_host()
    target = Path(target).expanduser().absolute()
    if target.exists() or target.is_symlink():
        raise FileExistsError('Target exists; choose a new directory: ' + str(target))
    for ancestor in (target, *target.parents):
        if ancestor.exists() or ancestor.is_symlink():
            reject_link(ancestor)
    _safe_name(target.name)
    bundle = Path(bundle).absolute()
    manifest = verify_bundle(bundle)
    settings = {}
    if obsidian_vault:
        vault = Path(obsidian_vault).absolute()
        if not vault.is_dir():
            raise ValueError('Obsidian vault must exist')
        settings['obsidian_target'] = str(vault / 'Songmeng_Law/08_Law/Shared-Library/Live-Inventory.md')
    if soffice:
        if not Path(soffice).is_file():
            raise ValueError('Configured soffice.exe not found')
        settings['soffice'] = str(Path(soffice).absolute())
    target.parent.mkdir(parents=True, exist_ok=True)
    restore_library(bundle / 'data/personal-public-library.zip', target)
    state = dict(status='installing', target=str(target), install_id=str(uuid.uuid4()),
                 activated=False, host=host)
    try:
        save_state(target, state)
        copy_payload(bundle, target, manifest)
        if (target / 'vendor/treasury/sources/legal-tools/国家法律法规数据库MCP/scripts/client.py').is_file():
            settings['treasury_root'] = str(target / 'vendor/treasury')
        (target / 'config/local-machine.json').write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
        extract_runtime(bundle / f'runtime/{PYTHON_ARCHIVE}', target / 'runtime/python')
        run([target / 'runtime/python/python.exe', '-X', 'utf8', '-m', 'venv', target / '.venv'], timeout=180)
        python = target / '.venv/Scripts/python.exe'
        run([python, '-X', 'utf8', '-m', 'pip', 'install', '--disable-pip-version-check',
             '--no-index', '--find-links', bundle / 'runtime/wheels-main', '--require-hashes',
             '-r', target / 'requirements-windows.lock.txt'], cwd=target, timeout=1800)
        report = doctor(target)
        state.update(report)
        if not report['ready_search'] or not report['ready_pdf'] or not report['ready_mock_hearing']:
            raise ValueError('Core doctor failed; see verification/install/state.json')
        fragment = '[mcp_servers.chiheng_legal]\ncommand = ' + json.dumps(str(python)) + '\nargs = ' + json.dumps(
            ['-E', '-s', '-X', 'utf8', str(target / 'legal_mcp.py')], ensure_ascii=False) + '\n'
        (target / 'verification/install/codex-mcp.toml').write_text(fragment, encoding='utf-8')
        from windows_external import install_components
        state['external'] = install_components(bundle, target)
        state.update(status='complete', endpoint='http://127.0.0.1:18063/mcp',
                     completion_scope='core_only_external_status_separate',
                     codex_connection='manual_import_required', skills='bundled_not_imported_into_host')
        save_state(target, state)
        return state
    except Exception as error:
        state.update(status='failed', error=error_detail(error), activated=False)
        save_state(target, state)
        raise


def task_manifest(target, install_id):
    target = Path(target).absolute()
    identity = hashlib.sha256(str(target).casefold().encode('utf-8')).hexdigest()[:16]
    tasks = []
    for kind in ('mcp', 'update'):
        arguments = ['-E', '-s', '-X', 'utf8', str(target / 'scripts/install_windows.py'),
                     '--target', str(target), '--run-task', kind]
        tasks.append(dict(name=f'Chiheng-{identity}-{kind}', kind=kind,
            execute=str(target / '.venv/Scripts/python.exe'),
            arguments=subprocess.list2cmdline(arguments), working_directory=str(target)))
    return {'target': str(target), 'install_id': install_id, 'tasks': tasks}


def task_action(target, mode, install_id):
    request = Path(target) / 'verification/install/tasks.json'
    request.write_text(json.dumps(task_manifest(target, install_id), ensure_ascii=False, indent=2), encoding='utf-8')
    powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = run([powershell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                  '-File', Path(target) / 'scripts/windows_tasks.ps1',
                  '-Mode', mode, '-Manifest', request], timeout=120)
    return json.loads(result.stdout)


def installed_state(target):
    target = Path(target).absolute()
    for path in (target, *target.parents):
        reject_link(path)
    state = json.loads((target / 'verification/install/state.json').read_text(encoding='utf-8'))
    if state.get('status') != 'complete' or state.get('target') != str(target) or not state.get('install_id'):
        raise ValueError('Only a complete installation at its original path can control tasks')
    return state


def activate(target):
    check_host()
    target = Path(target).absolute()
    state = installed_state(target)
    if not port_free():
        raise ValueError('Port 18063 already in use; existing service unchanged')
    report = doctor(target)
    if not report['ready_search']:
        raise ValueError('Search health check failed; no task registered')
    try:
        result = task_action(target, 'Activate', state['install_id'])
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        state.update(autostart='activation_failed_review_required', activation_error=error_detail(error))
        save_state(target, state)
        raise
    try:
        state.update(activated=True, autostart='registered', login_restart_verified=False,
                     http_ready_verified=False)
        save_state(target, state)
    except Exception:
        rollback = 'Remove' if result.get('activation_mode') == 'created' else 'Disable'
        task_action(target, rollback, state['install_id'])
        raise
    return result


def deactivate(target):
    check_host()
    target = Path(target).absolute()
    state = installed_state(target)
    result = task_action(target, 'Disable', state['install_id'])
    state.update(activated=False, autostart='disabled')
    save_state(target, state)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--obsidian-vault', type=Path)
    parser.add_argument('--soffice', type=Path)
    parser.add_argument('--activate', action='store_true')
    parser.add_argument('--doctor', action='store_true')
    parser.add_argument('--deactivate', action='store_true')
    parser.add_argument('--run-task', choices=('mcp', 'update'))
    args = parser.parse_args()
    try:
        if args.run_task:
            check_host()
            installed_state(args.target)
            if args.target.absolute() != ROOT:
                raise ValueError('Task must execute its own installation')
            if args.run_task == 'mcp' and not port_free():
                raise ValueError('Port 18063 is occupied')
            command = [sys.executable, '-X', 'utf8', str(ROOT /
                ('legal_mcp.py' if args.run_task == 'mcp' else 'scripts/scheduled_update.py'))]
            if args.run_task == 'mcp':
                command.append('--http')
            # MCP is deliberately long-lived; periodic scheduler remains bounded.
            result = run(command, cwd=ROOT, timeout=None if args.run_task == 'mcp' else 3600,
                         check=False, log=ROOT / f'verification/install/{args.run_task}.log')
            return result.returncode
        if args.doctor:
            check_host()
            result = doctor(args.target)
        elif args.deactivate:
            result = deactivate(args.target)
        elif args.bundle:
            result = install(args.bundle, args.target, obsidian_vault=args.obsidian_vault, soffice=args.soffice)
            if args.activate:
                result['activation'] = activate(args.target)
        elif args.activate:
            result = activate(args.target)
        else:
            parser.error('Use --bundle, --doctor, --activate or --deactivate')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if args.doctor and not result['ready_search'] else 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({'status': 'failed', 'error': error_detail(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
