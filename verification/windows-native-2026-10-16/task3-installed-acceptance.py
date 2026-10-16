"""One-shot acceptance harness; run with the new installation as cwd/interpreter."""
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from unittest.mock import patch

target = Path.cwd().resolve()
assert target.name == '持衡运行 02'
assert Path(sys.executable).is_relative_to(target)
assert Path(sys.base_prefix).resolve() == target / 'runtime/python'
sys.path.insert(0, str(target))
output = target / 'verification/acceptance'
output.mkdir(exist_ok=True)
forbidden = (Path(__file__).resolve().parents[2], target.with_name('持衡运行 01'),
             Path.home() / '.codex/config.toml')


def audit(event, args):
    if event != 'open' or not isinstance(args[0], (str, bytes, os.PathLike)):
        return
    path = Path(os.fsdecode(args[0])).absolute()
    if any(path == root or path.is_relative_to(root) for root in forbidden):
        raise AssertionError('Acceptance must not read old source/install/host configuration')


sys.addaudithook(audit)
phase = sys.argv[1]
result = {'phase': phase, 'target': str(target), 'old_source_install_host_reads_blocked': True}

if phase == 'environment':
    from importlib.metadata import distribution, version
    sdk1 = Path(sys.prefix).name == '.venv-mcp1'
    lock = target / ('requirements-windows-mcp1.lock.txt' if sdk1 else 'requirements-windows.lock.txt')
    requirements = re.findall(r'^([\w.-]+)(?:\[[^\]]+\])?==([^\s]+)', lock.read_text(), re.M)
    assert len(requirements) == len([line for line in lock.read_text().splitlines()
                                     if line.strip() and not line.startswith('#')])
    for name, expected in requirements:
        assert version(name) == expected, name
        assert Path(distribution(name).locate_file('')).resolve().is_relative_to(Path(sys.prefix)), name
    import mcp
    assert Path(mcp.__file__).resolve().is_relative_to(Path(sys.prefix))
    if sdk1:
        from mcp.server.fastmcp import FastMCP
        assert callable(FastMCP)
    else:
        from mcp.server.mcpserver import MCPServer
        assert callable(MCPServer)
        assert version('reportlab') == '4.4.9'
    result.update(environment='mcp1' if sdk1 else 'main', locked_packages=len(requirements),
                  mcp=version('mcp'), python=sys.version, executable=sys.executable,
                  base_prefix=sys.base_prefix, mcp_module=mcp.__file__)
    phase += '-mcp1' if sdk1 else '-main'

elif phase == 'data':
    from library_transfer import _digest, _content_info
    from legal_store import LegalStore
    import legal_mcp
    manifest = json.loads((target / 'manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['files'].items():
        assert _digest(target / name) == expected, name
    content = _content_info(target)
    for key, value in content.items():
        assert manifest[key] == value, key
    cards = fragments = searches = 0
    store = LegalStore(target / 'data/legal.sqlite3', readonly=True)
    try:
        for (version_id,) in store.db.execute('SELECT version_id FROM versions ORDER BY version_id'):
            original = store.detail(version_id)
            fragment = legal_mcp.get_law_fragment(version_id)
            assert fragment['found'] and fragment['text'] == original['text'][:3000]
            fragments += 1
            card = fragment['citation']
            for key in ('version_id', 'source_url', 'review_state', 'availability'):
                assert card[key] == original[key], (version_id, key)
            assert card['text_sha256'] == hashlib.sha256(original['text'].encode()).hexdigest()
            assert card['review_at_use_required'] and not card['legal_applicability_verified']
            assert isinstance(card['missing_fields'], list)
            cards += 1
            hits = legal_mcp.search_law(original['title'], include_quarantine=True, limit=100)['results']
            assert any(row['version_id'] == version_id for row in hits)
            searches += 1
    finally:
        store.close()
    inventory = legal_mcp.public_corpus_inventory()
    assert inventory['law_versions'] == 2190 and inventory['text_units'] == 77809
    assert inventory['review_state'] == 'unverified_mirror' and not inventory['coverage_complete']
    result.update(payloads=len(manifest['files']), cards=cards, fragments=fragments,
                  searches=searches, **content, inventory=inventory)

elif phase == 'doctor':
    import windows_external
    from scripts.install_windows import doctor
    with patch.object(windows_external, 'host_status', return_value={'status': 'not_checked_scope_no_host_config_read'}):
        report = doctor(target)
    assert all(report[key] for key in ('ready_search', 'ready_pdf', 'ready_mock_hearing'))
    assert not report['errors']
    assert report['external']['mcp1']['status'] == 'installed_import_verified'
    result.update(report)

elif phase in ('create', 'resume', 'reopen'):
    import windows_private
    from mock_hearing import create_session, append_turn, load_session, ROLES, STAGES
    case = target / 'private/acceptance-synthetic'
    if phase == 'create':
        windows_private.private_directory(target / 'private', create=True)
        windows_private.private_directory(case, create=True)
        material = case / '合成材料.txt'
        material.write_text('仅用于隔离安装验收的虚构材料。', encoding='utf-8')
        packet = dict(case_id='installation-synthetic', procedure='civil_first_instance',
                      our_role='plaintiff', synthetic=True, human_review=None,
                      materials=[dict(id='M1', relative_path=material.name,
                                      sha256=hashlib.sha256(material.read_bytes()).hexdigest())])
        create_session(case, packet)
        session = append_turn(case, dict(case_id=packet['case_id'], stage='issues', role='moderator',
            text='合成陈述。', material_ids=['M1'], source_cards=[], unresolved=['仅为验收，尚未法律核验。']))
        assert len(session['turns']) == 1
    else:
        session = load_session(case)
        previous = json.loads((output / ('create.json' if phase == 'resume' else 'resume.json')).read_text(encoding='utf-8'))
        assert hashlib.sha256((case / 'session.json').read_bytes()).hexdigest() == previous['session_sha256']
        if phase == 'resume':
            assert len(session['turns']) == 1
            for stage in STAGES:
                for role in sorted(ROLES[stage]):
                    if stage == 'issues' and role == 'moderator':
                        continue
                    session = append_turn(case, dict(case_id=session['case_id'], stage=stage, role=role,
                        text='合成陈述。', material_ids=['M1'], source_cards=[], unresolved=['仅为验收，尚未法律核验。']))
        assert session['completed'] and len(session['turns']) == 11
    assert session['synthetic'] and session['human_review'] is None
    result.update(case=str(case), turns=len(session['turns']), structural_completed=session['completed'],
                  session_sha256=hashlib.sha256((case / 'session.json').read_bytes()).hexdigest())
else:
    raise ValueError('Unknown acceptance phase')

(output / (phase + '.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
