"""Fixed local browser adapter. Unknown/stale process state requires manual review."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent
CDP = 'http://127.0.0.1:19224'
PATCH_HASHES = {'cli.js': '3f496cf5b832ae3e83246d87da82617060d2491f041b773b1ab4360d5bc5fc5d',
                'daemon.js': '22c9ebbf57ff69be90b1491d6a7e2622968755d4c7d00531504961cd8078bb10'}


def node_path(root):
    return Path(root) / 'runtime/node/node-v22.23.3-win-x64/node.exe'


def package_path(root):
    return Path(root) / 'vendor/bb-browser/node_modules/bb-browser'


def verify_source(package):
    for name, expected in PATCH_HASHES.items():
        path = Path(package) / 'dist' / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Browser patch identity mismatch')


def verify_payload(root):
    verify_source(package_path(root))


def browser_env(root):
    env = {key: value for key, value in os.environ.items()
           if not any(word in key.upper() for word in ('BB_BROWSER', 'PINIX', 'NODE_OPTIONS', 'NODE_PATH'))
           and key.upper() not in {'PYTHONPATH', 'PYTHONHOME', 'RMFYALK_TOKEN'}}
    env.update(BB_BROWSER_HOME=str(Path(root) / 'private/bb-state'), BB_BROWSER_CDP_URL=CDP)
    env['PATH'] = str(node_path(root).parent) + os.pathsep + env.get('PATH', '')
    return env


def offline_args(args):
    return len(args) == 1 and args[0] in {'--help', '-h', '--version', '-v'}


def validate_args(args):
    if any(item.split('=')[0] in {'--hub', '--hub-token', '--cdp-host', '--cdp-port',
                                '--host', '--port', '--token', '--profile', '--openclaw'} for item in args):
        raise ValueError('Connection override refused')
    if 'daemon' in args and args not in (['daemon', 'status'], ['daemon', 'start']):
        raise ValueError('Raw daemon control disabled; manual identity review required')
    # Match positional routing in the hash-pinned 0.14.2 CLI, including global options.
    value_options = {'--jq', '--port', '--depth', '-d', '--selector', '-s', '--days',
                     '--id', '--tab', '--domain', '--args', '--since', '--method',
                     '--status', '--type', '--filter', '--limit', '--request-id'}
    positional, skip = [], False
    for item in args:
        if skip:
            skip = False
        elif item in value_options:
            skip = True
        elif not item.startswith('-'):
            positional.append(item)
    if positional[:2] in (['site', 'recommend'], ['site', 'update']):
        raise ValueError('site recommend/update is pending Windows migration; route refused')
    if positional[:1] == ['history']:
        raise ValueError('history uses Unix shell; Windows support pending')


def powershell(script, *, env=None):
    exe = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = subprocess.run([str(exe), '-NoProfile', '-NonInteractive', '-Command', script],
                            env=env, capture_output=True, text=True, encoding='utf-8',
                            errors='replace', timeout=20, check=True)
    return json.loads(result.stdout)


def process_info(pid):
    if type(pid) is not int or pid <= 0:
        raise ValueError('Invalid process identity')
    return powershell("$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new(); "
        f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={pid}'; "
        "if (!$p) {throw 'Process absent'}; "
        "$ports=@(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | "
        "Where-Object {$_.OwningProcess -eq $p.ProcessId} | "
        "ForEach-Object { @{address=$_.LocalAddress;port=$_.LocalPort} }); "
        "@{pid=[int]$p.ProcessId;exe=$p.ExecutablePath;command=$p.CommandLine;"
        "created=$p.CreationDate.ToUniversalTime().ToString('o');listeners=$ports} | ConvertTo-Json -Depth 4")


def private_json(path):
    import windows_private
    with os.fdopen(windows_private.open_file(path, private=True), 'rb') as source:
        data = source.read(65537)
    if len(data) > 65536:
        raise ValueError('Oversized private state')
    return json.loads(data)


def write_private(path, data):
    import windows_private
    fd = windows_private.open_file(path, private=True, create=True, exclusive=True, writable=True)
    with os.fdopen(fd, 'w', encoding='utf-8') as output:
        json.dump(data, output)


def same_process(expected, actual, port):
    if any(expected.get(key) != actual.get(key) for key in ('pid', 'exe', 'command', 'created')):
        raise ValueError('Stale or unknown process identity; manual review required')
    if {'address': '127.0.0.1', 'port': port} not in actual.get('listeners', []):
        raise ValueError('Dedicated local port ownership not verified')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('Browser probe redirect refused')


def fetch_json(url):
    # No proxy is used for the dedicated local connection; system settings untouched.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(url, timeout=10) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError('Oversized browser metadata')
    return json.loads(raw)


def check_browser(root):
    root = Path(root)
    expected = private_json(root / 'private/browser-owner.json')
    same_process(expected, process_info(expected['pid']), 19224)
    data = fetch_json(CDP + '/json/version')
    endpoint = urllib.parse.urlsplit(data.get('webSocketDebuggerUrl', ''))
    if endpoint.scheme != 'ws' or endpoint.hostname != '127.0.0.1' or endpoint.port != 19224:
        raise ValueError('Dedicated CDP identity not verified')
    return data


def check_daemon(root):
    root = Path(root)
    state = root / 'private/bb-state/daemon.json'
    owner = root / 'private/daemon-owner.json'
    if not state.exists():
        if owner.exists():
            raise ValueError('Stale daemon ownership state; manual review required')
        return None
    if not owner.exists():
        raise ValueError('Unknown daemon state; manual identity review required')
    info = private_json(state)
    if info.get('host') != '127.0.0.1' or info.get('cdpPort') != 19224:
        raise ValueError('Unexpected daemon endpoint')
    expected = private_json(owner)
    if info.get('pid') != expected.get('pid'):
        raise ValueError('Unknown daemon PID')
    same_process(expected, process_info(info['pid']), info['port'])
    return info


def remember_daemon(root):
    root = Path(root)
    info = private_json(root / 'private/bb-state/daemon.json')
    actual = process_info(info['pid'])
    command = [str(node_path(root)), str(package_path(root).resolve() / 'dist/daemon.js'),
               '--no-chrome', '--cdp-host', '127.0.0.1', '--cdp-port', '19224']
    if (info.get('host') != '127.0.0.1' or info.get('cdpPort') != 19224 or
            os.path.normcase(actual['exe']) != os.path.normcase(command[0]) or
            actual['command'] != subprocess.list2cmdline(command)):
        raise ValueError('New daemon identity not verified; manual review required')
    same_process(actual, actual, info['port'])
    write_private(root / 'private/daemon-owner.json', actual)


def maintained_browser(root, explicit=None):
    candidates = [Path(explicit)] if explicit else [Path(os.environ.get(key, '')) / relative
        for key in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA')
        for relative in ('Google/Chrome/Application/chrome.exe', 'Microsoft/Edge/Application/msedge.exe')
        if os.environ.get(key)]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        env = browser_env(root)
        env['CHIHENG_BROWSER_EXE'] = str(candidate.absolute())
        info = powershell("$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new(); "
            "$f=Get-Item -LiteralPath $env:CHIHENG_BROWSER_EXE; $s=Get-AuthenticodeSignature -LiteralPath $f.FullName; "
            "@{status=[string]$s.Status;signer=$s.SignerCertificate.Subject;product=$f.VersionInfo.ProductName;"
            "version=$f.VersionInfo.ProductVersion} | ConvertTo-Json", env=env)
        chrome = info.get('product') == 'Google Chrome' and 'Google LLC' in info.get('signer', '')
        edge = info.get('product') == 'Microsoft Edge' and 'Microsoft Corporation' in info.get('signer', '')
        if info.get('status') != 'Valid' or not (chrome or edge):
            continue
        if chrome:
            data = fetch_json('https://versionhistory.googleapis.com/v1/chrome/platforms/win64/channels/stable/versions?pageSize=1')
            latest = data['versions'][0]['version']
        else:
            data = fetch_json('https://edgeupdates.microsoft.com/api/products?view=enterprise')
            latest = max((r['ProductVersion'] for p in data if p['Product'] == 'Stable'
                          for r in p['Releases'] if r['Platform'] == 'Windows' and r['Architecture'] == 'x64'),
                         key=lambda value: tuple(map(int, value.split('.'))))
        if tuple(map(int, info['version'].split('.'))) < tuple(map(int, latest.split('.'))):
            raise ValueError('Browser update required; installed version older than current stable')
        return candidate.absolute()
    raise ValueError('pending: no signed maintained Chrome/Edge verified')


def start_browser(root, explicit=None):
    from scripts.install_windows import port_free
    import windows_private
    root = Path(root)
    if not port_free(19224):
        raise ValueError('Port 19224 occupied; existing browser unchanged')
    # Never repurpose an old profile or overwrite a stale ownership record.
    profile = root / 'private/browser-profile'
    if profile.exists() or (root / 'private/browser-owner.json').exists():
        raise ValueError('Existing browser profile/state requires manual identity review')
    check_daemon(root)
    browser = maintained_browser(root, explicit)
    windows_private.private_directory(root / 'private', create=True)
    windows_private.private_directory(root / 'private/bb-state', create=True)
    windows_private.private_directory(profile, create=True)
    command = [str(browser), '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=19224',
               '--user-data-dir=' + str(profile), '--no-first-run', '--no-default-browser-check', 'about:blank']
    process = subprocess.Popen(command, env=browser_env(root), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        if process.poll() is not None:
            break
        actual = process_info(process.pid)
        if {'address': '127.0.0.1', 'port': 19224} in actual.get('listeners', []):
            if (os.path.normcase(actual['exe']) != os.path.normcase(str(browser)) or
                    actual['command'] != subprocess.list2cmdline(command)):
                raise ValueError('Browser launch identity mismatch')
            write_private(root / 'private/browser-owner.json', actual)
            check_browser(root)
            return {'browser': 'dedicated_connected', 'all_commands_verified': False}
        time.sleep(0.2)
    raise ValueError('Dedicated browser pending; inspect its window; no process was killed')


def invoke(root, args):
    root = Path(root)
    validate_args(args)
    verify_payload(root)
    before = None
    if not offline_args(args):
        check_browser(root)
        before = check_daemon(root)
        if before is None:
            from scripts.install_windows import port_free
            if not port_free(19824):
                raise ValueError('Port 19824 occupied by an unknown service; no daemon launched')
    try:
        result = subprocess.run([str(node_path(root)), str(package_path(root) / 'dist/cli.js'), *args],
                                env=browser_env(root), cwd=root, timeout=120)
    except subprocess.TimeoutExpired:
        raise ValueError('Browser command timed out after 120 seconds; its CLI stopped. '
                         'Browser/daemon state needs manual identity review.') from None
    if not offline_args(args) and before is None and (root / 'private/bb-state/daemon.json').exists():
        remember_daemon(root)
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start-browser', action='store_true')
    parser.add_argument('--browser', type=Path)
    parser.add_argument('args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        if os.name != 'nt':
            raise ValueError('Native Windows required')
        if args.start_browser:
            print(json.dumps(start_browser(ROOT, args.browser)))
            return 0
        forwarded = args.args[1:] if args.args[:1] == ['--'] else args.args
        return invoke(ROOT, forwarded)
    except Exception as error:
        # Never expose daemon auth material or subprocess output in diagnostics.
        reason = str(error) if type(error) is ValueError else type(error).__name__
        print(json.dumps({'status': 'pending', 'reason': reason,
                          'message': '未接管或结束其他进程；请核对专用浏览器与本安装状态。'}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
