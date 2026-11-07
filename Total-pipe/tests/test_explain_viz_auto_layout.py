"""Automatic opportunities, empty rectangles and constrained native body reflow."""
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest

from deck_compiler.contracts import digest
from deck_compiler.explain_viz import DeckIRAdapter, enhance
from deck_compiler.explain_viz.decision import auto_decision, candidates
from deck_compiler.explain_viz.space import contains, empty_rectangles
from deck_compiler.explain_viz.specs import Options, validate_spec
from deck_compiler.pipeline import compile_input, write_json
from test_explain_viz import EXAMPLE, inputs


def automatic():
    return json.loads((EXAMPLE/'automatic.deck_ir.json').read_text(encoding='utf-8'))


class EmptyRegionTests(unittest.TestCase):
    def test_rectangle_subtraction_keeps_margin_and_is_deterministic(self):
        region, occupied = [0, 0, 1000, 600], [[0, 0, 500, 600]]
        expected = [[512., 0., 488., 600.]]
        self.assertEqual(empty_rectangles(region, occupied), expected)
        self.assertEqual(empty_rectangles(region, occupied), expected)
        for box in empty_rectangles(region, occupied):
            self.assertTrue(contains(box, region))
            self.assertGreaterEqual(box[0], 512)

    def test_full_occupied_and_invalid_regions_have_no_opportunity(self):
        self.assertEqual(empty_rectangles([0, 0, 1000, 600], [[0, 0, 1000, 600]]), [])
        self.assertEqual(empty_rectangles([0, 0, math.nan, 600], []), [])
        self.assertEqual(empty_rectangles([0, 0, 0, 600], []), [])

    def test_unoccupied_region_must_meet_minimum_dimensions(self):
        self.assertEqual(empty_rectangles([0, 0, 200, 100], []), [])
        self.assertEqual(empty_rectangles([0, 0, 419, 600], []), [])
        self.assertEqual(empty_rectangles([0, 0, 1000, 259], []), [])
        self.assertEqual(empty_rectangles([0, 0, 420, 260], []), [[0, 0, 420, 260]])

    def test_cuts_do_not_leave_rectangles_containing_an_obstacle(self):
        region = [0, 0, 1200, 900]
        obstacles = [[400, 200, 200, 100], [100, 600, 800, 100]]
        for box in empty_rectangles(region, obstacles, minimum=(100, 100)):
            self.assertTrue(contains(box, region))
            for x, y, w, h in obstacles:
                self.assertFalse(min(box[0]+box[2], x+w+12) > max(box[0], x-12)
                                 and min(box[1]+box[3], y+h+12) > max(box[1], y-12))


class AutomaticDecisionTests(unittest.TestCase):
    def test_defaults_enable_detection_and_local_reflow(self):
        options = Options.read(None)
        self.assertEqual(options.mode, 'auto')
        self.assertEqual(options.slot_policy, 'detect_free_space')
        self.assertTrue(options.allow_local_reflow)

    def test_three_templates_are_extracted_only_from_current_explicit_statements(self):
        ir = automatic()
        adapter = DeckIRAdapter(EXAMPLE)
        for slide in ir['slides']:
            semantics = adapter.read_slide_semantics(slide, {'graphic_id': 'new_scene'})
            supported, _ = candidates(semantics)
            decision = auto_decision(slide['id'], semantics, supported)
            self.assertEqual(decision['decision'], 'draw')
            validate_spec(decision['visual_spec'], semantics['facts'])

    def test_unordered_lists_and_negated_attachment_are_not_auto_drawn(self):
        cases = [('层叠结构', '栅极、介电层、薄膜，没有说明上下顺序。'),
                 ('流程', '讨论生长、键合、释放，顺序尚未确定。'),
                 ('剥离角 θ', '薄膜未贴附于衬底，θ 是薄膜与衬底平面的夹角。')]
        for title, body in cases:
            semantics = dict(title=title, archetype='composite-research', existing_visuals=0,
                             facts={'semantic.title': title, 'block:definition': body})
            supported, _ = candidates(semantics)
            self.assertEqual(auto_decision('test', semantics, supported)['decision'], 'skip')


