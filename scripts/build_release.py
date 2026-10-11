"""Build portable source packages without credentials, corpus or virtualenv."""
import hashlib
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT.parents[1] / 'outputs'


def archive(folder, target):
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as out:
        for file in sorted(folder.rglob('*')):
            if (file.is_file() and '__pycache__' not in file.parts
                    and file.name != 'local-machine.json'):
                out.write(file, str(Path(folder.name) / file.relative_to(folder)))


def build_source_archive(root, target):
    selected = [*root.glob('*.py'), *root.glob('requirements*.txt')]
    for directory in ('scripts', 'config', 'tests'):
        selected += [file for file in (root/directory).rglob('*')
                     if file.is_file() and '__pycache__' not in file.parts and not file.name.startswith('.')
                     and file.name != 'local-machine.json']
    selected += [root/'docs'/name for name in ('local-operations.md', 'shared-library-contract.md',
                  'chatgpt-private-connection.md', 'source-scheduler-update.md', 'upstream-catalog-gap.md',
                  'official-article-progress.md', 'basic-laws-progress.md', 'supporting-rules-progress.md',
                  'supporting-format-recovery.md', 'official-monitor-progress.md',
                  'law-discovery-jilin-progress.md', 'jilin-rule-layout-progress.md',
                  'direct-ingest-pdf-progress.md', 'attachment-recovery-progress.md', 'multiple-pdf-progress.md',
                  'mac-migration-guide.md', 'mac-portability-audit.md', 'core-continuation-progress.md')]
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as out:
        for file in sorted(selected):
            out.write(file, str(Path('menglu-shared-library') / file.relative_to(root)))


def main():
    OUTPUT.mkdir(exist_ok=True)
    archive(ROOT/'skills/cn-litigation-redteam', OUTPUT/'cn-litigation-redteam-experimental-2026-09-27.zip')
    archive(ROOT/'plugins/chiheng-legal', OUTPUT/'chiheng-legal-plugin-2026-09-27.zip')
    archive(Path.home()/'.codex/skills/menglu-legal-treasury', OUTPUT/'menglu-legal-treasury-updated-skill-2026-09-27.zip')
    build_source_archive(ROOT, OUTPUT/'menglu-shared-library-source-2026-09-27.zip')
    shutil.copy2(OUTPUT/'cn-litigation-redteam-experimental-2026-09-27.zip', ROOT/'dist/cn-litigation-redteam.zip')
    for source, name in [('verification/scrapling-smoke.json', 'scrapling-smoke-2026-09-27.json'),
                     ('verification/source-probes.json', 'source-probes-2026-09-27.json'),
                     ('docs/local-operations.md', 'chiheng-local-operations.md')]:
        shutil.copy2(ROOT/source, OUTPUT/name)
    files = ['cn-litigation-redteam-experimental-2026-09-27.zip', 'chiheng-legal-plugin-2026-09-27.zip',
         'scrapling-smoke-2026-09-27.json', 'source-probes-2026-09-27.json', 'chiheng-local-operations.md']
    manifest = {'built_at': datetime.now(timezone.utc).isoformat(),
            'files': {name: hashlib.sha256((OUTPUT/name).read_bytes()).hexdigest() for name in files}}
    (OUTPUT/'chiheng-delivery-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
