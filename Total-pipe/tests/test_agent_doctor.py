import os
from unittest.mock import patch

from agent import doctor as module
from agent_fixture import AgentCase


class DoctorTests(AgentCase):
    def test_real_pdf_runtime_import_failure_blocks_evidence_despite_successful_bridge_version(self):
        # Inject a local import failure into the real bridge subprocess. No PDF is opened, no
        # processor is constructed, and no OCR/network request is made.
        injection = self.root/'import-injection'
        injection.mkdir()
        (injection/'sitecustomize.py').write_text(
            'import sys\n'
            'class BlockPdfRuntime:\n'
            '    def find_spec(self, fullname, path=None, target=None):\n'
            '        if fullname == "utils.pdf_handler":\n'
            '            raise ModuleNotFoundError("missing PDF runtime dependency sentinel")\n'
            'sys.meta_path.insert(0, BlockPdfRuntime())\n', encoding='utf-8')
        pythonpath = os.pathsep.join([str(injection), os.environ.get('PYTHONPATH', '')])
        with patch.dict(os.environ, {'PYTHONPATH': pythonpath}):
            result = module.doctor(source_kind='pdf')
        checks = {check['id']: check for check in result['checks']}
        self.assertEqual(checks['paperworkflow.bridge']['status'], 'PASS')
        self.assertEqual(checks['paperworkflow.runtime_imports']['status'], 'FAIL')
        self.assertIn('missing PDF runtime dependency sentinel', checks['paperworkflow.runtime_imports']['detail'])
        self.assertFalse(result['can_evidence_pdf'])
        self.assertIn('evidence', result['blocked_stages'])

    def test_missing_officecli_blocks_build_without_blocking_markdown_evidence(self):
        original = module.shutil.which
        with patch.object(module.shutil, 'which', side_effect=lambda name: None if name == 'officecli' else original(name)):
            result = module.doctor(source_kind='markdown')
        self.assertFalse(result['can_build_editable'])
        self.assertTrue(result['can_evidence_markdown'])
        self.assertIn('build', result['blocked_stages'])
        checks = {check['id']: check for check in result['checks']}
        self.assertIn('paperworkflow.bridge', checks)
        self.assertEqual(checks['officecli.present']['status'], 'FAIL')

    def test_ir_only_capability_does_not_require_rpa_or_ocr(self):
        original = module.probe
        def probe(argv, *args, **kwargs):
            if str(argv[0]) == 'node': return False, 'Node absent'
            return original(argv, *args, **kwargs)
        with patch.object(module, 'probe', side_effect=probe):
            result = module.doctor(source_kind='deck_ir')
        self.assertFalse(result['can_rpa'])
        self.assertNotIn('rpa', result['blocked_stages'])
        self.assertNotIn('evidence', result['blocked_stages'])

    def test_stage_instruction_routes_and_light_skill_are_complete(self):
        from agent.runner import TABLE, STAGES
        from agent import COMPONENT
        for stage in STAGES:
            if stage.get('instructions_ref'):
                ref = TABLE['instructions'][stage['instructions_ref']]
                if not ref.startswith('work/'):
                    self.assertTrue((COMPONENT/ref.split('#')[0]).is_file())
        self.assertLessEqual(len((COMPONENT/'skills/total-pipe-agent/SKILL.md').read_text().splitlines()), 60)
