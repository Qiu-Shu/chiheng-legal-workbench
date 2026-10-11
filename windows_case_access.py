"""Local-only Windows case access setup and isolated stdio entry. Never logs secrets."""
import argparse
import getpass
import importlib.util
import json
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parent
CASE_SCRIPTS = ROOT / 'vendor/treasury/sources/legal-tools/人民法院案例库MCP/scripts'


def access_path():
    return ROOT / 'private/case-access.env'


def load_client():
    spec = importlib.util.spec_from_file_location('_windows_case_client', CASE_SCRIPTS / 'client.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def save_local(value):
    """Hidden local input only; replace safely after validation, preserving old file on failure."""
    import windows_private
    module = load_client()
    module._validate_token(value)
    if module._is_expired(value):
        raise module.TokenExpiredError()
    destination = access_path()
    windows_private.private_directory(destination.parent, create=True)
    try:
        os.close(windows_private.open_file(destination, private=True))
    except FileNotFoundError:
        pass
    temporary = destination.parent / ('.case-' + uuid.uuid4().hex)
    try:
        fd = windows_private.open_file(temporary, private=True, writable=True, create=True, exclusive=True)
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as output:
            output.write('RMFYALK_TOKEN=' + json.dumps(value, ensure_ascii=True) + '\n')
            output.flush()
            os.fsync(output.fileno())
        module._read_bindings(temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def load_server():
    from importlib.metadata import version
    from mcp.server.fastmcp import FastMCP
    if version('mcp') != '1.28.0' or not callable(FastMCP):
        raise ValueError('Requires isolated MCP 1.28.0')
    client = load_client()
    sys.modules['client'] = client
    sys.path.insert(0, str(CASE_SCRIPTS))
    import server
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--save-local', action='store_true')
    parser.add_argument('--status', action='store_true')
    args = parser.parse_args()
    try:
        if os.name != 'nt':
            raise ValueError('Native Windows only')
        expected = ROOT / '.venv-mcp1/Scripts/python.exe'
        if os.path.normcase(os.path.abspath(sys.executable)) != os.path.normcase(str(expected)):
            raise ValueError('Use this installation .venv-mcp1 interpreter')
        os.environ.pop('RMFYALK_TOKEN', None)
        if args.save_local:
            if not sys.stdin.isatty():
                raise ValueError('Interactive console required; input must not be echoed')
            value = getpass.getpass('本机登录后输入认证值（不回显）：')
            save_local(value)
            print('已保存。仍需当前 MCP 完成认证、一条检索及对应正文三步验证。')
        elif args.status:
            module = load_client()
            try:
                module.client.token
                state = 'saved_pending_auth_search_body'
            except module.CredentialError as error:
                state = error.kind
            except module.TokenExpiredError:
                state = 'expired'
            print(json.dumps({'case_access': state, 'online_verified': False}))
        else:
            load_server().mcp.run(transport='stdio')
        return 0
    except Exception:
        print('案例库入口未完成。请检查本安装的独立环境、私有权限与本机认证；未输出认证内容。', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
