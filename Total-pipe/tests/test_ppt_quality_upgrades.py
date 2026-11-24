import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont

from agent import COMPONENT, runner
from agent.figure_crop import auto_detect_panels, crop_figure, inspect_figure
from agent.ir_preview import build_visual_checklist
from agent.state import read, sha, write
from deck_compiler.crops import verified_source
from deck_compiler.design import audit_design_quality
from deck_compiler.fonts import resolve_theme_fonts
from deck_compiler.graphic_layout import normalize_graphic_label
from deck_compiler.ir import validate
from deck_compiler.layout import break_lines, compile_deck
from deck_compiler.layout_feedback import make_feedback
from deck_compiler.visual_planner import make_prompt
from deck_compiler.whitespace import analyze_rendered_png_whitespace


def _base_deck(slides, assets=None):
    return {
        'schema_version': '2.0',
        'deck_id': 'quality-upgrades-test',
        'theme': {
            'font_family': 'Arial',
            'font_file': 'arial.ttf',
            'bold_font_file': 'arialbd.ttf',
            'accent': '#266E72',
            'foreground': '#142735',
            'background': '#FFFFFF',
        },
        'presentation': {
            'academic_design': {
                'style': 'research-seminar',
                'title_treatment': 'thin-rule',
                'density': 'balanced',
                'figure_treatment': 'unframed',
                'decoration_policy': 'minimal',
                'header_variant': 'compact',
            },
            'text_capacity_policy': 'preserve-terms',
        },
        'assets': assets or {},
        'slides': slides,
    }


