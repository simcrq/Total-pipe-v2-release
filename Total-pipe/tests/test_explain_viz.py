"""Optional teaching diagrams preserve canonical content and fail open at each boundary."""
import copy
import json
import math
from pathlib import Path
import unittest
from unittest.mock import patch

from deck_compiler.contracts import digest
from deck_compiler.explain_viz import DeckIRAdapter, enhance, make_prompt
from deck_compiler.explain_viz.adapter import placeholder
from deck_compiler.explain_viz.specs import validate_spec
from deck_compiler.explain_viz.templates import build
from deck_compiler.graphic_layout import validate_graphics
from deck_compiler.ir import validate

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT/'examples/explain-viz'


def inputs():
    return tuple(json.loads((EXAMPLE/name).read_text(encoding='utf-8'))
                 for name in ('reserved.deck_ir.json', 'slots.json', 'proposal.json'))


class AcceptingAdapter(DeckIRAdapter):
    """Isolate transaction policy from system font availability."""
    def compile(self, ir):
        return {'slides': []}

    def find_slot_box(self, layout, slide_id, graphic_id):
        return [0, 0, 1168, 400]

    def validate_ir(self, original, candidate, baseline, additions):
        for before, after in zip(original['slides'], candidate['slides']):
            if before['semantic'] != after['semantic']:
                raise ValueError('unauthorized_ir_change')
        return baseline


