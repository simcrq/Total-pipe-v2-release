"""Guardrail tests for Batch 2: dependency manifests, lazy imports, and CI config."""
import builtins
import importlib.util
import json
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]


class DependencyManifestTests(unittest.TestCase):
    def test_paperworkflow_pyproject_excludes_unused_and_batch_only_deps(self):
        data = tomllib.loads((REPO_ROOT / 'PaperWorkflow/pyproject.toml').read_text(encoding='utf-8'))
        deps = [d.lower() for d in data['project']['dependencies']]
        joined = ' '.join(deps)
        for excluded in ('numpy', 'tokenizers', 'openai', 'tqdm'):
            self.assertNotIn(excluded, joined)
        for required in ('loguru', 'pillow', 'pyyaml', 'requests'):
            self.assertIn(required, joined)
        batch = ' '.join(data['project']['optional-dependencies']['batch']).lower()
        self.assertIn('openai', batch)
        self.assertIn('tqdm', batch)

    def test_total_pipe_requirements_include_matplotlib_and_dev_jsonschema(self):
        compiler_req = (REPO_ROOT / 'Total-pipe/deck_compiler/requirements.txt').read_text(encoding='utf-8').lower()
        dev_req = (REPO_ROOT / 'Total-pipe/requirements-dev.txt').read_text(encoding='utf-8').lower()
        self.assertIn('matplotlib', compiler_req)
        self.assertIn('-r requirements.txt', dev_req)
        self.assertIn('jsonschema', dev_req)

    def test_install_dry_run_uses_slimmed_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            res = subprocess.run(
                [sys.executable, str(REPO_ROOT / 'install.py'), '--client', 'codex',
                 '--venv', str(root / 'venv'), '--config', str(root / 'config.toml'),
                 '--skills-root', str(root / 'skills'), '--dry-run'],
                check=True, capture_output=True, text=True,
            )
            payload = json.loads(res.stdout)
            self.assertEqual(payload['status'], 'DRY_RUN')
            joined = ' '.join(payload['dependencies']).lower()
            for excluded in ('numpy', 'tokenizers', 'openai', 'tqdm'):
                self.assertNotIn(excluded, joined)


class CiWorkflowTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('yaml'), 'pyyaml not installed')
    def test_workflow_covers_all_components_and_windows_matrix(self):
        import yaml

        wf_text = (REPO_ROOT / '.github/workflows/deck-compiler.yml').read_text(encoding='utf-8')
        wf = yaml.safe_load(wf_text)
        self.assertIn('compiler-regression', wf['jobs'])
        self.assertIn('research-ppt-assistant', wf['jobs'])
        self.assertIn('repo-hygiene', wf['jobs'])
        oses = {entry['os'] for entry in wf['jobs']['compiler-regression']['strategy']['matrix']['include']}
        self.assertEqual(oses, {'ubuntu-latest', 'windows-latest'})
        steps_text = json.dumps(wf['jobs']['compiler-regression']['steps'])
        for suite in ('Total-pipe/tests', 'Total-pipe/pwf2rpa/tests', 'PaperWorkflow/tests'):
            self.assertIn(suite, steps_text)
        rpa_steps = json.dumps(wf['jobs']['research-ppt-assistant']['steps'])
        self.assertIn('npm run check', rpa_steps)


class PaperWorkflowLazyDepsTests(unittest.TestCase):
    def test_official_cli_pdf_processor_does_not_import_requests(self):
        pwf_root = str(REPO_ROOT / 'PaperWorkflow')
        added = False
        if pwf_root not in sys.path:
            sys.path.insert(0, pwf_root)
            added = True
        saved_modules = {k: sys.modules.pop(k) for k in list(sys.modules)
                         if k in ('utils.pdf_handler', 'utils.pdf_api_handler')}
        try:
            real_import = builtins.__import__

            def block_requests(name, globals=None, locals=None, fromlist=(), level=0):
                if name == 'requests' or name.endswith('pdf_api_handler'):
                    raise AssertionError(f'unexpected import: {name}')
                return real_import(name, globals, locals, fromlist, level)

            with tempfile.TemporaryDirectory() as tmp, patch('builtins.__import__', side_effect=block_requests):
                from utils.pdf_handler import PDFProcessor
                proc = PDFProcessor({'paths': {'temp_dir': tmp}, 'api': {'mineru': {'mode': 'official_cli'}}})
                self.assertEqual(proc.mode, 'official_cli')
        finally:
            sys.modules.update(saved_modules)
            if added:
                sys.path.remove(pwf_root)


if __name__ == '__main__':
    unittest.main()
