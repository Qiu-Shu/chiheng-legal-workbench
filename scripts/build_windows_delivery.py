"""Build a new personal Windows delivery; never mutate the live library or old ZIPs."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from library_transfer import _digest, export_library, verify_archive
from scripts.install_windows import allowed_payload, reject_link, verify_bundle

EXCLUDED = {'__pycache__', '.venv', '.python-deps', 'node_modules', '.DS_Store',
            'session.json', 'manifest.hearing.json', 'cookies.json', 'local-machine.json'}


def safe_source(path, relative):
    if any(part in EXCLUDED or (part.startswith('.') and part not in {'.codex-plugin', '.mcp.json'})
           for part in Path(relative).parts) or '/behavior/runs/' in '/' + relative:
        return False
    if path.suffix in {'.pyc', '.pyo'}:
        return False
    return True


def tree_files(folder, prefix):
    selected = {}
    for directory, dirs, names in os.walk(folder, followlinks=False):
        for name in dirs[:]:
            path = Path(directory) / name
            if not safe_source(path, path.relative_to(folder).as_posix()):
                dirs.remove(name)
            else:
                reject_link(path)
        for name in names:
            path = Path(directory) / name
            relative = path.relative_to(folder).as_posix()
            if not safe_source(path, relative):
                continue
            reject_link(path)
            destination = prefix + '/' + relative
            if path.name == '.mcp.json' and destination != 'plugins/chiheng-legal/.mcp.json':
                continue
            try:
                allowed_payload(destination)
            except ValueError:
                continue
            selected[destination] = path
    return selected


def select_source(root):
    root = Path(root)
    selected = {}
    for path in [*root.glob('*.py'), *root.glob('requirements*.txt')]:
        reject_link(path)
        selected['source/' + path.name] = path
    for directory in ('scripts', 'tests', 'docs'):
        selected.update(tree_files(root / directory, 'source/' + directory))
    for name in ('upstream/original/LICENSE', 'upstream/original/NOTICE'):
        if (root / name).exists():
            selected['source/' + name] = root / name
    return selected


def copy_checked(source, target, expected):
    source, target = Path(source), Path(target)
    if not stat.S_ISREG(reject_link(source).st_mode) or _digest(source) != expected:
        raise ValueError('Source changed before copy: ' + str(source))
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open('rb') as original, target.open('xb') as output:
        shutil.copyfileobj(original, output)
    if _digest(target) != expected or _digest(source) != expected:
        raise ValueError('Source changed during copy: ' + str(source))


def build(root, output, copies, runtime, dev_wheels):
    root, output, copies = map(lambda p: Path(p).resolve(), (root, output, copies))
    output.mkdir(parents=True, exist_ok=True)
    delivery = Path(tempfile.mkdtemp(prefix='chiheng-windows10-' + datetime.now().strftime('%Y-%m-%d-'), dir=output))
    selected = select_source(root)
    for directory in ('skills', 'plugins', 'memory'):
        selected.update(tree_files(copies / directory, directory))
    selected.update(tree_files(root / 'vendor', 'vendor'))
    selected.update(tree_files(copies / 'vendor', 'vendor'))
    selected['install.cmd'] = root / 'scripts/install_windows.cmd'
    selected['windows_bootstrap.ps1'] = root / 'scripts/windows_bootstrap.ps1'
    for name in ('python-3.13.16-amd64.zip', 'node-v22.23.3-win-x64.zip', 'pnpm-11.25.0.tgz'):
        selected['runtime/' + name] = Path(runtime) / name
    for directory in ('wheels-main', 'wheels-mcp1'):
        selected.update(tree_files(Path(runtime) / directory, 'runtime/' + directory))
    selected.update(tree_files(Path(dev_wheels), 'runtime/wheels-dev'))
    selected['docs/runtime-sources.md'] = Path(runtime) / 'runtime-sources.md'
    selected['docs/windows10-migration-guide.md'] = root / 'docs/windows10-migration-guide.md'
    selected.update(tree_files(copies / 'docs', 'docs'))
    if 'plugins/chiheng-legal/.mcp.json' not in selected:
        raise ValueError('Required plugin connection manifest missing')
    before = {name: _digest(path) for name, path in selected.items()}
    with tempfile.TemporaryDirectory(prefix='windows-delivery-', dir=delivery) as temp:
        bundle = Path(temp) / '持衡 Windows10 个人迁移包'
        bundle.mkdir()
        for name, source in selected.items():
            allowed_payload(name)
            copy_checked(source, bundle / name, before[name])
        archive = bundle / 'data/personal-public-library.zip'
        archive.parent.mkdir()
        export_library(root, archive)
        library = verify_archive(archive)
        skill_zip = bundle / 'source/dist/cn-litigation-redteam.zip'
        skill_zip.parent.mkdir()
        skill_root = bundle / 'skills/cn-litigation-redteam'
        with zipfile.ZipFile(skill_zip, 'x', zipfile.ZIP_DEFLATED) as out:
            for path in sorted(skill_root.rglob('*')):
                if path.is_file():
                    out.write(path, 'cn-litigation-redteam/' + path.relative_to(skill_root).as_posix())
        files = {path.relative_to(bundle).as_posix(): _digest(path)
                 for path in sorted(bundle.rglob('*')) if path.is_file()}
        manifest = dict(schema_version=1, built_at=datetime.now(timezone.utc).isoformat(),
                        purpose='personal migration; Windows native acceptance pending', files=files,
                        library=library, source_files=before)
        (bundle / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        verify_bundle(bundle)
        if any(_digest(path) != before[name] for name, path in selected.items()):
            raise ValueError('Source changed before publication')
        target = delivery / '持衡-Windows10-x64-个人迁移总包.zip'
        with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED) as out:
            for path in sorted(bundle.rglob('*')):
                if path.is_file():
                    out.write(path, bundle.name + '/' + path.relative_to(bundle).as_posix())
        (delivery / 'SHA256.txt').write_text(_digest(target)['sha256'] + '  ' + target.name + '\n', encoding='utf-8')
        shutil.copyfile(root / 'docs/windows10-migration-guide.md', delivery / '先读我-迁移说明.md')
        (delivery / '内容清单.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {'directory': str(delivery), 'zip': str(target), **_digest(target), 'files': len(files), 'library': library}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--copies', type=Path, required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--dev-wheels', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.root, args.output, args.copies, args.runtime, args.dev_wheels), ensure_ascii=False, indent=2))