class AutomaticLayoutTests(unittest.TestCase):
    def test_detected_tail_needs_no_reserved_scene_and_keeps_old_native_geometry(self):
        ir = automatic()
        ir['presentation']['visual_style'] = {'pack': 'academic', 'overrides': {'page.sparse_balance': 'top'}}
        original = copy.deepcopy(ir)
        result = enhance(ir, options={'allow_local_reflow': False}, adapter=DeckIRAdapter(EXAMPLE))
        self.assertEqual(result.status, 'enhanced', result.audit())
        self.assertTrue(result.manifest, result.audit())
        self.assertTrue(all(item['slot_source'] == 'detected' for item in result.manifest))
        self.assertTrue(all(not item['layout_changes'] for item in result.manifest))
        self.assertEqual(ir, original)
        for old, new in zip(ir['slides'], result.deck_ir['slides']):
            self.assertEqual(old['semantic'], new['semantic'])
            self.assertEqual(old['composition']['blocks'], new['composition']['blocks'])

    def test_local_reflow_has_an_audited_move_and_preserves_source_content(self):
        ir = automatic()
        before = copy.deepcopy(ir)
        result = enhance(ir, adapter=DeckIRAdapter(EXAMPLE))
        self.assertEqual(result.status, 'enhanced', result.audit())
        moved = [item for item in result.manifest if item['slot_source'] == 'local_reflow']
        self.assertTrue(moved, result.audit())
        self.assertTrue(any(item['layout_changes'] for item in moved))
        self.assertEqual(ir, before)
        for old, new in zip(ir['slides'], result.deck_ir['slides']):
            self.assertEqual(old['semantic'], new['semantic'])
            self.assertEqual(old['composition']['blocks'], new['composition']['blocks'])

    def test_small_existing_reserved_slot_can_be_enlarged_by_reflow(self):
        ir, _, _ = inputs()
        for slide in ir['slides']:
            slide['composition']['layout_tree']['regions']['body']['weights'] = [3, 1]
        before = copy.deepcopy(ir)
        result = enhance(ir, adapter=DeckIRAdapter(EXAMPLE))
        self.assertEqual(result.status, 'enhanced', result.audit())
        self.assertEqual(len(result.manifest), 3)
        self.assertTrue(all(item['slot_source'] == 'local_reflow' for item in result.manifest))
        self.assertTrue(all(not any(x.endswith(':path:reserved_area') for x in item['shape_ids'])
                            for item in result.manifest))
        self.assertEqual(ir, before)

    def test_protected_pages_and_reserved_only_policy_are_noops_without_slots(self):
        ir = automatic()
        result = enhance(ir, options={'protected_slide_ids': [s['id'] for s in ir['slides']]})
        self.assertIs(result.deck_ir, ir)
        self.assertEqual({d['reason'] for d in result.decisions}, {'protected_slide'})
        result = enhance(ir, options={'slot_policy': 'reserved_only'})
        self.assertIs(result.deck_ir, ir)
        self.assertFalse(result.manifest)

    def test_unknown_protected_id_fails_closed_and_hard_intent_is_not_rearranged(self):
        ir = automatic()
        result = enhance(ir, options={'protected_slide_ids': ['misspelled-slide']})
        self.assertIs(result.deck_ir, ir)
        self.assertEqual(result.status, 'fallback')
        self.assertIn('invalid_protected_slides', result.warnings)
        ir['slides'][0]['composition']['visual_intent'] = {'relation': 'process'}
        result = enhance(ir)
        self.assertEqual(result.decisions[0]['reason'], 'hard_visual_intent')

    def test_layout_attempt_budget_bounds_failed_search_and_input_is_preserved(self):
        ir = automatic()
        class RejectingAdapter(DeckIRAdapter):
            def validate_ir(self, *args):
                raise ValueError('layout_conflict')
        result = enhance(ir, options={'max_layout_attempts_per_slide': 1}, adapter=RejectingAdapter(EXAMPLE))
        self.assertIs(result.deck_ir, ir)
        self.assertLessEqual(result.diagnostics['layout_attempts'], 4)
        self.assertFalse(result.manifest)

    def test_regular_compile_is_auto_and_off_overrides_missing_request(self):
        ir, _, _ = inputs()
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            source = folder/'source.json'
            write_json(source, ir)
            _, _, qa = compile_input(source, folder/'auto', {'name': 'packer'})
            self.assertEqual(qa['explain_viz']['mode'], 'auto')
            self.assertGreater(qa['explain_viz']['applied_visuals'], 0, qa)
            effective, _, off = compile_input(source, folder/'off', {'name': 'packer'},
                explain_viz_request=folder/'missing.json', explain_viz_mode='off')
            self.assertEqual(effective, ir)
            self.assertEqual(off['explain_viz']['status'], 'disabled')
            self.assertEqual(json.loads(source.read_text()), ir)

    def test_second_run_does_not_add_more_diagrams(self):
        ir = automatic()
        first = enhance(ir, adapter=DeckIRAdapter(EXAMPLE))
        self.assertEqual(first.status, 'enhanced', first.audit())
        second = enhance(first.deck_ir, adapter=DeckIRAdapter(EXAMPLE))
        self.assertIs(second.deck_ir, first.deck_ir)
        self.assertFalse(second.manifest)

    def test_agent_request_identity_keeps_old_jobs_equivalent_to_default_auto(self):
        from agent.requests import request_identity
        request = {'presentation_type': 'group_meeting'}
        self.assertEqual(request_identity(request), request_identity({**request, 'explain_viz_mode': 'auto'}))
        self.assertNotEqual(request_identity(request), request_identity({**request, 'explain_viz_mode': 'off'}))


if __name__ == '__main__':
    unittest.main()
