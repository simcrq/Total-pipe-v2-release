from unittest.mock import patch

from agent import doctor as module
from agent_fixture import AgentCase


class DoctorTests(AgentCase):
    def test_missing_officecli_blocks_build_without_blocking_markdown_evidence(self):
        original = module.shutil.which
        with patch.object(module.shutil, 'which', side_effect=lambda name: None if name == 'officecli' else original(name)):
            result = module.doctor(source_kind='markdown')
        self.assertFalse(result['can_build_editable'])
        self.assertTrue(result['can_evidence_markdown'])
        self.assertIn('build', result['blocked_stages'])
        self.assertEqual(len(result['checks']), 12)

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
