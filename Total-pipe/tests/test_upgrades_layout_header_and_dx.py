"""Unit tests for header/section_nav/footer upgrades, compact minimums, CJK stack/chart layout, and DX diagnostics."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from deck_compiler.chart_render import MIN_SIZE, compile_chart
from deck_compiler.fonts import resolve_theme_fonts
from deck_compiler.graphic_layout import compile_graphic
from deck_compiler.ir import validate as validate_ir
from deck_compiler.layout import compile_deck
from deck_compiler.officecli import _resolve_executable
from deck_compiler.visual_design import header_layout, resolve_design, validate_design


def _base_deck(slide, presentation=None):
    pres = {
        'academic_design': {
            'style': 'research-seminar',
            'title_treatment': 'thin-rule',
            'density': 'balanced',
            'figure_treatment': 'unframed',
            'decoration_policy': 'minimal',
            'header_variant': 'compact',
        },
        'text_capacity_policy': 'preserve-terms',
    }
    if presentation:
        for k, v in presentation.items():
            if k == 'academic_design' and isinstance(v, dict):
                pres['academic_design'] = {**pres['academic_design'], **v}
            else:
                pres[k] = v
    return {
        'schema_version': '2.0',
        'deck_id': 'upgrade-test',
        'theme': {
            'font_family': 'Arial',
            'font_file': 'arial.ttf',
            'bold_font_file': 'arialbd.ttf',
            'accent': '#266E72',
            'foreground': '#142735',
            'background': '#FFFFFF',
        },
        'presentation': pres,
        'assets': {},
        'slides': [slide],
    }


def _simple_slide(blocks, body, *, graphics=(), charts=(), presentation=None):
    comp = {
        'archetype': 'composite-research',
        'blocks': blocks,
        'figure_refs': [],
        'graphics': list(graphics),
        'layout_tree': {'version': '1.2', 'regions': {'body': body}},
    }
    if charts:
        comp['charts'] = list(charts)
    return {
        'id': 's1',
        'semantic': {
            'title': '案例一：公开基准驱动转向过拟合刷榜',
            'takeaway': '测试用副标题结论。',
            'purpose': 'Unit test slide',
            'evidence_refs': ['fixture:test'],
            'caveats': [],
            'speaker_notes': 'Notes.',
        },
        'composition': comp,
        'presentation': presentation or {},
    }


class UpgradeTests(unittest.TestCase):
    def test_section_nav_accent_bar_hide_takeaway_and_no_footer(self):
        self.assertEqual(
            validate_design({
                'style': 'research-seminar',
                'title_treatment': 'accent-bar',
                'density': 'balanced',
                'figure_treatment': 'unframed',
                'decoration_policy': 'minimal',
            }),
            [],
        )
        # decoration_policy=none must reject accent-bar
        errs = validate_design({
            'style': 'research-seminar',
            'title_treatment': 'accent-bar',
            'density': 'balanced',
            'figure_treatment': 'unframed',
            'decoration_policy': 'none',
        })
        self.assertTrue(errs)

        blocks = [{'id': 'b1', 'component': 'body', 'text': '简洁正文内容测试。', 'evidence_refs': ['fixture:test']}]
        body = {'id': 'root', 'type': 'stack', 'gap': 'compact', 'children': [{'id': 'leaf-b1', 'type': 'block', 'ref': 'b1'}]}
        slide = _simple_slide(blocks, body, presentation={'section': '案例剖析'})
        deck = _base_deck(slide, presentation={
            'academic_design': {'title_treatment': 'accent-bar', 'accent_color': '#B85D3B'},
            'section_nav': {'items': ['现象观察', '本质机理', '演进路径', '案例剖析', '治理应对']},
            'hide_takeaway': True,
            'page_numbers': False,
        })
        self.assertEqual([i for i in validate_ir(deck) if i['severity'] == 'FAIL'], [])
        layout, issues = compile_deck(deck, ROOT / 'examples')
        fails = [i for i in issues if i['severity'] == 'FAIL']
        self.assertEqual(fails, [], fails)
        elements = {e['id']: e for e in layout['slides'][0]['elements']}
        self.assertIn('header:nav-cell:3', elements)
        self.assertEqual(elements['header:nav-cell:3']['fill'], '#B85D3B')
        self.assertIn('header:nav-label:3', elements['header:nav-cell:3']['frame_members'])
        self.assertIn('visual:title-bar', elements)
        self.assertNotIn('takeaway', elements)
        self.assertNotIn('page:rule', elements)
        self.assertNotIn('page:number', elements)

    def test_compact_chart_and_cjk_reference_line_label(self):
        self.assertEqual(MIN_SIZE, (380.0, 220.0))
        reg, bold, _ = resolve_theme_fonts(
            {'font_family': 'Arial', 'font_file': 'arial.ttf', 'bold_font_file': 'arialbd.ttf'},
            ROOT / 'examples',
            '准确率 迭代轮次 泛化基线 80% 构造示例',
        )
        chart = {
            'id': 'c1',
            'kind': 'line',
            'basis': 'explain',
            'illustrative': True,
            'x': {'label': '迭代轮次', 'scale': 'linear', 'values': [1, 2, 3, 4]},
            'y': {'label': '准确率', 'scale': 'linear', 'unit': '%', 'min': 55, 'max': 100},
            'series': [{'label': '验证集', 'values': [68, 75, 81, 86]}],
            'reference_lines': [{'axis': 'y', 'value': 80, 'label': '泛化基线 80%', 'style': 'dashed'}],
            'source': '构造示例',
        }
        elements = compile_chart(chart, [0, 0, 400, 224], {'accent': '#266E72'}, {'font_file': reg, 'bold_font_file': bold})
        ref_lbl = next(e for e in elements if e['id'] == 'chart:c1:ref-label:0')
        self.assertGreaterEqual(ref_lbl['bbox'][3], 28.0)

    def test_compact_label_only_process_and_narrow_arrow_path(self):
        reg, bold, _ = resolve_theme_fonts(
            {'font_family': 'Arial', 'font_file': 'arial.ttf', 'bold_font_file': 'arialbd.ttf'},
            ROOT / 'examples',
            '步骤一二三四五',
        )
        proc = {
            'id': 'p1',
            'type': 'process',
            'direction': 'horizontal',
            'layout': 'compact',
            'nodes': [{'id': f'n{i}', 'title': f'步骤{i}'} for i in range(1, 6)],
            'edges': [{'from': f'n{i}', 'to': f'n{i+1}', 'kind': 'arrow'} for i in range(1, 5)],
        }
        # 80px height is enough for label-only compact process (64px square nodes + 16px pad)
        elems = compile_graphic(proc, [0, 0, 1000, 80], {'accent': '#266E72'}, {'font_file': reg, 'bold_font_file': bold})
        shapes = [e for e in elems if e['kind'] == 'shape']
        self.assertEqual(len(shapes), 5)
        self.assertAlmostEqual(shapes[0]['bbox'][2], shapes[0]['bbox'][3])

        # Narrow label-free path arrow (70px wide) compiles inside columns
        arrow = {
            'id': 'arr',
            'type': 'path',
            'view_box': [0, 0, 80, 200],
            'paths': [{'id': 'p', 'commands': [['M', 10, 90], ['L', 50, 90], ['L', 70, 100], ['L', 50, 110], ['L', 10, 110], ['Z']], 'stroke': '#B85D3B', 'fill': '#F6E5DD'}],
        }
        blocks = [
            {'id': 'l', 'component': 'body', 'text': '左侧说明。', 'evidence_refs': ['fixture:test']},
            {'id': 'r', 'component': 'body', 'text': '右侧说明。', 'evidence_refs': ['fixture:test']},
        ]
        body = {
            'id': 'cols', 'type': 'columns', 'weights': [1.0, 0.14, 1.0], 'gap': 'compact',
            'children': [
                {'id': 'lb', 'type': 'block', 'ref': 'l'},
                {'id': 'ag', 'type': 'graphic', 'ref': 'arr'},
                {'id': 'rb', 'type': 'block', 'ref': 'r'},
            ],
        }
        deck = _base_deck(_simple_slide(blocks, body, graphics=[arrow]))
        _, issues = compile_deck(deck, ROOT / 'examples')
        self.assertEqual([i for i in issues if i['severity'] == 'FAIL'], [])

    def test_stack_prioritizes_cjk_bold_block_over_chart_stretch(self):
        chart = {
            'id': 'c1',
            'kind': 'line',
            'basis': 'explain',
            'illustrative': True,
            'x': {'label': '轮次', 'scale': 'linear', 'values': [1, 2, 3, 4]},
            'y': {'label': '分数', 'scale': 'linear', 'unit': '%', 'min': 50, 'max': 100},
            'series': [{'label': '验证集', 'values': [65, 74, 81, 87]}],
            'source': '构造示例',
        }
        blocks = [
            {'id': 'b1', 'component': 'body', 'text': '公开基准提供**统一量尺**与**可复现基线**，推动跨域方法持续收敛并便于误差诊断。', 'evidence_refs': ['fixture:test']},
        ]
        body = {
            'id': 'panel1', 'type': 'panel', 'title': '对照卡片', 'padding': 'compact', 'gap': 'compact',
            'frame': {'border': {'color': '#CBD5E1', 'width': 1.2}, 'fill': '#F8FAFC',
                      'title_band': 'chip', 'title_align': 'center', 'title_fill': '#266E72', 'title_color': '#FFFFFF'},
            'body': {
                'id': 'st', 'type': 'stack', 'gap': 'compact',
                'children': [
                    {'id': 'lb1', 'type': 'block', 'ref': 'b1'},
                    {'id': 'lc1', 'type': 'chart', 'ref': 'c1'},
                ],
            },
        }
        deck = _base_deck(_simple_slide(blocks, body, charts=[chart]), presentation={'hide_takeaway': True, 'page_numbers': False})
        _, issues = compile_deck(deck, ROOT / 'examples')
        self.assertEqual([i for i in issues if i['severity'] == 'FAIL'], [])
        self.assertEqual([i for i in issues if i['rule'] in ('SCIENTIFIC_TEXT_OVERFLOW', 'CRITICAL_COLLISION')], [])

    def test_clean_cjk_fallback_is_info_not_review(self):
        _, _, notes = resolve_theme_fonts(
            {'font_family': 'Arial', 'font_file': 'arial.ttf', 'bold_font_file': 'arialbd.ttf'},
            ROOT / 'examples',
            '公开基准驱动演进测试案例',
        )
        font_subs = [n for n in notes if n['rule'] == 'FONT_SUBSTITUTED']
        if font_subs:
            self.assertEqual(font_subs[0]['severity'], 'INFO')

    def test_missing_officecli_gives_actionable_error(self):
        with self.assertRaises(FileNotFoundError) as ctx:
            _resolve_executable('nonexistent-officecli-binary-xyz')
        msg = str(ctx.exception)
        self.assertIn('nonexistent-officecli-binary-xyz', msg)
        self.assertIn('OfficeCLI 1.0.152+', msg)


if __name__ == '__main__':
    unittest.main()
