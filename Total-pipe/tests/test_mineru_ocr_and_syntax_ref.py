"""Regression tests for:
1. Direct MinerU CLI PDF OCR stage (ocr -> queries with outline -> evidence reusing OCR Markdown).
2. Complete Deck IR syntax & feature reference handbook wired into page_design & deck_ir prompts.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import unittest
from unittest.mock import patch

from agent import COMPONENT, adapters as a, ir_pages, mineru_cli, prompts, runner
from agent.state import read, write
from agent_fixture import AgentCase


SAMPLE_OCR_MD = """# Field-Modulated Photonic Response

## Abstract
The measured response increases from 2 to 4 units at 300 K with 98.58% reproducibility.

## Methods
Devices were fabricated by atomic layer deposition and tested at 300 K under 1 V bias.
Independent baseline controls without the barrier were measured under identical conditions.

## Results
The response doubled across three independent samples. ![Fig. 1](images/fig1.png)

## Discussion and Limitations
Thermal leakage degrades performance above 350 K; the small sample size limits generalization.
"""


def _fake_mineru_cli(command, args, *, timeout, env):
    argv = [*command, *args]
    out_idx = argv.index('-o') + 1
    out_dir = Path(argv[out_idx])
    pdf_path = Path(argv[argv.index('extract') + 1])
    stem_dir = out_dir / pdf_path.stem
    (stem_dir / 'images').mkdir(parents=True, exist_ok=True)
    (stem_dir / 'images' / 'fig1.png').write_bytes(b'\x89PNG\r\n\x1a\nfake')
    (stem_dir / 'full.md').write_text(SAMPLE_OCR_MD, encoding='utf-8')
    return subprocess.CompletedProcess(argv, 0, 'Extracted successfully', '')


class DirectMinerUCliTests(AgentCase):
    def test_extract_pdf_invokes_mineru_cli_and_reuses_sha_cache(self):
        pdf = self.root / 'paper.pdf'
        pdf.write_bytes(b'%PDF-1.4 synthetic paper')
        out_root = self.out / 'ocr'

        with patch('agent.mineru_cli._run_cli', side_effect=_fake_mineru_cli) as mock_run:
            first = mineru_cli.extract_pdf(pdf, out_root, overrides={'cli_command': 'mineru-open-api'})
            self.assertEqual(mock_run.call_count, 1)
            cmd, args = mock_run.call_args.args[:2]
            argv = [*cmd, *args]
            self.assertEqual(argv[:2], ['mineru-open-api', 'extract'])
            self.assertIn('-f', argv)
            self.assertIn('md', argv)
            self.assertFalse(first['cache_hit'])
            self.assertTrue(Path(first['markdown_path']).is_file())
            self.assertTrue(Path(first['images_dir']).is_dir())
            self.assertTrue(any('Methods' in item['heading'] for item in first['outline']))

            # Second extraction of identical PDF bytes must hit SHA cache without invoking CLI.
            second = mineru_cli.extract_pdf(pdf, out_root, overrides={'cli_command': 'mineru-open-api'})
            self.assertEqual(mock_run.call_count, 1)
            self.assertTrue(second['cache_hit'])
            self.assertEqual(first['markdown_path'], second['markdown_path'])

    def test_windows_cmd_shim_fallback_resolves_via_shutil_which(self):
        calls = []

        def side_effect(argv, **kwargs):
            calls.append(argv)
            if argv[0] == 'mineru-open-api':
                raise FileNotFoundError('bare command fails on Windows for .CMD')
            return subprocess.CompletedProcess(argv, 0, 'Token is valid', '')

        with (
            patch('agent.mineru_cli.os.name', 'nt'),
            patch('agent.mineru_cli.shutil.which', return_value=r'C:\npm\mineru-open-api.CMD'),
            patch('agent.mineru_cli.subprocess.run', side_effect=side_effect),
        ):
            auth = mineru_cli.verify_auth(overrides={'cli_command': 'mineru-open-api'})
        self.assertTrue(auth['verified'])
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1][0], r'C:\npm\mineru-open-api.CMD')

    def test_pdf_job_runs_ocr_stage_before_queries_and_passes_ocr_md_to_evidence(self):
        pdf = self.root / 'study.pdf'
        pdf.write_bytes(b'%PDF-1.4 main study')
        si_pdf = self.root / 'study_si.pdf'
        si_pdf.write_bytes(b'%PDF-1.4 supplementary study')

        with patch('agent.mineru_cli._run_cli', side_effect=_fake_mineru_cli) as mock_run:
            state = runner.start(
                str(pdf),
                str(self.out),
                'zh',
                'group_meeting',
                supplementary_paths=[str(si_pdf)],
            )
        self.assertEqual(state['stage'], 'queries', state)
        self.assertEqual(mock_run.call_count, 2)  # primary PDF + supplementary PDF
        self.assertTrue(Path(state['next_action']['ocr_markdown_path']).is_file())
        self.assertTrue(any('Results' in h['heading'] for h in state['next_action']['outline']))

        ocr_record = read(self.out / 'work/ocr_result.json')
        self.assertEqual(ocr_record['mode'], 'direct_cli')
        self.assertEqual(len(ocr_record['supplementary']), 1)
        self.assertTrue(Path(ocr_record['supplementary'][0]['markdown_path']).is_file())

        # Submit queries and verify evidence stage forwards ocr_markdown_path without re-running MinerU CLI.
        queries_path = self.out / 'work/queries.json'
        write(queries_path, [
            {'id': 'q1', 'query': 'measured response 300 K', 'intent': 'key_results'},
            {'id': 'q2', 'query': 'fabrication methods baseline controls', 'intent': 'methods'},
            {'id': 'q3', 'query': 'thermal leakage limitations 350 K', 'intent': 'limitations'},
        ])
        with patch('agent.mineru_cli._run_cli', side_effect=AssertionError('OCR must not run twice')):
            after_q = runner.advance(state['job_id'], artifact_kind='queries', artifact_path=str(queries_path))
        ev_args = read(self.out / 'work/evidence_args.json')
        self.assertEqual(ev_args['ocr_markdown_path'], ocr_record['markdown_path'])
        self.assertEqual(ev_args['ingestion']['mode'], 'direct_cli')
        self.assertIn(after_q['stage'], ('model_selection', 'queries'))

    def test_pdf_job_with_presupplied_queries_runs_ocr_then_evidence(self):
        pdf = self.root / 'presupplied.pdf'
        pdf.write_bytes(b'%PDF-1.4 presupplied queries')
        queries = [
            {'id': 'q1', 'query': 'measured response 300 K', 'intent': 'key_results'},
            {'id': 'q2', 'query': 'fabrication methods controls', 'intent': 'methods'},
            {'id': 'q3', 'query': 'thermal leakage limitations', 'intent': 'limitations'},
        ]
        with patch('agent.mineru_cli._run_cli', side_effect=_fake_mineru_cli) as mock_run:
            state = runner.start(str(pdf), str(self.out), 'zh', 'group_meeting', queries=queries)
        self.assertEqual(mock_run.call_count, 1)
        self.assertTrue((self.out / 'work/ocr_result.json').is_file())
        self.assertTrue((self.out / 'work/evidence_args.json').is_file())
        self.assertEqual(
            read(self.out / 'work/evidence_args.json')['ocr_markdown_path'],
            read(self.out / 'work/ocr_result.json')['markdown_path'],
        )
        self.assertEqual(state['stage'], 'model_selection', state)


class DeckIRSyntaxReferenceTests(AgentCase):
    def test_syntax_handbook_exists_has_valid_json_blocks_and_covers_all_features(self):
        doc_path = COMPONENT / 'docs/deck-ir-syntax-reference.md'
        self.assertTrue(doc_path.is_file())
        text = doc_path.read_text(encoding='utf-8')

        # Every JSON example block in the handbook must be valid JSON.
        blocks = re.findall(r'```json\s*\n(.*?)\n[ \t]*```', text, re.S)
        self.assertGreaterEqual(len(blocks), 10)
        for idx, block in enumerate(blocks):
            try:
                json.loads(block)
            except json.JSONDecodeError as exc:
                self.fail(f'JSON block #{idx + 1} in deck-ir-syntax-reference.md is invalid: {exc}\n{block}')

        for required_token in (
            'layout_tree', 'panel', 'title_band', 'image_grid', 'caption_for', 'text_for',
            'native_bullet_list', 'native_numbered_list', 'process', 'dag', 'mechanism',
            'architecture', 'funnel', 'path', 'composite', 'charts', 'tables',
            'visual_style', 'academic_design', 'copy_ref', 'example_lookup', '无需翻阅',
        ):
            self.assertIn(required_token, text)

    def test_syntax_reference_path_is_wired_into_prompts_and_descriptors(self):
        expected = str(COMPONENT / 'docs/deck-ir-syntax-reference.md')

        prompt = a.ir_prompt({}, {}, {}, {})
        self.assertEqual(prompt['syntax_reference_path'], expected)
        self.assertIn('syntax_reference_path', prompt['instructions'])
        self.assertIn('example_lookup', prompt['instructions'])

        work = self.out / 'work'
        write(work / 'page_design_prompt.json', {'schema_path': str(COMPONENT / 'schemas/page-design.schema.json')})
        write(work / 'ir_prompt_designed.json', {})
        write(work / 'page_design.json', {
            'schema_version': '1.1',
            'pages': [{'id': 'P1', 'content_refs': [], 'design': 'Two-column comparison layout.'}],
        })
        ir_pages.prepare_prompts(
            work,
            read(work / 'page_design.json'),
            {**prompt, 'story': {'story': [], 'ending': {}}, 'evidence': {}, 'figures': []},
        )
        page_prompt = read(work / 'ir_page_prompts/P1.json')
        self.assertEqual(page_prompt['syntax_reference_path'], expected)

        job = {'job_id': 'job-ref', 'request': {'out_dir': str(self.out), 'source_kind': 'markdown', 'page_mode': 'deck_ir'}, 'ir_pages': {}, 'checkpoints': {}}
        desc = ir_pages.descriptor(job, 'up-1')
        self.assertEqual(desc['syntax_reference_path'], expected)

        design_stage = next(s for s in runner.STAGES if s['id'] == 'page_design')
        design_env = runner.envelope(job, design_stage)
        self.assertEqual(design_env['next_action']['co_design']['syntax_reference_path'], expected)

        ir_stage = next(s for s in runner.STAGES if s['id'] == 'deck_ir')
        ir_env = runner.envelope(job, ir_stage, upstream='up-1')
        self.assertEqual(ir_env['next_action']['syntax_reference_path'], expected)

        self.assertIn('syntax_reference_path', prompts.design_task({'story': {'content_contract': {'version': '2.0'}}}))
        self.assertIn('syntax_reference_path', prompts.ir_task({'page_design': {'schema_version': '1.3', 'pages': []}}))
        self.assertIn('example_lookup', prompts.ir_task({'page_design': {'schema_version': '1.3', 'pages': []}}))


if __name__ == '__main__':
    unittest.main()