class ExplainVizPolicyTests(unittest.TestCase):
    def setUp(self):
        self.ir, self.slots, self.proposal = inputs()

    def apply(self, ir=None, proposal=None, adapter=None, **options):
        return enhance(self.ir if ir is None else ir,
                       {'slots': self.slots, 'proposal': self.proposal if proposal is None else proposal},
                       {'mode': 'auto', **options}, adapter or AcceptingAdapter())

    def rebind(self):
        self.proposal['ir_sha256'] = digest(self.ir)
        self.proposal['slots_sha256'] = digest(self.slots)

    def test_default_off_returns_same_object_without_compilation(self):
        with patch.object(DeckIRAdapter, 'compile', side_effect=AssertionError('must not compile')):
            result = enhance(self.ir)
        self.assertIs(result.deck_ir, self.ir)
        self.assertEqual(result.status, 'disabled')
        self.assertEqual(result.diagnostics['compile_calls'], 0)

    def test_no_slot_is_a_noop_without_a_proposal_or_compilation(self):
        result = enhance(self.ir, options={'mode': 'prefer'})
        self.assertIs(result.deck_ir, self.ir)
        self.assertEqual({d['reason'] for d in result.decisions}, {'no_slot'})
        self.assertEqual(result.diagnostics['compile_calls'], 0)

    def test_success_appends_only_inside_reserved_arrays(self):
        original = copy.deepcopy(self.ir)
        result = self.apply()
        self.assertEqual(result.status, 'enhanced', result.audit())
        self.assertEqual(len(result.manifest), 3)
        self.assertEqual(self.ir, original)
        for old, new in zip(self.ir['slides'], result.deck_ir['slides']):
            self.assertEqual(old['semantic'], new['semantic'])
            self.assertEqual(old['composition']['layout_tree'], new['composition']['layout_tree'])
            self.assertEqual(old['composition']['blocks'], new['composition']['blocks'])
            self.assertEqual(old['composition']['graphics'][0]['paths'][0],
                             new['composition']['graphics'][0]['paths'][0])
        self.assertNotIn('deck_ir', result.audit())
        self.assertIn('semantic_review_required', result.warnings)

    def test_second_run_is_idempotent_even_with_original_proposal(self):
        first = self.apply()
        second = self.apply(ir=first.deck_ir)
        self.assertIs(second.deck_ir, first.deck_ir)
        self.assertEqual({d['reason'] for d in second.decisions}, {'already_enhanced'})
        self.assertFalse(second.added_object_ids)

    def test_budget_counts_existing_diagrams_across_runs(self):
        first = self.apply(max_visuals_per_deck=1)
        proposal = copy.deepcopy(self.proposal)
        proposal['ir_sha256'] = digest(first.deck_ir)
        second = self.apply(ir=first.deck_ir, proposal=proposal, max_visuals_per_deck=1)
        self.assertIs(second.deck_ir, first.deck_ir)
        self.assertFalse(second.manifest)
        self.assertIn('deck_budget', {d['reason'] for d in second.decisions})

    def test_stale_ir_and_slots_revert_before_compilation(self):
        for key in ('ir_sha256', 'slots_sha256'):
            with self.subTest(key=key):
                proposal = copy.deepcopy(self.proposal)
                proposal[key] = '0'*64
                result = self.apply(proposal=proposal)
                self.assertIs(result.deck_ir, self.ir)
                self.assertEqual(result.status, 'fallback')
                self.assertIn('stale_proposal', result.warnings)
                self.assertEqual(result.diagnostics['compile_calls'], 0)

    def test_bad_page_spec_preserves_other_page_transactions(self):
        self.proposal['slides'][0]['visual_spec']['labels']['film'] = '未提供的材料'
        result = self.apply()
        self.assertEqual(len(result.manifest), 2)
        self.assertEqual(result.deck_ir['slides'][0], self.ir['slides'][0])
        self.assertIn('peel-angle:unbound_label', result.warnings)

    def test_page_compiler_rejection_does_not_modify_input_or_other_pages(self):
        class RejectPeel(AcceptingAdapter):
            def validate_ir(self, original, candidate, baseline, additions):
                if any(item['slide_id'] == 'peel-angle' for item in additions):
                    raise ValueError('existing_object_changed')
                return baseline
        result = self.apply(adapter=RejectPeel())
        self.assertEqual(len(result.manifest), 2)
        self.assertEqual(result.deck_ir['slides'][0], self.ir['slides'][0])

    def test_final_failure_clears_manifest_and_does_not_report_draw(self):
        class RejectFinal(AcceptingAdapter):
            calls = 0
            def validate_ir(self, *args):
                self.calls += 1
                if self.calls == 4:
                    raise RuntimeError('sensitive page content')
                return {'slides': []}
        result = self.apply(adapter=RejectFinal())
        self.assertIs(result.deck_ir, self.ir)
        self.assertEqual(result.status, 'fallback')
        self.assertFalse(result.manifest or result.added_object_ids)
        self.assertFalse(any(d['decision'] == 'draw' for d in result.decisions))
        self.assertNotIn('sensitive page content', json.dumps(result.audit()))

    def test_unexpected_adapter_mutation_is_discarded_on_exception(self):
        class BrokenAppend(AcceptingAdapter):
            def append_group(self, ir, *args):
                ir['slides'][0]['semantic']['title'] = 'corrupted'
                raise RuntimeError('unexpected error')
        original = copy.deepcopy(self.ir)
        result = self.apply(adapter=BrokenAppend())
        self.assertIs(result.deck_ir, self.ir)
        self.assertEqual(self.ir, original)
        self.assertFalse(result.manifest)

    def test_prefer_changes_threshold_but_keeps_source_confidence_gate(self):
        for entry in self.proposal['slides']:
            entry['scores'] = dict(explanation_gain=.6, relationship_clarity=.6,
                                   source_confidence=.8, layout_fit=.8, redundancy=0)
        self.assertFalse(self.apply().manifest)
        self.assertEqual(len(self.apply(mode='prefer').manifest), 3)
        for entry in self.proposal['slides']:
            entry['scores']['source_confidence'] = .79
        self.assertFalse(self.apply(mode='prefer').manifest)

    def test_invalid_scores_and_parameters_cannot_reach_template_generation(self):
        for value in (True, math.nan, math.inf, -1, 2):
            proposal = copy.deepcopy(self.proposal)
            proposal['slides'][0]['scores']['explanation_gain'] = value
            result = self.apply(proposal=proposal)
            self.assertEqual(result.deck_ir['slides'][0], self.ir['slides'][0])
        self.proposal['slides'][0]['visual_spec']['parameters'] = {'angle_deg': 35}
        self.assertEqual(self.apply().deck_ir['slides'][0], self.ir['slides'][0])

    def test_summary_and_existing_visual_pages_never_draw(self):
        self.ir['slides'][0]['composition']['archetype'] = 'three-conclusions'
        self.ir['slides'][1]['composition']['graphics'].append(placeholder('other'))
        self.rebind()
        result = self.apply(mode='prefer')
        self.assertEqual(len(result.manifest), 1)
        self.assertIn('summary_page', {d['reason'] for d in result.decisions})
        self.assertIn('existing_visual', {d['reason'] for d in result.decisions})

    def test_nonempty_or_nonreserved_path_cannot_be_used_as_slot(self):
        self.ir['slides'][0]['composition']['graphics'][0]['paths'][0]['fill'] = 'accent'
        self.rebind()
        result = self.apply()
        self.assertEqual(result.deck_ir['slides'][0], self.ir['slides'][0])
        self.assertIn('invalid_slot', {d['reason'] for d in result.decisions})

    def test_unordered_or_reversed_source_cannot_become_layers_or_steps(self):
        for index in (1, 2):
            slide = self.ir['slides'][index]
            facts = {f"block:{b['id']}": b['text'] for b in slide['composition']['blocks']}
            spec = copy.deepcopy(self.proposal['slides'][index]['visual_spec'])
            keys = list(spec['labels'])
            spec['labels'][keys[0]], spec['labels'][keys[1]] = spec['labels'][keys[1]], spec['labels'][keys[0]]
            with self.assertRaisesRegex(ValueError, 'unsupported_source_relation'):
                validate_spec(spec, facts)

    def test_negated_attachment_is_not_a_source_for_drawing_attachment(self):
        facts = {'block:definition': '薄膜未贴附于衬底；θ 是薄膜与衬底平面的夹角。'}
        spec = self.proposal['slides'][0]['visual_spec']
        with self.assertRaisesRegex(ValueError, 'unsupported_source_relation'):
            validate_spec(spec, facts)

    def test_failed_baseline_compilation_is_attempted_only_once(self):
        class BrokenBaseline(AcceptingAdapter):
            calls = 0
            def compile(self, ir):
                self.calls += 1
                raise ValueError('compile_failed')
        adapter = BrokenBaseline()
        result = self.apply(adapter=adapter)
        self.assertEqual(adapter.calls, 1)
        self.assertIs(result.deck_ir, self.ir)
        self.assertIn('baseline_compile_failed', result.warnings)


