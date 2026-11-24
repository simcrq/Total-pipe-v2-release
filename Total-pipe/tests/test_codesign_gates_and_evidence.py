"""Regression tests for:
1. Co-design live single-page IR preview/preflight during page_design + max 2 IR subagents.
2. Concrete design quality gates, design audit, and raised revision budgets.
3. Unified evidence retrieval for Story Planner (story_prompt, CLI, and MCP advance.evidence_query).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from agent import COMPONENT, adapters as a, evidence_search, ir_pages, runner, topic
from agent.state import locate, read, save, write
from agent_fixture import AgentCase
from deck_compiler.design import audit_design_quality, validate_design


def _base_v13_design(pages):
    return {
        'schema_version': '1.3',
        'deck_id': 'codesign-test',
        'setting': {'audience': 'Domain peers', 'occasion': 'group-meeting', 'reading': 'spoken'},
        'pages': pages,
    }


def _v13_story():
    return {
        'title': 'Field response study',
        'content_contract': {
            'version': '2.0',
            'units': {
                'U1': {
                    'kind': 'finding',
                    'epistemic': 'observed',
                    'visibility': 'required',
                    'text': 'Response doubles from 2 to 4 units at 300 K.',
                    'evidence': ['EV0001'],
                },
                'U2': {
                    'kind': 'condition',
                    'epistemic': 'observed',
                    'visibility': 'required',
                    'text': 'Measured under 1 V bias across three samples.',
                    'evidence': ['EV0002'],
                },
            },
            'narrative_map': [
                {'slide_role': 'finding', 'unit_ids': ['U1', 'U2']},
            ],
        },
        'nodes': [
            {
                'title': 'Measured field response',
                'question': 'How does the response change?',
                'answer': 'Response doubles from 2 to 4 units at 300 K.',
                'evidence': ['EV0001'],
            }
        ],
        'ending': {
            'takeaway': 'Field doubles the response.',
            'limitation': 'Limited to three samples at 300 K.',
            'evidence': ['EV0002'],
        },
    }


def _v13_evidence():
    return {
        'figures': [{'id': 'FIG001', 'caption': 'Response vs field at 300 K.'}],
        'evidence': [
            {'evidence_id': 'EV0001', 'text': 'Response doubles from 2 to 4 units at 300 K.'},
            {'evidence_id': 'EV0002', 'text': 'Measured under 1 V bias across three samples.'},
        ],
    }


class CoDesignAndBatchCapTests(AgentCase):
    def _prepare_paper_job_at_page_design(self):
        # Start a minimal paper-mode job, then position it at page_design with a real page_design_prompt.json.
        with patch('agent.runner.a.execute', side_effect=a.Failure(
                'INSUFFICIENT_DRAWING_SPACE', 'Fixture stops at IR.', 'replan', 'deck_ir')):
            res = runner.start(str(COMPONENT / 'examples/native-bullets.deck_ir.json'),
                               str(self.out), 'zh', 'group_meeting')
        job_id = res['job_id']
        work = self.out / 'work'
        write(work / 'story_plan.json', {
            'story': [{'title': 'Field response', 'answer': 'Response doubles at 300 K.',
                       'key_points': ['Verified across three samples.'], 'evidence': ['EV0001']}],
            'ending': {'takeaway': 'Field-driven response is reproducible.', 'limitation': 'Tested at 300 K.'},
        })
        write(work / 'normalized_content.json', {'status': 'valid', 'slides': []})
        write(work / 'page_design_prompt.json', {
            'co_design': {
                'enabled': True,
                'draft_pages_dir': str(work / 'pages'),
                'max_ir_subagents': 2,
            }
        })
        _, job = locate(job_id)
        job['request']['source_kind'] = 'markdown'
        job['request']['page_mode'] = 'deck_ir'
        job.pop('last_error', None)
        save(job)
        stage = next(s for s in runner.STAGES if s['id'] == 'page_design')
        return job_id, work, job, stage

    def test_live_single_page_preview_and_preflight_work_during_page_design(self):
        job_id, work, job, stage = self._prepare_paper_job_at_page_design()

        # Check envelope at page_design exposes ir_preview and co_design metadata
        env = runner.envelope(job, stage)
        self.assertTrue(env.get('ir_preview'))
        co_design = env['next_action'].get('co_design')
        self.assertIsInstance(co_design, dict)
        self.assertEqual(co_design['max_ir_subagents'], 2)
        self.assertEqual(Path(co_design['draft_pages_dir']), work / 'pages')

        # Write a standalone single-page IR draft under work/pages/P1.json before page_design.json exists.
        draft_ir = read(COMPONENT / 'examples/native-bullets.deck_ir.json')
        draft_ir['slides'] = [copy.deepcopy(draft_ir['slides'][0])]
        draft_ir['slides'][0]['id'] = 'P1'
        draft_path = work / 'pages/P1.json'
        write(draft_path, draft_ir)
        job_before = (self.out / '.totalpipe/job.json').read_bytes()

        with patch('agent.runner.current', return_value=(stage, 'synthetic-upstream')):
            preview = runner.advance(job_id, preview={'artifact_path': str(draft_path),
                                                      'slide_ids': ['P1'], 'mode': 'layout'})
            self.assertEqual(preview['preview_result']['status'], 'PASS', preview)
            self.assertTrue(preview['preview_result']['design_draft_mode'])
            self.assertTrue(Path(preview['preview_result']['pages'][0]['skeleton_png']).is_file())
            self.assertEqual(job_before, (self.out / '.totalpipe/job.json').read_bytes())

            preflight = runner.advance(job_id, artifact_kind='deck_ir',
                                       artifact_path=str(draft_path), preflight=True)
            self.assertTrue(preflight['preflight_result']['job_unchanged'])
            self.assertTrue(preflight['preflight_result']['design_draft_mode'])
            self.assertTrue(preflight['preflight_result']['geometry_checked'])
            self.assertEqual(job_before, (self.out / '.totalpipe/job.json').read_bytes())

    def test_ir_pages_caps_parallel_subagents_at_two_and_marks_existing_drafts(self):
        work = self.out / 'work'
        pages = [
            {'id': f'P{i}', 'content_refs': [], 'design': f'Slide {i} multi-zone diagram layout.'}
            for i in range(1, 11)
        ]
        write(work / 'page_design.json', {'schema_version': '1.1', 'pages': pages})
        write(work / 'pages/P1.json', {'slides': [{'id': 'P1'}]})
        job = {'job_id': 'job-batch', 'request': {'out_dir': str(self.out)}, 'ir_pages': {}}
        desc = ir_pages.descriptor(job, 'up-1')
        pa = desc['parallel_authoring']
        self.assertEqual(pa['max_subagents'], 2)
        self.assertEqual(len(pa['batches']), 2)
        self.assertEqual(pa['batches'][0]['page_ids'], ['P1', 'P2', 'P3', 'P4', 'P5'])
        self.assertEqual(pa['batches'][1]['page_ids'], ['P6', 'P7', 'P8', 'P9', 'P10'])
        self.assertTrue(desc['pages'][0]['draft_exists'])
        self.assertFalse(desc['pages'][1]['draft_exists'])

        # Single pending page only creates 1 batch, never exceeding 2.
        job['ir_pages'] = {'upstream': 'up-1', 'records': {f'P{i}': {'sha': 'ok'} for i in range(2, 11)}}
        desc_one = ir_pages.descriptor(job, 'up-1')
        self.assertEqual(len(desc_one['parallel_authoring']['batches']), 1)
        self.assertEqual(desc_one['parallel_authoring']['batches'][0]['page_ids'], ['P1'])


class DesignGatesAndBudgetsTests(unittest.TestCase):
    def test_revision_budgets_are_raised(self):
        stages = {s['id']: s for s in runner.STAGES}
        self.assertGreaterEqual(stages['queries']['max_attempts'], 5)
        self.assertGreaterEqual(stages['story']['max_attempts'], 5)
        self.assertGreaterEqual(stages['scientific_review']['max_attempts'], 4)
        self.assertGreaterEqual(stages['page_design']['max_attempts'], 6)
        self.assertGreaterEqual(stages['page_review']['max_attempts'], 4)
        self.assertGreaterEqual(stages['page_scene']['max_attempts'], 6)
        self.assertGreaterEqual(stages['deck_ir']['max_attempts'], 6)
        self.assertGreaterEqual(stages['visual_design']['max_attempts'], 5)
        self.assertGreaterEqual(ir_pages.MAX_REJECTED_REVISIONS_PER_PAGE, 6)
        self.assertGreaterEqual(runner.MAX_REPAIR_ATTEMPTS, 5)

    def test_v13_design_gates_catch_vague_duplicate_overloaded_and_missing_readout(self):
        story = _v13_story()
        evidence = _v13_evidence()
        bad_page = {
            'id': 'P1',
            'content_refs': ['U1', 'U2'],
            'reuse_refs': [],
            'figures': ['FIG001'],
            'figure_sources': {'FIG001': 'Fig. 1'},
            'design': 'TBD',
            'display_copy': [
                {'id': 'c_title', 'role': 'title', 'text': 'Response doubles at 300 K'},
                {'id': 'c_take', 'role': 'takeaway', 'text': 'Response doubles at 300 K'},
                *[{'id': f'c_b{i}', 'role': 'body', 'text': f'Body point {i}.'} for i in range(1, 8)],
            ],
            'content_map': {
                'U1': {'destination': 'visible', 'copy_ids': ['c_b1'], 'carriers': [{'kind': 'text'}]},
                'U2': {'destination': 'visible', 'copy_ids': ['c_b2'], 'carriers': [{'kind': 'figure'}]},
            },
        }
        problems = validate_design(_base_v13_design([bad_page]), story, evidence)
        joined = '\n'.join(problems)
        self.assertIn('DESIGN_TOO_VAGUE', joined)
        self.assertIn('DESIGN_TITLE_TAKEAWAY_DUPLICATE', joined)
        self.assertIn('DESIGN_BODY_OVERLOADED', joined)
        self.assertIn('DESIGN_FIGURE_READOUT_MISSING', joined)

    def test_design_audit_flags_low_visual_diversity_for_text_only_deck(self):
        text_only = _base_v13_design([
            {'id': f'P{i}', 'content_refs': [f'U{i}'], 'figures': [],
             'design': 'Place three short sentences stacked vertically from top to bottom.'}
            for i in range(1, 5)
        ])
        audit = audit_design_quality(text_only)
        self.assertEqual(audit['visual_pages'], 0)
        self.assertEqual(audit['visual_ratio'], 0.0)
        self.assertEqual(audit['text_only_risk_pages'], ['P1', 'P2', 'P3', 'P4'])
        self.assertTrue(any(w['code'] == 'DESIGN_LOW_VISUAL_DIVERSITY' for w in audit['warnings']))

    def test_topic_check_design_rejects_vague_placeholder(self):
        with self.assertRaises(ValueError) as ctx:
            topic.check_design({
                'schema_version': 'topic-1.0',
                'deck_id': 'test-topic',
                'pages': [{'id': 'P1', 'design': '默认排版'}],
            })
        self.assertIn('DESIGN_TOO_VAGUE', str(ctx.exception))


class EvidenceRetrievalIntegrationTests(AgentCase):
    def _build_workflow_fixture(self):
        work = self.out / 'work'
        work.mkdir(parents=True, exist_ok=True)
        paper_md = self.root / 'paper.md'
        paper_md.write_text(
            '# Field Response Study\n\n'
            '# Abstract\n'
            'The response increases from 2 to 4 units with 98.58% reproducibility at 300 K.\n\n'
            '# Theoretical Model\n'
            'The barrier response obeys:\n\n'
            '$$R(E) = R_0 \\exp(\\alpha E / k_B T)$$\n\n'
            'As shown in Fig. 2b, the control without bias stays flat.\n\n'
            '# Unindexed Detail\n'
            'An extra cryogenic calibration at 77 K showed zero hysteresis drift.\n',
            encoding='utf-8',
        )
        si_md = self.root / 'supplementary.md'
        si_md.write_text(
            '# Supplementary Note 1\n'
            'Extended endurance testing over 10000 cycles at 300 K confirmed <1.2% drift.\n',
            encoding='utf-8',
        )
        wf_path = work / 'workflow.json'
        wf = {
            'schema_version': 4,
            'source': {'markdown_path': str(paper_md)},
            'related_documents': [{'role': 'supplementary', 'markdown_path': str(si_md)}],
            'evidence_registry': [
                {
                    'evidence_id': 'EV0001',
                    'modality': 'text',
                    'support_type': 'empirical',
                    'heading': 'Abstract',
                    'query_ids': ['Q1'],
                    'text': 'The response increases from 2 to 4 units with 98.58% reproducibility at 300 K.',
                },
                {
                    'evidence_id': 'EV0002',
                    'modality': 'text',
                    'support_type': 'empirical',
                    'heading': 'Theoretical Model',
                    'query_ids': ['Q2'],
                    'text': 'As shown in Fig. 2b, the control without bias stays flat.',
                },
            ],
        }
        write(wf_path, wf)
        write(work / 'evidence_pointer.json', {'workflow': str(wf_path)})
        return work, wf_path, paper_md, si_md

    def test_search_outline_and_read_lines_cover_registry_source_and_si(self):
        _, wf_path, _, si_md = self._build_workflow_fixture()

        outline = evidence_search.document_outline(wf_path)
        self.assertEqual(outline['registry_count'], 2)
        self.assertTrue(any('Theoretical Model' in (s['heading'] or '') for s in outline['sections']))

        # Bilingual + numeric query hits registry EV0001 and source Markdown
        res = evidence_search.search_evidence(wf_path, '98.58% 对照', scope='all')
        self.assertTrue(any(h['evidence_id'] == 'EV0001' for h in res['registry_hits']))
        self.assertTrue(any(h['evidence_id'] == 'EV0002' for h in res['registry_hits']))

        # Formula modality query finds the display equation in source Markdown
        formula = evidence_search.search_evidence(wf_path, '公式 推导', scope='source', modality='formula')
        self.assertTrue(any('R_0' in h['snippet'] for h in formula['source_hits']), formula)

        # Unindexed passage is returned from source with not_in_registry=True
        gap = evidence_search.search_evidence(wf_path, '77 K cryogenic hysteresis', scope='source')
        self.assertTrue(gap['source_hits'])
        self.assertTrue(gap['source_hits'][0]['not_in_registry'])

        # Supplementary search hits paired SI markdown
        si = evidence_search.search_evidence(wf_path, '10000 cycles endurance', scope='supplementary')
        self.assertTrue(si['supplementary_hits'])
        self.assertIn('1.2%', si['supplementary_hits'][0]['snippet'])

        # Exact line reader works for both main paper and SI, and blocks arbitrary files
        slice_main = evidence_search.read_source_lines(wf_path, 1, 5)
        self.assertIn('1: # Field Response Study', slice_main['text'])
        slice_si = evidence_search.read_source_lines(wf_path, 1, 3, file_path=str(si_md))
        self.assertIn('10000 cycles', slice_si['text'])
        outside = self.root / 'secret.md'
        outside.write_text('do not read', encoding='utf-8')
        with self.assertRaises(ValueError):
            evidence_search.read_source_lines(wf_path, 1, 2, file_path=str(outside))

    def test_cli_and_runner_advance_evidence_query_are_read_only(self):
        work, wf_path, _, _ = self._build_workflow_fixture()

        # Verify standalone CLI invocation (the path Story Planner subagents use)
        proc = subprocess.run(
            [sys.executable, '-m', 'agent.evidence_search', '--workflow', str(wf_path),
             'search', 'Fig. 2b 对照', '--top-k', '4'],
            cwd=str(COMPONENT),
            capture_output=True,
            text=True,
            check=True,
        )
        cli_data = json.loads(proc.stdout)
        self.assertTrue(any(h['evidence_id'] == 'EV0002' for h in cli_data['registry_hits']))

        # Verify lookup_descriptor includes CLI prefix, MCP call, outline, and registry_summary
        desc = evidence_search.lookup_descriptor(wf_path, job_id='job-ev-1')
        self.assertEqual(desc['registry_summary']['count'], 2)
        self.assertEqual(desc['mcp_call']['tool'], 'totalpipe_advance')
        self.assertEqual(desc['mcp_call']['arguments']['job_id'], 'job-ev-1')
        self.assertTrue(desc['outline'])

        # Wire a paper job paused at story stage and invoke runner.advance(evidence_query=...)
        with patch('agent.runner.a.execute', side_effect=a.Failure(
                'INSUFFICIENT_DRAWING_SPACE', 'Fixture stops.', 'replan', 'deck_ir')):
            res = runner.start(str(COMPONENT / 'examples/native-bullets.deck_ir.json'),
                               str(self.out), 'zh', 'group_meeting')
        job_id = res['job_id']
        _, job = locate(job_id)
        job['request']['source_kind'] = 'markdown'
        job.pop('last_error', None)
        save(job)
        story_stage = next(s for s in runner.STAGES if s['id'] == 'story')
        before = (self.out / '.totalpipe/job.json').read_bytes()

        with patch('agent.runner.current', return_value=(story_stage, 'up-story')):
            status_env = runner.status(job_id)
            self.assertIn('evidence_lookup', status_env)
            self.assertEqual(status_env['evidence_lookup']['argument'], 'evidence_query')

            ev_res = runner.advance(job_id, evidence_query={'operation': 'search', 'query': '98.58%', 'top_k': 4})
            self.assertEqual(ev_res['evidence_result']['status'], 'PASS')
            self.assertTrue(ev_res['evidence_result']['job_unchanged'])
            self.assertTrue(any(h['evidence_id'] == 'EV0001' for h in ev_res['evidence_result']['registry_hits']))
            self.assertEqual(before, (self.out / '.totalpipe/job.json').read_bytes())

            out_res = runner.advance(job_id, evidence_query={'operation': 'outline'})
            self.assertEqual(out_res['evidence_result']['status'], 'PASS')
            self.assertEqual(out_res['evidence_result']['registry_count'], 2)

            lines_res = runner.advance(job_id, evidence_query={'operation': 'read_lines', 'start': 1, 'end': 4})
            self.assertEqual(lines_res['evidence_result']['status'], 'PASS')
            self.assertIn('Field Response Study', lines_res['evidence_result']['text'])
            self.assertEqual(before, (self.out / '.totalpipe/job.json').read_bytes())


if __name__ == '__main__':
    unittest.main()
