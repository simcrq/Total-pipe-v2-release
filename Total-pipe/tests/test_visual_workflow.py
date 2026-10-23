"""Agent entry points cannot accidentally skip design; low-level legacy compilation still works."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from deck_compiler.contracts import digest
from deck_compiler.pipeline import build, compile_input, locked, write_json
from deck_compiler.unified_cli import generate_presentation
from deck_compiler.visual_planner import apply_proposal, make_prompt, pending_design, planning_targets
from test_deck_compiler import ROOT, fixture


DESIGN = {'style': 'research-seminar', 'title_treatment': 'thin-rule', 'density': 'balanced',
          'figure_treatment': 'unframed', 'decoration_policy': 'minimal'}
PLAN = {'visual_job': 'measurement-evidence', 'primary': {'kind': 'figure', 'index': 0},
        'composition': 'figure-left'}


class VisualWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.path = self.base/'deck.json'
        self.out = self.base/'build'

    def figure_deck(self):
        ir = fixture()
        Image.new('RGB', (1000, 600), '#DAE8EE').save(self.base/'panel.png')
        ir['assets'] = {'panel': {'path': 'panel.png', 'source_figure': '1'}}
        slide = ir['slides'][0]
        slide['semantic']['caveats'] = []
        slide['composition'] = {'archetype': 'figure-parameters',
            'blocks': [{'id': 'conditions', 'component': 'body', 'text': 'The control conditions are fixed.'}],
            'figure_refs': [{'asset_id': 'panel', 'source_figure': '1',
                             'caption': 'Fig. 1. Control.', 'min_panel_extent': 140}]}
        ir['slides'] = [slide, copy.deepcopy(slide)]
        ir['slides'][1]['id'] = 'peer'
        return ir

    def compile(self, ir, **kwargs):
        write_json(self.path, ir)
        with locked(self.out):
            return compile_input(self.path, self.out, **kwargs)

    def test_missing_design_returns_a_full_prompt_before_rendering(self):
        ir = self.figure_deck()
        write_json(self.path, ir)
        with patch('deck_compiler.pipeline.officecli.preflight') as writer:
            qa = build(self.path, self.out, native_render=False)
        writer.assert_not_called()
        self.assertEqual(qa['next_action']['slide_ids'], ['evidence', 'peer'])
        self.assertTrue(qa['next_action']['academic_design_required'])
        prompt = json.loads(Path(qa['next_action']['prompt']).read_text())
        self.assertEqual(prompt['deck_ir'], ir)
        self.assertEqual(prompt['ir_sha256'], digest(ir))
        self.assertEqual(prompt['planning_targets'][0]['visual_jobs'], ['measurement-evidence'])
        self.assertFalse((self.out/'candidate.pptx').exists())

    def test_style_alone_does_not_hide_missing_per_slide_plans(self):
        ir = self.figure_deck()
        ir['presentation'] = {'academic_design': DESIGN}
        ir['slides'][0]['presentation']['visual_plan'] = copy.deepcopy(PLAN)
        _, layout, qa = self.compile(ir)
        self.assertIsNone(layout)
        self.assertEqual(qa['next_action']['slide_ids'], ['peer'])
        self.assertFalse(qa['next_action']['academic_design_required'])

    def test_complete_design_resumes_compilation_without_changing_science(self):
        ir = self.figure_deck()
        proposal = {'ir_sha256': digest(ir), 'academic_design': DESIGN,
                    'slides': [{'slide_id': s['id'], 'visual_plan': PLAN} for s in ir['slides']]}
        merged = apply_proposal(ir, proposal)
        _, layout, qa = self.compile(merged)
        self.assertEqual(qa['counts']['FAIL'], 0, qa)
        self.assertEqual(len(layout['slides']), 2)
        self.assertNotIn('next_action', qa)
        for old, new in zip(ir['slides'], merged['slides']):
            self.assertEqual(new['semantic'], old['semantic'])
            self.assertEqual(new['composition'], old['composition'])

    def test_text_and_formula_only_deck_can_complete_deck_wide_design(self):
        ir = fixture()
        ir['slides'][0]['composition']['blocks'][0] = {
            'id': 'equation', 'component': 'formula', 'text': r'\sqrt{1+e^{-t}}'}
        ir['slides'][0]['composition']['archetype'] = 'three-conclusions'
        self.assertTrue(all(not t['visual_jobs'] for t in planning_targets(ir)))
        proposal = {'ir_sha256': digest(ir), 'academic_design': DESIGN, 'slides': []}
        merged = apply_proposal(ir, proposal)
        _, layout, qa = self.compile(merged)
        self.assertIsNotNone(layout)
        self.assertEqual(qa['counts']['FAIL'], 0, qa)
        self.assertFalse(pending_design(merged)['slide_ids'])
        self.assertTrue(any(e['kind'] == 'math' for e in layout['slides'][0]['elements']))

    def test_hard_process_groups_are_identified_without_inventing_a_visual_plan(self):
        ir = self.figure_deck()
        slide = ir['slides'][0]
        slide['composition']['visual_intent'] = {'relation': 'process'}
        target = planning_targets(ir)[0]
        self.assertEqual(target['visual_jobs'], [])
        self.assertEqual(target['reason'], 'hard_process_group')

    def test_selected_prompt_keeps_the_whole_deck_and_lists_only_selected_targets(self):
        ir = self.figure_deck()
        prompt = make_prompt(ir, self.base, slide_ids=['peer'])
        self.assertEqual(len(prompt['deck_ir']['slides']), 2)
        self.assertEqual([t['slide_id'] for t in prompt['planning_targets']], ['peer'])

    def test_explicit_legacy_mode_preserves_the_old_path(self):
        _, layout, qa = self.compile(fixture(), require_visual_design=False)
        self.assertIsNotNone(layout)
        self.assertEqual(qa['counts']['FAIL'], 0, qa)
        self.assertNotIn('academic_design', layout)

    def test_blocked_compile_removes_stale_layout_and_derived_files(self):
        self.compile(fixture(), require_visual_design=False)
        self.assertTrue((self.out/'layout.json').exists())
        self.assertTrue((self.out/'derived').exists())
        self.compile(fixture())
        self.assertFalse((self.out/'layout.json').exists())
        self.assertFalse((self.out/'derived').exists())

    def test_cli_defaults_to_design_and_has_an_explicit_legacy_opt_out(self):
        write_json(self.path, fixture())
        command = [sys.executable, '-m', 'deck_compiler', 'compile', '--ir', str(self.path),
                   '--out', str(self.out)]
        blocked = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(blocked.returncode, 1, blocked.stderr)
        self.assertTrue(json.loads(blocked.stdout)['next_action']['prompt'])
        legacy = subprocess.run([*command, '--skip-visual-design'], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(legacy.returncode, 0, legacy.stderr)
        self.assertEqual(json.loads(legacy.stdout)['counts']['FAIL'], 0)

    def test_mcp_default_surfaces_the_design_gate_and_rejects_non_boolean_bypass(self):
        write_json(self.path, fixture())
        for bypass in (None, 'true'):
            arguments = {'ir': str(self.path), 'out': str(self.out)}
            if bypass is not None: arguments['skip_visual_design'] = bypass
            request = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                       'params': {'name': 'totalpipe_compile', 'arguments': arguments}}
            process = subprocess.run([sys.executable, '-m', 'deck_compiler.mcp_server'],
                input=json.dumps(request)+'\n', cwd=ROOT, capture_output=True, text=True, timeout=30)
            response = json.loads(process.stdout)['result']
            if bypass is None:
                payload = json.loads(response['content'][0]['text'])
                self.assertEqual(payload['exit_code'], 1)
                self.assertTrue(Path(payload['next_action']['prompt']).exists())
            else:
                self.assertTrue(response['isError'])

    def test_unified_generation_uses_the_same_gate(self):
        write_json(self.path, fixture())
        success, pptx, qa = generate_presentation(self.path, self.out)
        self.assertFalse(success)
        self.assertIsNone(pptx)
        self.assertTrue(qa['next_action']['academic_design_required'])


if __name__ == '__main__':
    unittest.main()
