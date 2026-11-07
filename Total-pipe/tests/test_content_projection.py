"""Science-record preservation, audience-copy authority, scoped qualifiers and review gates."""
import copy
import shutil
import unittest
from unittest.mock import patch

import jsonschema

from agent import COMPONENT, adapters as a, runner
from agent import content_review
from agent.ir_pages import bind_sources
from agent.state import read, write, sha
from agent_fixture import AgentCase, workflow
from deck_compiler.design import bind_design, validate_design, content_bindings
from deck_compiler.content_projection import validate_ir as validate_projection
from deck_compiler.pipeline import compile_input
from pwf2rpa.content_contract import records, validate_contract


def scientific_story():
    nodes = [
        {'answer': 'Separate sensing and processing modules require data conversion and transfer, adding latency and energy costs.',
         'key_points': ['The introduction reports no measured system energy-saving factor.'], 'evidence': ['EV0001']},
        {'answer': 'Measured accuracy increased from 16% to 62%.',
         'key_points': ['Gaussian-noise Fashion-MNIST; identical training conditions.',
                        'These observations do not establish a unique mechanism.'], 'evidence': ['EV0002']},
        {'answer': 'An independent control supports the response.', 'evidence': ['EV0003']},
        {'answer': 'The device provides distinct responses under the tested settings.', 'evidence': ['EV0004']}]
    for i, node in enumerate(nodes):
        node.update(title='Observation and scope', question='Which evidence supports the claim?',
                    next='An independent test constrains the remaining interpretation.')
    value = {'planner': {'mode': 'subagent', 'model': 'test-model', 'reasoning_effort': 'high', 'selected_by_user': True},
             'core_question': 'What supports the response?', 'main_message': 'The response is measured under stated conditions.',
             'story': nodes, 'ending': {'takeaway': 'The response is supported under the tested settings.',
                                      'limitation': 'The tested sample limits generalization.'}}
    policies = {ref: {'kind': 'claim', 'visibility': 'required'} for ref in records(value)}
    policies['S1.key_points[0]'] = {'kind': 'scope', 'visibility': 'notes_allowed',
                                  'reason': 'The motivation page makes no system energy-gain claim.'}
    policies['S2.key_points[0]'] = {'kind': 'condition', 'visibility': 'with_claim', 'applies_to': ['S2.answer']}
    policies['S2.key_points[1]'] = {'kind': 'negative_result', 'visibility': 'with_claim', 'applies_to': ['S2.answer']}
    policies['ending.limitation'] = {'kind': 'scope', 'visibility': 'required'}
    value['content_contract'] = {'version': '1.0', 'items': policies}
    return value


def evidence(story):
    result = {}
    for node in story['story']:
        text = ' '.join([node['answer'], *node.get('key_points', [])])
        for ref in node['evidence']:
            result[ref] = text
    return result


