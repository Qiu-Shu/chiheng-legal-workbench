"""Install optional Windows adapters; component status never implies online readiness."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tomllib


class ComponentFailure(Exception):
    def __init__(self, stage, error):
        self.stage = stage
        self.error_type = type(error).__name__
        super().__init__(stage + ': ' + self.error_type)


def step(stage, action):
    try:
        return action()
    except Exception as error:
        raise ComponentFailure(stage, error) from None

NODE_ARCHIVE = 'node-v22.23.3-win-x64.zip'
NODE_HASH = '2b0ff57b049cda1bbcea2240eec20467018713c1efe1f7360c2681859b90ed71'
PNPM_HASH = '33dd0748f27e7916c4f1c8b6943461983e3453b06bbda6312a6280130b4881e5'
SDK_PROBE = '''
import json
from importlib.metadata import version
from mcp.server.fastmcp import FastMCP
assert version('mcp') == '1.28.0' and callable(FastMCP)
print(json.dumps(dict(sdk=version('mcp'), fastmcp=True)))
'''


def install_mcp1(bundle, target):
    from scripts.install_windows import run
    step('mcp1.venv', lambda: run([target / 'runtime/python/python.exe', '-X', 'utf8', '-m', 'venv', target / '.venv-mcp1'], timeout=180))
    python = target / '.venv-mcp1/Scripts/python.exe'
    step('mcp1.offline_pip', lambda: run([python, '-E', '-s', '-X', 'utf8', '-m', 'pip', 'install', '--disable-pip-version-check',
         '--no-index', '--find-links', bundle / 'runtime/wheels-mcp1', '--require-hashes',
         '-r', target / 'requirements-windows-mcp1.lock.txt'], cwd=target, timeout=1800))
    report = json.loads(step('mcp1.import', lambda: run([python, '-E', '-s', '-X', 'utf8', '-c', SDK_PROBE], cwd=target)).stdout)
    if report != {'sdk': '1.28.0', 'fastmcp': True}:
        raise ValueError('SDK1 import probe failed')
    return dict(status='installed_import_verified', **report, online_verified=False)


def extract_pnpm(archive, destination):
    from scripts.install_windows import _digest, _safe_name
    if _digest(archive)['sha256'] != PNPM_HASH:
        raise ValueError('pnpm archive hash mismatch')
    with tarfile.open(archive, 'r:gz') as source:
        members = source.getmembers()
        if len(members) > 2000 or sum(item.size for item in members) > 100 * 1024**2:
            raise ValueError('pnpm archive size refused')
        seen = set()
        for item in members:
            key = _safe_name(item.name.rstrip('/'))
            if key in seen or not (item.isdir() or item.isfile()) or not item.name.startswith('package/'):
                raise ValueError('Unsafe pnpm archive member')
            seen.add(key)
        destination.mkdir(parents=True, exist_ok=False)
        source.extractall(destination, filter='data')


def install_browser(bundle, target):
    from scripts.install_windows import extract_runtime
    from windows_browser import browser_env, node_path, verify_source, verify_payload
    step('browser.node_extract', lambda: extract_runtime(bundle / ('runtime/' + NODE_ARCHIVE), target / 'runtime/node',
                    expected_hash=NODE_HASH, required_entry='node-v22.23.3-win-x64/node.exe'))
    step('browser.pnpm_extract', lambda: extract_pnpm(bundle / 'runtime/pnpm-11.25.0.tgz', target / 'runtime/pnpm'))
    node = node_path(target)
    pnpm = target / 'runtime/pnpm/package/bin/pnpm.cjs'
    env = browser_env(target)
    def run(args, timeout=60):
        return subprocess.run([str(x) for x in args], cwd=target / 'vendor/bb-browser', env=env,
                              capture_output=True, text=True, encoding='utf-8', check=True, timeout=timeout)
    if run([node, '--version']).stdout.strip() != 'v22.23.3':
        raise ValueError('Node version mismatch')
    if run([node, pnpm, '--version']).stdout.strip() != '11.25.0':
        raise ValueError('pnpm version mismatch')
    source = target / 'vendor/bb-browser/package'
    verify_source(source)
    # Network dependency retrieval is explicit. Locked integrity and no lifecycle scripts.
    step('browser.frozen_dependencies', lambda: run([node, pnpm, 'install', '--frozen-lockfile', '--ignore-scripts', '--prod'], timeout=1800))
    installed = target / 'vendor/bb-browser/node_modules/bb-browser'
    if not installed.resolve().is_relative_to((target / 'vendor/bb-browser').resolve()):
        raise ValueError('Package resolved outside installation')
    from scripts.install_windows import _digest
    expected = {'cli.js': '72e9ec031a5fdf272d091d561b85a4a9a39aec8c7e0d458429cdc7ed8b506f59',
                'daemon.js': 'f1060b67efe59f5669604ef0b2f5ce1bab93470e0555875c4b90f16aa1e0014e'}
    for name, digest in expected.items():
        if _digest(installed / 'dist' / name)['sha256'] != digest:
            raise ValueError('Unexpected upstream browser source identity')
    for name in expected:
        shutil.copyfile(source / 'dist' / name, installed / 'dist' / name)
    verify_payload(target)
    if run([node, installed / 'dist/cli.js', '--version']).stdout.strip() != '0.14.2':
        raise ValueError('bb-browser version/import failed')
    return dict(status='installed_native_pending', dependencies='network_frozen_lock_ignore_scripts',
                browser='pending_supported_local_browser', all_commands_verified=False)


def connection_fragment(target):
    python = str(Path(target).absolute() / '.venv-mcp1/Scripts/python.exe')
    result = ''
    for name, relative in [('menglu_rmfyalk', 'windows_case_access.py'),
                           ('menglu_flk_npc', 'scripts/windows_flk_blocked.py')]:
        result += f'[mcp_servers.{name}]\ncommand = ' + json.dumps(python) + '\nargs = ' + json.dumps(
            ['-E', '-s', '-X', 'utf8', str(Path(target).absolute() / relative)], ensure_ascii=False) + '\n\n'
    return result


def host_conflicts(config):
    """Inspect only server names, never return or copy host values."""
    config = Path(config)
    if not config.exists():
        return []
    if config.stat().st_size > 1024 * 1024:
        raise ValueError('Host configuration too large for name check')
    with config.open('rb') as stream:
        names = tomllib.load(stream).get('mcp_servers', {})
    return sorted(set(names) & {'chiheng_legal', 'menglu_rmfyalk', 'menglu_flk_npc'})


def install_components(bundle, target):
    report = dict(ready_external=False, flk={'status': 'blocked', 'policy': 'FLK_ACCESS_BLOCK'},
                  case={'status': 'pending_local_login_and_auth_search_body'},
                  host={'status': 'manual_import_required'})
    for key, action in [('mcp1', install_mcp1), ('bb_browser', install_browser)]:
        try:
            report[key] = action(Path(bundle), Path(target))
        except Exception as error:
            # A child may inherit sensitive environment values: never persist raw output.
            report[key] = dict(status='failed', error_type=getattr(error, 'error_type', type(error).__name__),
                               stage=getattr(error, 'stage', key + '.setup'),
                               action='Review component files; no automatic repair or overwrite')
    destination = Path(target) / 'verification/install'
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'codex-external-mcp.toml').write_text(connection_fragment(target), encoding='utf-8')
    report['host'] = host_status()
    return report


def host_status():
    if os.name != 'nt':
        return {'status': 'pending_target_host_check'}
    try:
        conflicts = host_conflicts(Path.home() / '.codex/config.toml')
        return dict(status='conflict_no_overwrite' if conflicts else 'manual_import_required',
                    conflicting_names=conflicts)
    except Exception:
        return {'status': 'host_name_check_failed_manual_review'}


def doctor(target):
    from scripts.install_windows import run
    from windows_browser import node_path, package_path, verify_payload, browser_env
    target = Path(target)
    result = dict(ready_external=False, flk={'status': 'blocked', 'policy': 'FLK_ACCESS_BLOCK'},
                  case={'status': 'pending_local_login_and_auth_search_body'}, host=host_status())
    python = target / '.venv-mcp1/Scripts/python.exe'
    if not python.is_file():
        result['mcp1'] = {'status': 'missing'}
    else:
        try:
            probe = json.loads(run([python, '-E', '-s', '-X', 'utf8', '-c', SDK_PROBE], cwd=target).stdout)
            if probe != {'sdk': '1.28.0', 'fastmcp': True}:
                raise ValueError('Invalid SDK1 probe')
            result['mcp1'] = dict(status='installed_import_verified', **probe)
            local = json.loads(run([python, '-E', '-s', '-X', 'utf8', target / 'windows_case_access.py', '--status'], cwd=target).stdout)
            result['case']['local_file'] = local['case_access']
        except Exception as error:
            result['mcp1'] = dict(status='failed', error_type=type(error).__name__)
    if not node_path(target).is_file():
        result['bb_browser'] = {'status': 'missing'}
    else:
        try:
            verify_payload(target)
            version = subprocess.run([str(node_path(target)), str(package_path(target) / 'dist/cli.js'), '--version'],
                env=browser_env(target), capture_output=True, text=True, timeout=30, check=True).stdout.strip()
            if version != '0.14.2':
                raise ValueError('Unexpected browser version')
            result['bb_browser'] = dict(status='installed_native_pending', all_commands_verified=False)
        except Exception as error:
            result['bb_browser'] = dict(status='failed', error_type=type(error).__name__)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--host-config', type=Path)
    args = parser.parse_args()
    from scripts.install_windows import check_host
    check_host()
    print(json.dumps({'conflicting_names': host_conflicts(args.host_config)} if args.host_config else doctor(args.target),
                     ensure_ascii=False, indent=2))
