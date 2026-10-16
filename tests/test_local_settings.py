import importlib.util
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch


class LocalSettingsTests(unittest.TestCase):
    def fixture(self, root):
        from legal_store import LegalStore
        (root / 'config').mkdir()
        LegalStore(root / 'data/legal.sqlite3').close()
        (root / 'data/index.json').write_text('{"laws":{"test":{"title":"Test law","provisions":[]}}}')
        (root / 'config/shared-library.json').write_text('{"corpus_path":"../data/index.json"}')
        (root / 'config/sources.json').write_text('{"sources":[]}')
        (root / 'config/coverage-targets.yaml').write_text('{"regions":[],"source_categories":[]}')

    def test_mcp_reads_relocated_relative_corpus_from_unrelated_cwd(self):
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            (root / 'legal_mcp.py').write_bytes((project / 'legal_mcp.py').read_bytes())
            code = 'import sys; sys.path[:0] = ' + repr([str(root), str(project)]) + '; import legal_mcp; print(legal_mcp.corpus.inventory())'
            result = subprocess.run([sys.executable, '-c', code], cwd='/', capture_output=True, text=True, check=True)
            self.assertIn("'available': True", result.stdout)

    def test_integrity_reads_relocated_relative_corpus(self):
        from scripts import integrity_report
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            with patch('builtins.print'):
                report = integrity_report.main(root=root)
            self.assertTrue(report['shared_offline_corpus']['available'])

    def test_obsidian_reads_relocated_relative_corpus(self):
        from scripts import export_obsidian_library as exporter
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            target = root / 'note.md'
            with patch.object(exporter, 'ROOT', root):
                exporter.export(target)
            self.assertIn('离线镜像可用：True', target.read_text())

    def test_release_import_is_inert_and_all_archives_exclude_machine_config(self):
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'workspace/project'
            (root / 'scripts').mkdir(parents=True)
            script = root / 'scripts/build_release.py'
            script.write_bytes((project / 'scripts/build_release.py').read_bytes())
            result = subprocess.run([sys.executable, '-c',
                'import runpy, sys; runpy.run_path(sys.argv[1], run_name="test")', str(script)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((Path(tmp) / 'outputs').exists())
            from scripts.build_release import archive
            config = root / 'config'
            config.mkdir()
            (config / 'local-machine.json').write_text('{"secret":"machine path"}')
            (config / 'shared-library.json').write_text('{}')
            target = Path(tmp) / 'test.zip'
            archive(root, target)
            import zipfile
            with zipfile.ZipFile(target) as out:
                self.assertFalse(any('local-machine.json' in name for name in out.namelist()))
                self.assertIn('project/config/shared-library.json', out.namelist())

    def settings(self):
        self.assertIsNotNone(importlib.util.find_spec('local_settings'), '缺少机器配置与路径解析模块')
        import local_settings
        return local_settings

    def test_source_package_and_data_selection_exclude_machine_config(self):
        from scripts.build_release import build_source_archive
        from library_transfer import _source_files
        import zipfile
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'source.zip'
            build_source_archive(project, target)
            with zipfile.ZipFile(target) as out:
                self.assertFalse(any(name.endswith('/local-machine.json') for name in out.namelist()))
                self.assertIn('menglu-shared-library/local_settings.py', out.namelist())
                self.assertIn('menglu-shared-library/requirements-dev.txt', out.namelist())
                for name in ('docs/mac-migration-guide.md', 'docs/mac-portability-audit.md',
                             'docs/core-continuation-progress.md',
                             'scripts/install_mac.py', 'scripts/transfer_library.py',
                             'requirements-search.txt'):
                    self.assertIn('menglu-shared-library/' + name, out.namelist())
            self.assertFalse(any(str(path).endswith('local-machine.json') for path in _source_files(project)))

    def test_relative_path_is_anchored_to_relocated_config_not_cwd(self):
        settings = self.settings()
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'relocated/config/shared-library.json'
            with patch('os.getcwd', return_value='/'):
                self.assertEqual(settings.resolve_config_path(config, '../data/index.json'),
                                 config.parent.parent / 'data/index.json')
            absolute = Path(tmp).resolve() / 'index.json'
            self.assertEqual(settings.resolve_config_path(config, str(absolute)), absolute)

    def test_machine_config_missing_is_optional_and_invalid_values_fail(self):
        settings = self.settings()
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'local-machine.json'
            self.assertEqual(settings.load_machine_config(config), {})
            for value in ([], {'pdf_python': []}, {'soffice': ''}, {'obsidian_target': 2}, {'unknown': 'x'}):
                config.write_text(json.dumps(value))
                with self.subTest(value=value), self.assertRaises(ValueError):
                    settings.load_machine_config(config)
            config.write_text('{bad')
            with self.assertRaises(ValueError):
                settings.load_machine_config(config)
            config.write_text('{"treasury_root":"../treasury"}')
            self.assertEqual(settings.configured_path('treasury_root', config), config.parent.parent / 'treasury')

    def test_missing_explicit_executables_do_not_fall_back(self):
        settings = self.settings()
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / 'missing-tool'
            for resolver in (settings.resolve_soffice, settings.resolve_pdf_python):
                with self.subTest(resolver=resolver), self.assertRaisesRegex(ValueError, '不可用'):
                    resolver(missing)

    def test_converters_honor_explicit_missing_environment_paths(self):
        import legacy_doc
        import official_pdf
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / 'missing')
            with patch.dict(os.environ, {'MENGLU_SOFFICE': missing, 'MENGLU_PDF_PYTHON': missing}):
                with self.subTest(tool='soffice'), self.assertRaisesRegex(ValueError, '不可用'):
                    legacy_doc.convert_legacy_doc(bytes.fromhex('d0cf11e0a1b11ae1'))
                with self.subTest(tool='pdf_python'), self.assertRaisesRegex(ValueError, '不可用'):
                    official_pdf.extract_pdf(b'%PDF-1.4\n', 'Test Law')

    def test_ingest_helpers_import_without_optional_treasury(self):
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'local_settings.py').write_bytes((project / 'local_settings.py').read_bytes())
            code = ('import sys, runpy; sys.path[:0] = ' + repr([str(root), str(project)])
                    + '; import local_settings; module = runpy.run_path(sys.argv[1]); print(module["TREASURY"])')
            result = subprocess.run([sys.executable, '-c', code, str(project / 'scripts/ingest_basic_laws.py')],
                                    cwd='/', capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout.strip(), 'None')

    def test_pdf_uses_current_python_when_dependencies_available(self):
        settings = self.settings()
        with patch.dict(os.environ, {}, clear=True), patch.object(settings, 'configured_path', return_value=None), \
                patch.object(settings.importlib.util, 'find_spec', return_value=object()):
            self.assertEqual(settings.resolve_pdf_python(), Path(settings.sys.executable))

    def test_libreoffice_can_be_discovered_on_path(self):
        settings = self.settings()
        with patch.dict(os.environ, {}, clear=True), patch.object(settings, 'configured_path', return_value=None), \
                patch.object(settings.shutil, 'which', return_value=sys.executable):
            self.assertEqual(settings.resolve_soffice(), Path(sys.executable))

    def test_treasury_optional_until_requested(self):
        settings = self.settings()
        with patch.object(settings, 'configured_path', return_value=None):
            with self.assertRaisesRegex(ValueError, 'treasury_root'):
                settings.require_treasury()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(ValueError, 'client.py'):
                settings.require_treasury(root)
            client = root / 'sources/legal-tools/国家法律法规数据库MCP/scripts/client.py'
            client.parent.mkdir(parents=True)
            client.write_text('')
            self.assertEqual(settings.require_treasury(root), root)

    def test_unconfigured_obsidian_export_reports_skip_without_writes(self):
        from scripts import export_obsidian_library as exporter
        with tempfile.TemporaryDirectory() as tmp, patch.object(exporter, 'ROOT', Path(tmp)):
            result = exporter.export()
            self.assertEqual(result, {'status': 'skipped', 'reason': 'obsidian_target_not_configured'})
            self.assertEqual(list(Path(tmp).iterdir()), [])