def source_design(story):
    def item(id, role, text, *refs):
        return {'id': id, 'role': role, 'text': text, 'source_refs': list(refs)}
    def visible(id):
        return {'destination': 'visible', 'carriers': [{'kind': 'copy', 'ref': id}]}
    def notes(reason):
        return {'destination': 'notes', 'reason': reason}
    pages = [
        {'id': 'P1', 'content_refs': ['S1.answer', 'S1.key_points[0]'],
         'display_copy': [item('title', 'title', 'Moving data adds a system cost', 'S1.answer'),
                          item('take', 'takeaway', 'Separate sensing and processing requires data transfer.', 'S1.answer'),
                          item('body', 'body', 'Conversion and transmission add latency and energy costs.', 'S1.answer')],
         'content_map': {'S1.answer': visible('body'), 'S1.key_points[0]': notes('No numerical energy gain is claimed on this motivation page.')}},
        {'id': 'P2', 'content_refs': ['S2.answer'],
         'display_copy': [item('title', 'title', 'Accuracy improves under the tested noisy task', 'S2.answer'),
                          item('take', 'takeaway', 'Accuracy increases from 16% to 62%.', 'S2.answer'),
                          item('condition', 'body', 'Gaussian-noise Fashion-MNIST; identical training conditions.', 'S2.key_points[0]'),
                          item('negative', 'body', 'The mechanism remains unresolved.', 'S2.key_points[1]')],
         'content_map': {'S2.answer': visible('take'), 'S2.key_points[0]': visible('condition'), 'S2.key_points[1]': visible('negative')}},
        {'id': 'P3', 'content_refs': ['S2.key_points[0]', 'S2.key_points[1]', 'S3.answer', 'S4.answer'],
         'display_copy': [item('title', 'title', 'Controls constrain the interpretation', 'S3.answer'),
                          item('take', 'takeaway', 'The independent control supports the response.', 'S3.answer'),
                          item('device', 'body', 'The device provides distinct responses in the tested settings.', 'S4.answer'),
                          item('condition', 'body', 'Gaussian-noise Fashion-MNIST; identical training conditions.', 'S2.key_points[0]'),
                          item('negative', 'body', 'The mechanism remains unresolved.', 'S2.key_points[1]')],
         'content_map': {'S3.answer': visible('take'), 'S4.answer': visible('device'),
                         'S2.key_points[0]': visible('condition'), 'S2.key_points[1]': visible('negative')}},
        {'id': 'P4', 'content_refs': ['ending.takeaway', 'ending.limitation'],
         'display_copy': [item('title', 'title', 'Evidence supports the tested response', 'ending.takeaway'),
                          item('take', 'takeaway', 'The result is supported in the tested settings.', 'ending.takeaway'),
                          item('scope', 'body', 'The tested sample limits generalization.', 'ending.limitation')],
         'content_map': {'ending.takeaway': visible('take'), 'ending.limitation': visible('scope')}}]
    for page in pages:
        page['design'] = 'Show the approved conclusion above its evidence and retain visible qualifiers beside the claim.'
    return {'schema_version': '1.2', 'deck_id': 'projection-fixture',
            'setting': {'audience': 'Peers who have not read the paper', 'occasion': 'group-meeting', 'reading': 'spoken'},
            'pages': pages}


def authored_ir(design):
    ir = read(COMPONENT/'examples/native-bullets.deck_ir.json')
    ir['deck_id'], ir['assets'], ir['slides'] = design['deck_id'], {}, []
    for page in design['pages']:
        body = [c for c in page['display_copy'] if c['role'] == 'body']
        ir['slides'].append({'id': page['id'], 'semantic': {'title': {'copy_ref': 'title'}, 'purpose': 'Explain the evidence and its scope.',
                            'takeaway': {'copy_ref': 'take'}, 'speaker_notes': 'Synthetic fixture; no model or human review claimed.', 'caveats': []},
                            'composition': {'archetype': 'composite-research', 'figure_refs': [],
                                'blocks': [{'id': c['id'], 'component': 'body', 'text': {'copy_ref': c['id']}} for c in body],
                                'layout_tree': {'version': '1.0', 'regions': {'body': {'id': 'body-stack', 'type': 'stack', 'children': [
                                    {'id': f'leaf{i}', 'type': 'block', 'ref': c['id']} for i, c in enumerate(body)]}}}}, 'presentation': {'variant': 'default'}})
    return ir


def synthetic_review(work, design):
    # Test fixture only. Runtime never constructs an automatic approval.
    return {'schema_version': '1.0', 'method': 'agent-source-review', 'reviewer': 'Synthetic test reviewer',
            'story_sha256': sha(work/'story_plan.json'), 'design_sha256': sha(work/'page_design.json'),
            'pages': [{'id': page['id'], 'checks': {key: {'status': 'pass', 'note': 'Explicit synthetic fixture review; not real scientific acceptance.'}
                                                    for key in content_review.CHECKS}} for page in design['pages']]}


