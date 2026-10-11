"""Install a verified personal library on Apple Silicon; activation is explicit."""
import argparse
import json
import os
import platform
import plistlib
import shutil
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from library_transfer import restore_library
from local_settings import load_machine_config, require_treasury

LABELS = ('com.chiheng.legal-mcp', 'com.menglu.legal-update')
PROBE = '''
import importlib, json, platform, sqlite3, sys
result = dict(system=platform.system(), machine=platform.machine(),
              version=list(sys.version_info[:3]), sqlite=sqlite3.sqlite_version)
try:
    with sqlite3.connect(':memory:') as db:
        db.execute("CREATE VIRTUAL TABLE probe USING fts5(text, tokenize='trigram')")
    result['fts5_trigram'] = True
except sqlite3.Error:
    result['fts5_trigram'] = False
result['dependencies'] = {}
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
SMOKE = '''
import hashlib, json
from pathlib import Path
from legal_store import LegalStore
from shared_corpus import PublicCorpus
from local_settings import resolve_config_path
import legal_mcp
config_path = Path('config/shared-library.json')
config = json.loads(config_path.read_text())
corpus = PublicCorpus(resolve_config_path(config_path, config['corpus_path']))
inventory = corpus.inventory()
if not inventory['available']:
    raise ValueError('Mirror unavailable')
mirror_hits = []
mirror_data = json.loads(corpus.path.read_text())['laws']
for law_id, law in mirror_data.items():
    sample = next((item for item in law.get('provisions', []) if item.get('text', '').strip()), None)
    if sample:
        mirror_hits = corpus.search(sample['text'][:32], law_title=law.get('title'), limit=50)
        digest = hashlib.sha256(sample['text'].encode()).hexdigest()
        if not any(row['law_id'] == law_id and row['text_sha256'] == digest for row in mirror_hits):
            raise ValueError('Mirror search failed to return stored text')
        break
store = LegalStore('data/legal.sqlite3', readonly=True)
try:
    health = store.health()
    if health['integrity'] != 'ok':
        raise ValueError('SQLite integrity check failed')
    hits = []
    for row in store.db.execute('SELECT version_id FROM versions ORDER BY fetched_at DESC, version_id'):
        sample = store.detail(row['version_id'])
        if sample['availability'] == 'withdrawn':
            continue
        hits = store.search(sample['title'], include_quarantine=True, limit=100)
        if not any(hit['version_id'] == sample['version_id'] and hit['text'] == sample['text'] for hit in hits):
            raise ValueError('Database search failed to return stored version')
        break
finally:
    store.close()
print(json.dumps(dict(ok=True, versions=health['versions'],
    mirror_versions=inventory['law_versions'], search_hits=len(hits),
    mirror_hits=len(mirror_hits))))
