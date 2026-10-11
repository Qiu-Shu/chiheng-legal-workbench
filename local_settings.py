"""Paths shared across portable installs; machine settings are never distributed."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys

MACHINE_CONFIG = Path(__file__).resolve().parent / 'config/local-machine.json'
MACHINE_KEYS = {'obsidian_target', 'treasury_root', 'soffice', 'pdf_python'}


def resolve_config_path(config_path, value):
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ValueError('配置路径必须为非空字符串')
    path = Path(value).expanduser()
    return Path(os.path.abspath(path if path.is_absolute() else Path(config_path).parent / path))


def load_machine_config(config_path=MACHINE_CONFIG):
    path = Path(config_path)
    if not path.exists():
        return {}
    settings = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(settings, dict) or settings.keys() - MACHINE_KEYS
            or any(not isinstance(value, str) or not value.strip() for value in settings.values())):
        raise ValueError('local-machine.json 只支持四项非空路径：' + ', '.join(sorted(MACHINE_KEYS)))
    return settings


def configured_path(key, config_path=MACHINE_CONFIG):
    value = load_machine_config(config_path).get(key)
    return resolve_config_path(config_path, value) if value is not None else None


def _executable(path, name):
    path = Path(path).expanduser()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError(name + ' 配置的执行文件不可用：' + str(path))
    return path


def resolve_soffice(explicit=None):
    selected = explicit or os.environ.get('MENGLU_SOFFICE') or configured_path('soffice')
    if selected is not None:
        return _executable(selected, 'LibreOffice')
    selected = shutil.which('soffice.exe' if sys.platform == 'win32' else 'soffice')
    if not selected and sys.platform == 'win32':
        candidates = [Path(os.environ[key]) / 'LibreOffice/program/soffice.exe'
                      for key in ('ProgramFiles', 'ProgramFiles(x86)') if os.environ.get(key)]
        selected = next((path for path in candidates if path.is_file()), 'soffice.exe')
    elif not selected:
        selected = '/Applications/LibreOffice.app/Contents/MacOS/soffice'
    return _executable(selected, 'LibreOffice；请安装或设置 soffice / MENGLU_SOFFICE')


def resolve_pdf_python(explicit=None):
    selected = explicit or os.environ.get('MENGLU_PDF_PYTHON') or configured_path('pdf_python')
    if selected is not None:
        return _executable(selected, 'PDF Python')
    if all(importlib.util.find_spec(name) is not None for name in ('pypdf', 'pdfplumber')):
        return Path(sys.executable)
    raise ValueError('PDF依赖不可用：请安装 requirements.lock.txt 或配置 pdf_python / MENGLU_PDF_PYTHON')


def require_treasury(root=None):
    root = root if root is not None else configured_path('treasury_root')
    if root is None:
        raise ValueError('国家库客户端未配置：请在 local-machine.json 设置 treasury_root')
    root = Path(root)
    if not (root / 'sources/legal-tools/国家法律法规数据库MCP/scripts/client.py').is_file():
        raise ValueError('treasury_root 中缺少国家库 client.py：' + str(root))
    return root