class ProjectionTests(AgentCase):
    def prepare(self):
        self.story = scientific_story()
        self.design = source_design(self.story)
        self.evidence = evidence(self.story)
        work = self.out/'work'
        write(work/'story_plan.json', self.story)
        write(work/'page_design.json', self.design)
        write(work/'page_design_review.json', synthetic_review(work, self.design))
        self.bound = a.load_design(work)
        self.ir = bind_sources(authored_ir(self.design), self.bound, work, work/'draft.json')
        return work

    def test_scientific_record_can_be_faithfully_rewritten_and_optional_scope_stays_in_notes(self):
        self.prepare()
        self.assertEqual(validate_design(self.design, self.story, self.evidence, 4), [])
        jsonschema.validate(self.design, read(COMPONENT/'schemas/page-design-v1.2.schema.json'))
        self.assertEqual(a.ir_issues(self.ir, design=self.bound, slide_count=4), [])
        original = self.story['story'][0]['answer']
        page = self.ir['slides'][0]
        self.assertNotEqual(page['composition']['blocks'][0]['text'], original)
        self.assertIn(original, page['semantic']['speaker_notes'])
        self.assertNotIn('energy-saving factor', page['composition']['blocks'][0]['text'])

    def test_scoped_qualifiers_follow_the_claim_without_duplicate_ownership(self):
        self.prepare()
        page = self.ir['slides'][1]
        self.assertNotIn('S2.key_points[0]', self.design['pages'][1]['content_refs'])
        self.assertIn('S2.key_points[0]', page['semantic']['content_projection']['items'])
        self.assertIn('Gaussian-noise', page['semantic']['speaker_notes'])
        self.design['pages'][1]['content_map']['S2.key_points[0]'] = {'destination': 'notes', 'reason': 'Make the page shorter.'}
        self.assertIn('cannot be notes-only', ' '.join(validate_design(self.design, self.story, self.evidence)))

    def test_critical_numbers_conditions_and_negative_findings_cannot_survive_only_in_notes_or_metadata(self):
        self.prepare()
        for key in ('condition', 'negative'):
            ir = copy.deepcopy(self.ir)
            ir['slides'][1]['composition']['blocks'] = [b for b in ir['slides'][1]['composition']['blocks'] if b['id'] != key]
            failures = validate_projection(ir['slides'][1], {})
            self.assertTrue(any('no visible IR object' in message for _, _, message in failures), failures)
        ir = copy.deepcopy(self.ir)
        ir['slides'][1]['semantic']['takeaway'] = 'A response is measured.'
        failures = validate_projection(ir['slides'][1], {})
        self.assertTrue(any('Approved copy take' in message for _, _, message in failures))

    def test_compiled_page_objects_are_checked_separately_from_declared_ir(self):
        self.prepare()
        page = self.ir['slides'][1]
        result = validate_projection(page, {}, {'elements': [{'kind': 'text', 'text': page['semantic']['title']}]})
        self.assertTrue(any('absent from compiled' in message for _, _, message in result))

    def test_ir_cannot_add_audit_prose_or_change_approved_copy(self):
        self.prepare()
        self.ir['slides'][0]['composition']['blocks'][0]['text'] += ' This path is not a device experiment; no system saving factor is reported.'
        self.assertTrue(any('Unapproved body' in message for _, _, message in validate_projection(self.ir['slides'][0], {})))

    def test_records_and_projection_cannot_be_dropped_or_silently_edited(self):
        work = self.prepare()
        self.ir['slides'][0]['semantic']['speaker_notes'] = 'Short summary only.'
        self.assertTrue(any('scientific record' in message for _, _, message in validate_projection(self.ir['slides'][0], {})))
        self.ir['slides'][0]['semantic']['content_projection']['items']['S1.answer']['text'] = 'A changed claim.'
        with self.assertRaises(ValueError):
            bind_sources(self.ir, self.bound, work, work/'draft.json')

    def test_new_contract_cannot_downgrade_to_legacy_or_hide_controls(self):
        self.prepare()
        old = copy.deepcopy(self.design)
        old['schema_version'] = '1.1'
        with self.assertRaisesRegex(a.Failure, 'downgrade'):
            a.check_design(old, self.story, self.evidence)
        self.story['content_contract']['items']['S2.key_points[1]'] = {'kind': 'negative_result', 'visibility': 'notes_allowed', 'reason': 'Shorter.'}
        self.assertTrue(validate_contract(self.story))

    def test_source_review_is_explicit_bound_to_hashes_and_invalidates_on_copy_change(self):
        work = self.prepare()
        (work/'page_design_review.json').unlink()
        with self.assertRaises(a.Failure):
            a.load_design(work)
        write(work/'page_design_review.json', synthetic_review(work, self.design))
        self.design['pages'][0]['display_copy'][0]['text'] = 'A revised title'
        write(work/'page_design.json', self.design)
        with self.assertRaisesRegex(a.Failure, 'stale'):
            a.load_design(work)

    def test_malformed_projection_is_a_failure_and_critical_policies_are_not_guessed_from_words(self):
        self.prepare()
        for field, value in [('content_map', []), ('items', None), ('display_copy', [None]), ('review', {})]:
            page = copy.deepcopy(self.ir['slides'][0])
            page['semantic']['content_projection'][field] = value
            self.assertTrue(validate_projection(page, {}))
        for value in (None, [], {}, ''):
            design = copy.deepcopy(self.design)
            design['pages'][0]['display_copy'] = value
            self.assertTrue(validate_design(design, self.story, self.evidence))
        # The legitimate limitation can use the same wording as an audit remark; routing is
        # determined by policy/claim scope, never by a 'not reported' keyword rule.
        self.assertEqual(self.design['pages'][0]['content_map']['S1.key_points[0]']['destination'], 'notes')
        self.assertEqual(self.design['pages'][-1]['content_map']['ending.limitation']['destination'], 'visible')

    def test_story_schema_and_runtime_preserve_the_versioned_contract(self):
        self.prepare()
        from pwf2rpa import Workflow, validate_story
        flow = workflow()
        for item in flow['evidence_registry']:
            item['text'] = self.evidence.get(item['evidence_id'], 'Other synthetic evidence.')
        normalized, _ = validate_story(self.story, Workflow(flow))
        self.assertEqual(normalized['content_contract'], self.story['content_contract'])
        jsonschema.validate(self.story, read(COMPONENT/'pwf2rpa/schemas/story-plan.schema.json'))

    def test_missing_and_failed_review_checks_never_pass(self):
        work = self.prepare()
        review = synthetic_review(work, self.design)
        review['pages'][0]['checks'].pop('qualifier_scope')
        with self.assertRaises(ValueError): content_review.validate(work, review)
        review = synthetic_review(work, self.design)
        review['pages'][0]['checks']['scientific_fidelity'] = {'status': 'fail', 'note': 'The rewrite incorrectly claims measured system energy savings.'}
        with self.assertRaisesRegex(ValueError, 'rejected'): content_review.validate(work, review)

    def test_rendered_projection_ledger_and_canonical_schema_are_written(self):
        work = self.prepare()
        write(work/'draft.json', self.ir)
        jsonschema.validate(self.ir, read(COMPONENT/'schemas/deck-ir.schema.json'))
        _, _, qa = compile_input(work/'draft.json', self.out/'measured', {'name': 'packer'}, require_visual_design=False)
        self.assertEqual(qa['counts']['FAIL'], 0, qa['items'])
        ledger = read(self.out/'measured/derived/content_projection_coverage.json')
        self.assertIn('S1.key_points[0]', ledger['slides'][0]['notes_refs'])
        self.assertIn('S2.key_points[0]', ledger['slides'][1]['visible_refs'])

    def test_paper_numbers_cannot_be_turned_into_supplement_copy(self):
        self.prepare()
        item = self.design['pages'][1]['display_copy'][1]
        item.update(basis='supplement', source_refs=[], supplement={'kind': 'background', 'source': 'Constructed illustration', 'constructed': False})
        with self.assertRaises(a.Failure) as caught:
            a.check_design(self.design, self.story, self.evidence)
        self.assertIn('supplement reuses the paper value', ' '.join(caught.exception.details))

    def test_approved_supplement_copy_keeps_its_channel_and_respects_job_setting(self):
        work = self.prepare()
        self.design['pages'][0]['display_copy'].append({'id': 'example', 'role': 'body', 'text': '构造示例：示意两个模块之间的数据路径。',
            'source_refs': [], 'basis': 'supplement', 'supplement': {'kind': 'example', 'source': 'Constructed software fixture', 'constructed': True}})
        self.assertEqual(validate_design(self.design, self.story, self.evidence), [])
        write(work/'page_design.json', self.design)
        write(work/'page_design_review.json', synthetic_review(work, self.design))
        ir = bind_sources(authored_ir(self.design), a.load_design(work), work, work/'draft.json')
        block = next(b for b in ir['slides'][0]['composition']['blocks'] if b['id'] == 'example')
        self.assertEqual(block['basis'], 'supplement')
        self.assertNotIn('evidence_refs', block)
        self.assertTrue(any(i['code'] == 'SUPPLEMENT_NOT_ENABLED' for i in a.ir_issues(ir, supplement='off', design=a.load_design(work))))
        self.assertEqual(a.ir_issues(ir, supplement='both', design=a.load_design(work)), [])

    def test_a_native_visual_carrier_is_present_in_compiled_objects_and_keeps_semantic_review(self):
        work = self.prepare()
        page = self.design['pages'][1]
        page['display_copy'] += [{'id': 'input', 'role': 'label', 'text': 'Input', 'source_refs': ['S2.answer']},
                                 {'id': 'processing', 'role': 'label', 'text': 'Processing', 'source_refs': ['S2.answer']},
                                 {'id': 'output', 'role': 'label', 'text': 'Response', 'source_refs': ['S2.answer']}]
        page['content_map']['S2.answer']['carriers'] = [{'kind': 'graphic', 'ref': 'response', 'locator': 'Read the input-to-response relation.'}]
        write(work/'page_design.json', self.design)
        write(work/'page_design_review.json', synthetic_review(work, self.design))
        ir = authored_ir(self.design)
        comp = ir['slides'][1]['composition']
        comp['graphics'] = [{'id': 'response', 'type': 'process', 'nodes': [
            {'id': 'input', 'title': {'copy_ref': 'input'}}, {'id': 'processing', 'title': {'copy_ref': 'processing'}},
            {'id': 'output', 'title': {'copy_ref': 'output'}}],
                            'edges': [{'from': 'input', 'to': 'processing'}, {'from': 'processing', 'to': 'output'}]}]
        comp['layout_tree']['regions']['body']['children'].insert(0, {'id': 'graphic-leaf', 'type': 'graphic', 'ref': 'response'})
        ir = bind_sources(ir, a.load_design(work), work, work/'draft.json')
        write(work/'draft.json', ir)
        _, _, qa = compile_input(work/'draft.json', self.out/'native-visual', {'name': 'packer'}, require_visual_design=False)
        self.assertEqual(qa['counts']['FAIL'], 0, qa['items'])
        self.assertTrue(any(i['rule'] == 'CONTENT_VISUAL_SEMANTICS_REVIEW' for i in qa['items']))