'''


def run(command, *, cwd=None, timeout=60, check=True):
    # A fresh venv must not accidentally import the source machine's packages.
    env = {key: value for key, value in os.environ.items()
           if key not in ('PYTHONPATH', 'PYTHONHOME', 'MENGLU_PDF_PYTHON', 'MENGLU_SOFFICE')}
    env['PYTHONNOUSERSITE'] = '1'
    return subprocess.run([str(item) for item in command], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=timeout, check=check)


def check_host():
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise ValueError('仅支持原生 Apple Silicon macOS；请退出 Rosetta 后重试')


def probe_runtime(python):
    return json.loads(run([str(python), '-c', PROBE], timeout=60).stdout)


def validate_runtime(report):
    if (report['system'] != 'Darwin' or report['machine'] != 'arm64'
            or tuple(report['version']) < (3, 12) or not report['fts5_trigram']):
        raise ValueError('目标 Python 必须为原生 macOS arm64、3.12+，SQLite 支持 FTS5/trigram')


def select_python(explicit=None):
    bundled = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3'
    candidates = [explicit] if explicit else [sys.executable, bundled,
                  shutil.which('python3.12'), shutil.which('python3')]
    errors = []
    for candidate in candidates:
        if not candidate:
            continue
        candidate = Path(candidate).expanduser().absolute()
        try:
            validate_runtime(probe_runtime(candidate))
            return candidate
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            errors.append(f'{candidate}: {error}')
    raise ValueError('未找到合适的 Python；用 --python 指定 3.12+。\n' + '\n'.join(errors))


def port_free(port=18063):
    with socket.socket() as listener:
        try:
            listener.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False


def machine_settings(*, obsidian_vault=None, soffice=None, treasury_root=None):
    settings = {}
    if obsidian_vault:
        vault = Path(obsidian_vault).expanduser().resolve()
        if not vault.is_dir():
            raise ValueError('Obsidian vault 必须是现有目录')
        settings['obsidian_target'] = str(vault / 'Songmeng_Law/08_Law/Shared-Library/Live-Inventory.md')
    if soffice:
        executable = Path(soffice).expanduser().resolve()
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError('soffice 必须是可执行文件')
        settings['soffice'] = str(executable)
    if treasury_root:
        settings['treasury_root'] = str(require_treasury(Path(treasury_root).expanduser().resolve()))
    return settings


def smoke_library(target, python):
    return json.loads(run([str(python), '-c', SMOKE], cwd=target, timeout=120).stdout)


def doctor(target):
    target = Path(target).expanduser().resolve()
    report = {'ready_search': False, 'ready_pdf': False, 'ready_doc': False,
              'ready_update': False, 'port_conflict': not port_free(), 'errors': [],
              'update_network_verified': False, 'browser_binaries': 'not_checked'}
    try:
        runtime = probe_runtime(target / '.venv/bin/python')
        report['runtime'] = runtime
        validate_runtime(runtime)
        deps = runtime['dependencies']
        settings = load_machine_config(target / 'config/local-machine.json')
        soffice = settings.get('soffice') or shutil.which('soffice') or '/Applications/LibreOffice.app/Contents/MacOS/soffice'
        report['ready_doc'] = Path(soffice).is_file() and os.access(soffice, os.X_OK)
        report['ready_pdf'] = all(deps.get(name, False) for name in ('pypdf', 'pdfplumber'))
        if all(deps.get(name, False) for name in ('mcp', 'yaml')):
            report['library'] = smoke_library(target, target / '.venv/bin/python')
            report['ready_search'] = report['library']['ok']
        treasury = settings.get('treasury_root')
        treasury_ready = bool(treasury and (Path(treasury) /
            'sources/legal-tools/国家法律法规数据库MCP/scripts/client.py').is_file())
        report['treasury_client_present'] = treasury_ready
        if treasury_ready:
            try:
                run([str(target / '.venv/bin/python'), '-c',
                     'import sys; sys.path.insert(0, sys.argv[1]); from client import FlkClient; import models',
                     str(Path(treasury) / 'sources/legal-tools/国家法律法规数据库MCP/scripts')],
                    cwd=target, timeout=60)
            except (OSError, subprocess.SubprocessError) as error:
                treasury_ready = False
                report['errors'].append('国家库客户端导入失败：' + str(error))
        report['treasury_client_importable'] = treasury_ready
        report['ready_update'] = (report['ready_search'] and treasury_ready
                                  and all(deps.get(name, False) for name in ('scrapling', 'httpx')))
        report['missing_dependencies'] = [name for name, available in deps.items() if not available]
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        report['errors'].append(str(error))
    return report


def generate_plists(target, *, include_update):
    target = Path(target).resolve()
    output = target / 'verification/install'
    output.mkdir(parents=True, exist_ok=True)
    paths = []
    for label in LABELS[:2 if include_update else 1]:
        mcp = label == LABELS[0]
        arguments = [str(target / '.venv/bin/python'), str(target /
                     ('legal_mcp.py' if mcp else 'scripts/scheduled_update.py'))]
        if mcp:
            arguments.append('--http')
        content = {'Label': label, 'ProgramArguments': arguments,
                   'WorkingDirectory': str(target), 'RunAtLoad': True,
                   'EnvironmentVariables': {'PYTHONNOUSERSITE': '1', 'PYTHONUNBUFFERED': '1'},
                   'StandardOutPath': str(target / f'verification/{label}.stdout.log'),
                   'StandardErrorPath': str(target / f'verification/{label}.stderr.log')}
        content.update({'KeepAlive': True} if mcp else {'StartInterval': 300})
        path = output / f'{label}.plist'
        with path.open('xb') as stream:
            plistlib.dump(content, stream)
        paths.append(path)
    return paths


def save_state(target, state):
    path = target / 'verification/install/state.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')


def install(archive, target, *, python=None, profile='full', obsidian_vault=None,
            soffice=None, treasury_root=None):
    target = Path(target).expanduser().absolute()
    if target.exists() or target.is_symlink():
        raise FileExistsError(f'目标已存在，未修改：{target}。请保留原目录并选择全新目标。')
    check_host()
    if profile not in ('full', 'search'):
        raise ValueError('profile 必须为 full 或 search')
    selected = select_python(python)
    settings = machine_settings(obsidian_vault=obsidian_vault, soffice=soffice, treasury_root=treasury_root)
    restore_library(archive, target)
    state = {'status': 'installing', 'profile': profile, 'target': str(target)}
    try:
        save_state(target, state)
        # Only executable source and dependency manifests; data/config come from the verified archive.
        for pattern in ('*.py', 'scripts/*.py', 'requirements*.txt'):
            for source in ROOT.glob(pattern):
                if source.is_symlink() or not source.is_file():
                    raise ValueError(f'源码必须是普通文件：{source}')
                destination = target / source.relative_to(ROOT)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open('xb') as stream:
                    stream.write(source.read_bytes())
        if settings:
            (target / 'config/local-machine.json').write_text(json.dumps(settings, ensure_ascii=False, indent=2))
        run([str(selected), '-m', 'venv', str(target / '.venv')], timeout=120)
        runtime_python = target / '.venv/bin/python'
        validate_runtime(probe_runtime(runtime_python))
        requirements = 'requirements.lock.txt' if profile == 'full' else 'requirements-search.txt'
        run([str(runtime_python), '-m', 'pip', 'install', '--disable-pip-version-check',
             '--timeout', '30', '--retries', '2', '-r', str(target / requirements)], cwd=target, timeout=1800)
        report = doctor(target)
        if not report['ready_search'] or not report['ready_pdf']:
            raise ValueError('安装后检查未通过：' + json.dumps(report, ensure_ascii=False))
        paths = generate_plists(target, include_update=profile == 'full' and report['ready_update'])
        state.update(report, status='complete', plists=[str(path) for path in paths],
                     endpoint='http://127.0.0.1:18063/mcp', activated=False)
        save_state(target, state)
        return state
    except Exception as error:
        state.update(status='failed', error=str(error), activated=False)
        save_state(target, state)
        raise


def activate(target, *, agents_dir=None):
    check_host()
    target = Path(target).expanduser().resolve()
    state = json.loads((target / 'verification/install/state.json').read_text())
    if state['status'] != 'complete':
        raise ValueError('只允许启用安装检查已通过的目录')
    if not port_free():
        raise ValueError('18063 端口已占用；未修改现有服务')
    agents_dir = Path(agents_dir) if agents_dir else Path.home() / 'Library/LaunchAgents'
    expected = [target / f'verification/install/{label}.plist' for label in LABELS]
    declared = state.get('plists')
    profile = state.get('profile')
    allowed = [str(path) for path in expected[:2 if profile == 'full' else 1]]
    if (profile not in ('full', 'search') or not isinstance(declared, list)
            or any(not isinstance(path, str) or path not in allowed for path in declared)
            or len(set(declared)) != len(declared) or str(expected[0]) not in declared):
        raise ValueError('安装状态中的服务清单无效；必须包含本安装的 MCP 服务且符合安装模式')
    sources = [path for path in expected if str(path) in declared]
    if any(path.is_symlink() or not path.is_file() for path in sources):
        raise ValueError('安装时生成的服务文件缺失或不是普通文件，拒绝部分启用')
    domain = f'gui/{os.getuid()}'
    for source in sources:
        destination = agents_dir / source.name
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f'已有服务文件，拒绝覆盖：{destination}')
        if run(['launchctl', 'print', f'{domain}/{source.stem}'], check=False).returncode == 0:
            raise ValueError(f'同名服务已加载，未修改：{source.stem}')
    report = doctor(target)
    if not report['ready_search'] or (expected[1] in sources and not report['ready_update']):
        raise ValueError('启用前复查未通过：' + json.dumps(report, ensure_ascii=False))
    agents_dir.mkdir(parents=True, exist_ok=True)
    created = []
    registered = []
    try:
        for source in sources:
            destination = agents_dir / source.name
            payload = source.read_bytes()
            with destination.open('xb') as stream:
                owner = os.fstat(stream.fileno())
                created.append((destination, owner.st_dev, owner.st_ino, payload))
                stream.write(payload)
            run(['launchctl', 'bootstrap', domain, str(destination)])
            registered.append(source.stem)
        state.update(activated=True, activation_status='registered', http_ready_verified=False,
                     login_restart_verified=False)
        save_state(target, state)
    except Exception:
        for label in reversed(registered):
            try:
                run(['launchctl', 'bootout', f'{domain}/{label}'], check=False)
            except (OSError, subprocess.SubprocessError):
                pass
        for destination, device, inode, payload in created:
            try:
                current = destination.lstat()
                if (not destination.is_symlink() and (current.st_dev, current.st_ino) == (device, inode)
                        and destination.read_bytes() == payload):
                    destination.unlink()
            except OSError:
                pass
        raise
    return {'activated': True, 'activation_status': 'registered', 'domain': domain,
            'labels': registered, 'http_ready_verified': False, 'login_restart_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--python', type=Path)
    parser.add_argument('--profile', choices=('full', 'search'), default='full')
    parser.add_argument('--obsidian-vault', type=Path)
    parser.add_argument('--soffice', type=Path)
    parser.add_argument('--treasury-root', type=Path)
    parser.add_argument('--doctor', action='store_true')
    parser.add_argument('--activate', action='store_true')
    args = parser.parse_args()
    try:
        if args.doctor:
            if args.archive or args.activate:
                parser.error('--doctor 不与 --archive / --activate 同用')
            result = doctor(args.target)
        elif args.archive:
            result = install(args.archive, args.target, python=args.python, profile=args.profile,
                             obsidian_vault=args.obsidian_vault, soffice=args.soffice,
                             treasury_root=args.treasury_root)
            if args.activate:
                result['activation'] = activate(args.target)
        elif args.activate:
            result = activate(args.target)
        else:
            parser.error('安装需要 --archive；已有安装可用 --doctor 或 --activate')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not args.doctor or result['ready_search'] else 1
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({'status': 'failed', 'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