class ExplainVizNativeTests(unittest.TestCase):
    def test_quality_gate_rejects_moving_objects_and_cross_slot_collisions(self):
        ir, _, _ = inputs()
        ir['slides'] = ir['slides'][:1]
        candidate = copy.deepcopy(ir)
        candidate['slides'][0]['composition']['graphics'][0]['paths'].append({
            'id': 'evz_extra', 'commands': [['M', 40, 100], ['L', 300, 200]]})
        eid = 'graphic:explanation_visual:path:evz_extra'
        additions = [{'slide_id': 'peel-angle', 'graphic_id': 'explanation_visual', 'shape_ids': [eid]}]
        old = [{'id': 'reserved_area', 'kind': 'shape', 'graphic_id': 'explanation_visual',
                'bbox': [0, 0, 1000, 600], 'layout_region': [0, 0, 1000, 600]},
               {'id': 'definition', 'kind': 'text', 'bbox': [0, 650, 1000, 80], 'text': 'unchanged'}]
        baseline = {'slides': [{'id': 'peel-angle', 'elements': old}]}
        extra = {'id': eid, 'kind': 'shape', 'bbox': [40, 100, 260, 100]}
        adapter = DeckIRAdapter()
        accepted = {'slides': [{'id': 'peel-angle', 'elements': copy.deepcopy(old)+[extra]}]}
        with patch.object(adapter, 'compile', return_value=accepted):
            adapter.validate_ir(ir, candidate, baseline, additions)
        changed = copy.deepcopy(accepted)
        changed['slides'][0]['elements'][1]['bbox'][0] = 1
        with patch.object(adapter, 'compile', return_value=changed):
            with self.assertRaisesRegex(ValueError, 'existing_object_changed'):
                adapter.validate_ir(ir, candidate, baseline, additions)
        baseline['slides'][0]['elements'][1]['bbox'] = [40, 100, 260, 100]
        accepted['slides'][0]['elements'][1]['bbox'] = [40, 100, 260, 100]
        with patch.object(adapter, 'compile', return_value=accepted):
            with self.assertRaisesRegex(ValueError, 'layout_conflict'):
                adapter.validate_ir(ir, candidate, baseline, additions)

    def test_schemas_cover_the_reserved_deck_and_bound_proposal(self):
        import jsonschema
        ir, slots, proposal = inputs()
        jsonschema.validate(ir, json.loads((ROOT/'schemas/deck-ir.schema.json').read_text()))
        schema = json.loads((ROOT/'schemas/explain-viz.schema.json').read_text())
        jsonschema.validate(proposal, schema)
        jsonschema.validate(slots, {**schema, '$ref': '#/$defs/slots'})
        self.assertFalse([item for item in validate(ir) if item['severity'] == 'FAIL'])
        self.assertEqual(proposal['ir_sha256'], digest(ir))
        self.assertEqual(proposal['slots_sha256'], digest(slots))

    def test_templates_are_deterministic_bounded_native_paths(self):
        _, _, proposal = inputs()
        for entry in proposal['slides']:
            spec = entry['visual_spec']
            group = build(spec)
            self.assertEqual(group, build(spec))
            scene = {'id': 'teaching', 'type': 'path', **group}
            self.assertFalse(validate_graphics([scene], 'native-graphic'))
            self.assertLessEqual(len(group['labels']), 7)
            self.assertTrue(any(label['text'] == '示意' for label in group['labels']))

    def test_peel_angle_uses_horizontal_substrate_reference_and_symbolic_label(self):
        spec = inputs()[2]['slides'][0]['visual_spec']
        group = build(spec)
        free = next(p for p in group['paths'] if p['id'].endswith('_peeled_film'))
        start, end = [p[1:] for p in free['commands']]
        angle = math.degrees(math.atan2(start[1]-end[1], end[0]-start[0]))
        self.assertAlmostEqual(angle, 35)
        for path in group['paths']:
            if '_reference_' in path['id']:
                self.assertEqual(path['commands'][0][2], path['commands'][1][2])
        self.assertEqual({label['text'] for label in group['labels']}, {'示意', '薄膜', '衬底', 'θ'})

    def test_adapter_mapping_keeps_geometry_isotropic_in_offset_view_box(self):
        spec = inputs()[2]['slides'][0]['visual_spec']
        slot = placeholder()
        slot['view_box'] = [10, 20, 500, 500]
        group = DeckIRAdapter().build_native_group(spec, slot, {})
        free = next(p for p in group['paths'] if p['id'].endswith('_peeled_film'))
        a, b = [p[1:] for p in free['commands']]
        self.assertAlmostEqual(math.degrees(math.atan2(a[1]-b[1], b[0]-a[0])), 35, places=5)

    def test_real_compiler_preserves_all_existing_objects_for_three_templates(self):
        ir, slots, proposal = inputs()
        result = enhance(ir, {'slots': slots, 'proposal': proposal}, {'mode': 'auto'}, DeckIRAdapter(EXAMPLE))
        self.assertEqual(result.status, 'enhanced', result.audit())
        self.assertEqual(len(result.manifest), 3, result.audit())
        self.assertEqual(len(result.added_object_ids), sum(len(item['shape_ids']) for item in result.manifest))

    def test_prompt_contains_only_filtered_candidates_and_no_model_invocation(self):
        ir, slots, _ = inputs()
        with patch.object(DeckIRAdapter, 'compile', return_value={'slides': []}), \
             patch.object(DeckIRAdapter, 'find_slot_box', return_value=[0, 0, 1168, 400]):
            prompt = make_prompt(ir, slots, EXAMPLE)
        self.assertEqual(len(prompt['candidates']), 3)
        self.assertIn('proposal_schema', prompt)
        self.assertEqual(prompt['ir_sha256'], digest(ir))
        self.assertNotIn('speaker_notes', json.dumps(prompt['candidates']))


if __name__ == '__main__':
    unittest.main()