class ProjectionRunnerTests(AgentCase):
    def start_design(self):
        story = scientific_story()
        flow = workflow()
        flow['evidence_registry'] = [{'evidence_id': key, 'text': text, 'query_ids': ['results'], 'modality': 'body_text',
                                     'support_type': 'direct_observation'} for key, text in evidence(story).items()]
        source = self.root/'workflow.json'
        write(source, flow)
        result = runner.start(str(source), str(self.out), 'en', 'group_meeting', source_kind='workflow', slide_count=4)
        # Explicit old prompt fixture exercises recovery of the paragraph-based 1.0 contract.
        # Atomic 2.0 generation and its earlier science gate have separate integration tests.
        execute = runner.a.execute
        def legacy_prompt(stage, job):
            paths = execute(stage, job)
            if stage == 'story_prompt':
                prompt = read(self.out/'work/story_prompt.json')
                prompt['content_contract_version'] = '1.0'
                write(self.out/'work/story_prompt.json', prompt)
            return paths
        with patch('agent.runner.a.execute', side_effect=legacy_prompt):
            result = runner.advance(result['job_id'], inputs={'model': 'test-model', 'reasoning_effort': 'high', 'selected_by_user': True})
        work = self.out/'work'
        write(work/'story_plan.json', story)
        result = runner.advance(result['job_id'], artifact_kind='story_plan', artifact_path=str(work/'story_plan.json'))
        self.assertEqual(result['stage'], 'page_design', result)
        self.assertEqual(read(work/'page_design_prompt.json')['shape']['schema_version'], '1.2')
        design = source_design(story)
        write(work/'page_design.json', design)
        result = runner.advance(result['job_id'], artifact_kind='page_design', artifact_path=str(work/'page_design.json'))
        return work, design, result

    def test_review_stage_cannot_be_skipped_and_acceptance_binds_the_review(self):
        work, design, result = self.start_design()
        self.assertEqual(result['stage'], 'page_review', result)
        self.assertFalse((work/'ir_prompt_designed.json').exists())
        write(work/'draft.json', authored_ir(design))
        skipped = runner.advance(result['job_id'], artifact_kind='deck_ir', artifact_path=str(work/'draft.json'))
        self.assertEqual(skipped['next_action']['reason'], 'ARTIFACT_STAGE_MISMATCH')
        write(work/'page_design_review.json', synthetic_review(work, design))
        result = runner.advance(result['job_id'], artifact_kind='page_design_review', artifact_path=str(work/'page_design_review.json'))
        self.assertEqual(result['stage'], 'deck_ir', result)
        prompt = read(work/'ir_prompt_designed.json')
        self.assertIn('audience copy', prompt['instructions'])
        self.assertNotIn('Preserve complete scientific body, key_points', prompt['instructions'])

    def test_malformed_review_repairs_only_the_record_but_failed_review_replans_design(self):
        work, design, result = self.start_design()
        review = synthetic_review(work, design)
        review['pages'][0]['checks'].pop('audience_copy')
        write(work/'page_design_review.json', review)
        result = runner.advance(result['job_id'], artifact_kind='page_design_review', artifact_path=str(work/'page_design_review.json'))
        self.assertEqual(result['next_action']['target_stage'], 'page_review')
        self.assertEqual(result['next_action']['reason'], 'PAGE_DESIGN_REVIEW_INVALID')
        review = synthetic_review(work, design)
        review['pages'][0]['checks']['scientific_fidelity'] = {'status': 'fail', 'note': 'A scientific statement requires redesign.'}
        write(work/'page_design_review.json', review)
        result = runner.advance(result['job_id'], artifact_kind='page_design_review', artifact_path=str(work/'page_design_review.json'))
        self.assertEqual(result['next_action']['target_stage'], 'page_design')
        self.assertEqual(result['next_action']['reason'], 'PAGE_DESIGN_REVIEW_REJECTED')

    @unittest.skipUnless(shutil.which('officecli'), 'OfficeCLI required')
    def test_new_contract_reaches_an_editable_candidate_with_existing_qa(self):
        work, design, result = self.start_design()
        write(work/'page_design_review.json', synthetic_review(work, design))
        result = runner.advance(result['job_id'], artifact_kind='page_design_review', artifact_path=str(work/'page_design_review.json'))
        write(work/'draft.json', authored_ir(design))
        result = runner.advance(result['job_id'], artifact_kind='deck_ir', artifact_path=str(work/'draft.json'))
        self.assertEqual(result['status'], 'candidate_ready', result)
        self.assertEqual(result['qa']['counts']['FAIL'], 0)
        self.assertTrue((self.out/'build/candidate.pptx').is_file())
        self.assertTrue((self.out/'build/derived/content_projection_coverage.json').is_file())