class PptQualityUpgradeTests(unittest.TestCase):
    def test_chart_two_row_legend_hbar_categories_and_collision_avoidance(self):
        chart = {
            'id': 'ablation-hbar',
            'kind': 'hbar',
            'basis': 'explain',
            'illustrative': True,
            'x': {'label': 'Variant', 'categories': ['Full Model', 'w/o Residual', 'w/o Alignment', 'Single Stream']},
            'y': {'label': 'Macro F1', 'unit': '%', 'min': 50, 'max': 100},
            'series': [
                {'id': 's1', 'label': 'Dataset Alpha Benchmark', 'values': [94.2, 86.5, 80.1, 71.0]},
                {'id': 's2', 'label': 'Dataset Beta Cross-Domain', 'values': [91.8, 83.2, 77.4, 68.5]},
                {'id': 's3', 'label': 'Noisy Stress Regime 20dB', 'values': [89.0, 79.4, 73.0, 64.2]},
            ],
            'reference_lines': [
                {'axis': 'y', 'value': 90.0, 'label': 'Target 90%', 'style': 'dashed'},
            ],
            'shaded_zones': [
                {'axis': 'y', 'low': 88.0, 'high': 100.0, 'label': 'Deployable'},
            ],
            'annotations': [
                {'text': '+23.2 pt gain', 'series': 0, 'point': 0, 'dx': 0, 'dy': 0},
            ],
        }
        slide = {
            'id': 's1',
            'semantic': {
                'title': 'Horizontal ablation chart supports categories, zones and two-row legends',
                'purpose': 'Test chart primitives',
                'takeaway': 'Wide legends wrap cleanly into two rows and annotations avoid bar collisions.',
                'evidence_refs': [],
                'caveats': [],
                'speaker_notes': 'Synthetic ablation benchmark.',
            },
            'composition': {
                'archetype': 'composite-research',
                'blocks': [],
                'figure_refs': [],
                'graphics': [],
                'charts': [chart],
                'layout_tree': {
                    'version': '1.2',
                    'regions': {'body': {'id': 'c1', 'type': 'chart', 'ref': 'ablation-hbar'}},
                },
            },
            'presentation': {},
        }
        deck = _base_deck([slide])
        ir_errors = [i for i in validate(deck) if i['severity'] == 'FAIL']
        self.assertEqual(ir_errors, [])
        layout, issues = compile_deck(deck, COMPONENT)
        fails = [i for i in issues if i['severity'] == 'FAIL']
        self.assertEqual(fails, [])
        elems = layout['slides'][0]['elements']
        self.assertTrue(any(':ref:' in e['id'] for e in elems))
        self.assertTrue(any(':zone:' in e['id'] for e in elems))
        self.assertTrue(any(':bar:' in e['id'] for e in elems))
        legend_ys = {round(e['bbox'][1], 1) for e in elems if ':legend:' in e['id'] and e['kind'] == 'text'}
        self.assertGreaterEqual(len(legend_ys), 2)

    def test_cjk_orphan_wrap_rebalance_and_graphic_symbol_normalization(self):
        regular, _, _ = resolve_theme_fonts({'font_family': 'Microsoft YaHei'}, COMPONENT, '有效势垒降低')
        face = ImageFont.truetype(regular, 28)
        text = '外加偏压使界面有效势垒降低'
        # Choose width where naive greedy wrap leaves 1-char final line "低".
        full_w = face.getlength(text)
        one_less_w = face.getlength(text[:-1])
        lines = break_lines(text, face, one_less_w + 1.0)
        self.assertGreaterEqual(len(lines), 2)
        self.assertGreaterEqual(len(lines[-1].strip()), 2, lines)
        self.assertEqual(''.join(lines), text)
        self.assertEqual(
            normalize_graphic_label(r'Gain >= 3.2 \times 10^2 -> \Delta \Phi <= 0.1 \pm 0.02'),
            'Gain ≥ 3.2 × 10^2 → Δ Φ ≤ 0.1 ± 0.02',
        )

    def test_layout_tree_elastic_micro_fit_and_subtree_breakdown(self):
        def make_stack_deck(block_count, gap='spacious', panel_padding='standard'):
            blocks = [
                {'id': f'b{i}', 'component': 'body',
                 'text': f'第 {i} 组实验条件保持采样窗口一致并记录稳态均值响应。'}
                for i in range(1, block_count + 1)
            ]
            children = [
                {
                    'id': f'p{i}',
                    'type': 'panel',
                    'title': f'模块 {i}',
                    'padding': panel_padding,
                    'gap': gap,
                    'body': {'id': f'leaf-{i}', 'type': 'block', 'ref': f'b{i}'},
                }
                for i in range(1, block_count + 1)
            ]
            slide = {
                'id': 'elastic-slide',
                'semantic': {
                    'title': '布局树弹性间距微调与子树高度分解测试',
                    'purpose': 'Test elastic fit',
                    'takeaway': '轻微间距超限自动收紧容器留白，严重超限返回逐节点高度分解。',
                    'evidence_refs': [],
                    'caveats': [],
                    'speaker_notes': 'Elastic micro-fit test.',
                },
                'composition': {
                    'archetype': 'composite-research',
                    'blocks': blocks,
                    'figure_refs': [],
                    'graphics': [],
                    'layout_tree': {
                        'version': '1.2',
                        'regions': {'body': {'id': 'root', 'type': 'stack', 'gap': gap, 'children': children}},
                    },
                },
                'presentation': {},
            }
            return _base_deck([slide])

        # 3 spacious panels require 3*136 + 2*32 = 472 px vs ~450 px body height (+22 px <= 27 px elastic cap).
        rescued_deck = make_stack_deck(3, gap='spacious', panel_padding='standard')
        layout, issues = compile_deck(rescued_deck, COMPONENT)
        self.assertEqual([i for i in issues if i['severity'] == 'FAIL'], [])
        self.assertTrue(any(i['rule'] == 'ELASTIC_MICRO_FIT' for i in issues), issues)
        self.assertEqual(layout['slides'][0]['elements'][-1]['bbox'][2] > 0, True)

        # 5 panels exceed body height far beyond elastic cap -> subtree_breakdown must be reported.
        overflow_deck = make_stack_deck(5, gap='spacious', panel_padding='standard')
        _, over_issues = compile_deck(overflow_deck, COMPONENT)
        fails = [i for i in over_issues if i['severity'] == 'FAIL']
        self.assertTrue(fails)
        feedback = make_feedback(overflow_deck, None, over_issues)
        fail_errs = [e for e in feedback['slides'][0]['errors'] if e['severity'] == 'FAIL']
        self.assertTrue(fail_errs)
        err = fail_errs[0]
        self.assertIn('subtree_breakdown', err)
        self.assertEqual(len(err['subtree_breakdown']), 5)
        self.assertTrue(all('required_height_px' in item for item in err['subtree_breakdown']))

    def test_lossless_figure_crop_tool_and_native_highlight_overlays(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            composite = Image.new('RGB', (440, 320), 'white')
            draw = ImageDraw.Draw(composite)
            boxes = [(20, 20, 190, 140), (240, 20, 415, 140), (20, 175, 190, 295), (240, 175, 415, 295)]
            colors = [(30, 80, 140), (160, 55, 35), (35, 120, 90), (110, 60, 140)]
            for rect, color in zip(boxes, colors):
                draw.rectangle(rect, fill=color)
            src_fig = root / 'multi_panel.png'
            composite.save(src_fig)

            detected = auto_detect_panels(composite, min_panel_px=60)
            self.assertEqual(len(detected), 4)

            inspected = inspect_figure(src_fig, root / 'crops')
            self.assertTrue(Path(inspected['grid_preview_path']).is_file())
            self.assertEqual(len(inspected['candidate_panels']), 4)

            cropped = crop_figure(src_fig, detected[0], root / 'crops', source_figure='3a')
            self.assertTrue(cropped['verified_lossless'])
            self.assertEqual(verified_source(cropped['asset_entry']), str(src_fig.resolve()))

            # Verify runner.advance(figure_crop=...) does not mutate job state.
            job_dir = root / 'job'
            with patch.dict('os.environ', {'TOTALPIPE_AGENT_HOME': str(root / '.tp_home')}):
                state = runner.start('如何拆解多子图证据？', job_dir, source_kind='topic')
                job_fig = job_dir / 'work' / 'multi_panel.png'
                composite.save(job_fig)
                before_job_sha = sha(job_dir / '.totalpipe/job.json')
                resp = runner.advance(state['job_id'], figure_crop={'operation': 'crop', 'source': str(job_fig), 'box': detected[1]})
                self.assertEqual(resp['figure_crop_result']['status'], 'PASS')
                self.assertEqual(sha(job_dir / '.totalpipe/job.json'), before_job_sha)

            # Verify figure_refs[].highlights compiles without CRITICAL_COLLISION.
            slide = {
                'id': 'hl-slide',
                'semantic': {
                    'title': '论文子图支持归一化原生高亮框与圆角标签',
                    'purpose': 'Test figure highlights',
                    'takeaway': '高亮框与原图共享 overlap_group，不触发碰撞误报。',
                    'evidence_refs': ['EV1'],
                    'caveats': [],
                    'speaker_notes': 'Fig. 3a highlight test.',
                },
                'composition': {
                    'archetype': 'figure-parameters',
                    'blocks': [
                        {'id': 'b1', 'component': 'body', 'text': '框选区对应峰值响应平台。'},
                    ],
                    'figure_refs': [
                        {
                            'asset_id': 'fig3a',
                            'source_figure': '3a',
                            'caption': 'Fig. 3a 局部无损裁切子图与峰值框选。',
                            'min_panel_extent': 100,
                            'highlights': [
                                {'box': [0.15, 0.20, 0.50, 0.45], 'label': '① 峰值区', 'color': '#C2410C'},
                            ],
                        },
                    ],
                    'graphics': [],
                },
                'presentation': {},
            }
            deck = _base_deck([slide], {'fig3a': cropped['asset_entry']})
            self.assertEqual([i for i in validate(deck) if i['severity'] == 'FAIL'], [])
            layout, issues = compile_deck(deck, root)
            self.assertEqual([i for i in issues if i['severity'] == 'FAIL'], [])
            ids = {e['id'] for e in layout['slides'][0]['elements']}
            self.assertIn('figure-1:highlight:1', ids)
            self.assertIn('figure-1:highlight-badge:1', ids)
            self.assertIn('figure-1:highlight-label:1', ids)

    def test_monotonous_layout_audit_rhythm_summary_and_preview_checklist(self):
        monotonous = {
            'pages': [
                {'id': 'cover', 'content_refs': []},
                {'id': 'p1', 'content_refs': ['u1'], 'design': '双栏对比方案 A 与方案 B 的核心差异'},
                {'id': 'p2', 'content_refs': ['u2'], 'design': '两栏并列说明训练阶段与推理阶段开销'},
                {'id': 'p3', 'content_refs': ['u3'], 'design': '双栏对照展示线上与离线吞吐表现'},
            ],
        }
        audit = audit_design_quality(monotonous)
        codes = {w['code'] for w in audit['warnings']}
        self.assertIn('DECK_MONOTONOUS_LAYOUT', codes)

        varied = {
            'pages': [
                {'id': 'cover', 'content_refs': []},
                {'id': 'p1', 'content_refs': ['u1'], 'design': '漏斗流程图展示瓶颈收缩'},
                {'id': 'p2', 'content_refs': ['u2'], 'design': '原生对照表汇总三组消融指标'},
                {'id': 'p3', 'content_refs': ['u3'], 'design': '误差棒折线图比较收敛速度'},
            ],
        }
        self.assertNotIn('DECK_MONOTONOUS_LAYOUT', {w['code'] for w in audit_design_quality(varied)['warnings']})

        deck = _base_deck([{
            'id': 'rhythm-1',
            'semantic': {
                'title': 'Rhythm summary covers layout_tree slides',
                'purpose': 'Check visual_planner',
                'takeaway': 'Deck rhythm summary inspects all slides.',
                'evidence_refs': [],
                'caveats': [],
                'speaker_notes': 'Notes.',
            },
            'composition': {
                'archetype': 'composite-research',
                'blocks': [{'id': 'b1', 'component': 'body', 'text': '左侧流程配合右侧结论。'}],
                'figure_refs': [],
                'graphics': [],
                'layout_tree': {'version': '1.2', 'regions': {'body': {'id': 'l1', 'type': 'block', 'ref': 'b1'}}},
            },
            'presentation': {},
        }])
        prompt = make_prompt(deck, COMPONENT)
        self.assertIn('deck_rhythm_summary', prompt)
        self.assertEqual(prompt['deck_rhythm_summary']['slides'][0]['uses_layout_tree'], True)

        layout, issues = compile_deck(deck, COMPONENT)
        with tempfile.TemporaryDirectory() as tmp:
            png_path = Path(tmp) / 'slide.png'
            img = Image.new('RGB', (1280, 720), 'white')
            d = ImageDraw.Draw(img)
            d.rectangle((100, 260, 560, 420), fill=(30, 60, 90))
            d.rectangle((680, 260, 1140, 580), fill=(38, 110, 114))
            img.save(png_path)
            px_ws = analyze_rendered_png_whitespace(png_path)
            checklist = build_visual_checklist(layout['slides'][0], issues, {'whitespace': {'empty_quadrants': 0}}, px_ws)
            self.assertEqual(checklist['orphan_line_wraps']['status'], 'PASS')
            self.assertEqual(checklist['chart_annotation_clearance']['status'], 'PASS')
            self.assertEqual(checklist['footer_clearance']['status'], 'PASS')

    def test_topic_deck_ir_mode_and_new_library_examples(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'TOTALPIPE_AGENT_HOME': str(Path(tmp) / '.tp_home')}):
            out = Path(tmp) / 'topic_ir'
            state = runner.start('为什么局部归约能降低尾延迟？', out, source_kind='topic', page_mode='deck_ir', slide_count=1)
            self.assertEqual(state['stage'], 'page_design')
            self.assertTrue(state['next_action']['co_design']['enabled'])

            design_path = Path(state['next_action']['expected_output'])
            write(design_path, {
                'schema_version': 'topic-1.0',
                'deck_id': 'tail-latency',
                'pages': [{'id': 'P1', 'title': '局部归约消除全局等待', 'design': '左侧三步流程，右侧对照表总结延迟收益。'}],
            })
            state = runner.advance(state['job_id'], artifact_kind='page_design', artifact_path=str(design_path))
            self.assertEqual(state['stage'], 'deck_ir')
            self.assertIn('page_authoring', state['next_action'])
            designed_prompt = read(state['next_action']['input_path'])
            self.assertIn('topic_mode_rules', designed_prompt)

            ir_draft = out / 'work/pages/P1.json'
            write(ir_draft, _base_deck([{
                'id': 'P1',
                'semantic': {
                    'title': '局部归约将跨核同步限制在块边界',
                    'purpose': '解释尾延迟下降原因',
                    'takeaway': '减少逐样本锁竞争即可压低 P99 延迟。',
                    'evidence_refs': [],
                    'caveats': [],
                    'speaker_notes': '题目讲解备注。',
                },
                'composition': {
                    'archetype': 'composite-research',
                    'blocks': [{'id': 'b1', 'component': 'body', 'text': '块内独立累加，仅在窗口末尾同步一次摘要。'}],
                    'figure_refs': [],
                    'graphics': [],
                    'layout_tree': {'version': '1.2', 'regions': {'body': {'id': 'leaf', 'type': 'block', 'ref': 'b1'}}},
                },
                'presentation': {},
            }]))
            preflight = runner.advance(state['job_id'], artifact_kind='deck_ir_page', artifact_path=str(ir_draft), preflight=True)
            self.assertEqual(preflight['page_result']['status'], 'PASS', preflight)

        library = COMPONENT / 'examples/library'
        for example_id in (
            'problem-gap-approach',
            'system-architecture-ablation',
            'multi-panel-grid-readout',
            'conclusions-boundary-matrix',
        ):
            with self.subTest(example=example_id):
                deck = json.loads(subprocess.check_output(
                    [sys.executable, '-B', str(library / 'catalog.py'), 'show', example_id],
                    encoding='utf-8',
                ))
                self.assertEqual([i for i in validate(deck) if i['severity'] == 'FAIL'], [])
                _, issues = compile_deck(deck, library)
                self.assertEqual([i for i in issues if i['severity'] == 'FAIL'], [])


if __name__ == '__main__':
    unittest.main()
