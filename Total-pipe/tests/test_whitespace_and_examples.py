"""Regression tests for accurate 2D whitespace detection and example-library integration in page_design/page_scene."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

TOTAL_PIPE = Path(__file__).resolve().parents[1]
if str(TOTAL_PIPE) not in sys.path:
    sys.path.insert(0, str(TOTAL_PIPE))


class WhitespaceGeometryTests(unittest.TestCase):
    def test_union_area_never_double_counts_overlapping_boxes(self):
        from deck_compiler.whitespace import union_area

        # Two identical 200x200 boxes overlapping completely -> area is 40000, not 80000.
        self.assertAlmostEqual(union_area([[0, 0, 200, 200], [0, 0, 200, 200]]), 40000.0, places=3)
        # Half-overlapping 200x200 boxes -> 200*200 + 100*200 = 60000.
        self.assertAlmostEqual(union_area([[0, 0, 200, 200], [100, 0, 200, 200]]), 60000.0, places=3)

    def test_visible_element_boxes_excludes_containers_backgrounds_and_clamps_short_text(self):
        from deck_compiler.whitespace import analyze_region_whitespace, visible_element_boxes

        body = [56.0, 200.0, 1168.0, 464.0]
        elements = [
            {'id': 'bg', 'kind': 'image', 'role': 'background', 'bbox': [0, 0, 1280, 720]},
            {'id': 'panel:frame', 'kind': 'shape', 'role': 'decoration', 'bbox': [56, 200, 1168, 460],
             'collision_mode': 'container', 'frame_members': ['b1']},
            {'id': 'divider', 'kind': 'shape', 'role': 'decoration', 'bbox': [56, 300, 1168, 2]},
            {'id': 'b1', 'kind': 'text', 'role': 'body', 'text': '简短结论',
             'bbox': [56, 210, 1168, 400],
             'contract': {'font_size': 24, 'line_height': 1.25, 'vertical_anchor': 'top',
                          'inset': {'top': 4, 'bottom': 4, 'left': 4, 'right': 4}}},
        ]
        boxes = visible_element_boxes(elements, body, include_header=False)
        self.assertEqual(len(boxes), 1)
        # Short 4-char text must not be counted as 1168x400.
        self.assertLess(boxes[0][2], 250.0)
        self.assertLess(boxes[0][3], 60.0)

        metrics = analyze_region_whitespace(boxes, body, min_empty_size=(360.0, 160.0))
        self.assertLess(metrics['coverage_ratio'], 0.05)
        self.assertGreater(metrics['largest_empty_ratio'], 0.80)
        self.assertGreaterEqual(metrics['empty_quadrants'], 3)

    def test_analyze_balance_and_skeleton_do_not_overcount_containers_or_overlaps(self):
        from deck_compiler.quality_metrics import analyze_balance
        from deck_compiler.workshop.skeleton import capacity

        slide = {
            'id': 'S1',
            'elements': [
                {'id': 'bg', 'kind': 'image', 'role': 'background', 'bbox': [0, 0, 1280, 720]},
                {'id': 'title', 'kind': 'text', 'role': 'title', 'text': '页面标题',
                 'bbox': [56, 32, 1168, 56],
                 'contract': {'font_size': 36, 'line_height': 1.2, 'vertical_anchor': 'top',
                              'inset': {'top': 2, 'bottom': 2, 'left': 2, 'right': 2}}},
                {'id': 'takeaway', 'kind': 'text', 'role': 'takeaway', 'text': '一句话结论',
                 'bbox': [56, 108, 1168, 48],
                 'contract': {'font_size': 26, 'line_height': 1.2, 'vertical_anchor': 'top',
                              'inset': {'top': 2, 'bottom': 2, 'left': 2, 'right': 2}}},
                {'id': 'frame', 'kind': 'shape', 'role': 'decoration', 'bbox': [56, 200, 1168, 440],
                 'collision_mode': 'container', 'frame_members': ['b1']},
                {'id': 'b1', 'kind': 'text', 'role': 'body', 'text': '只有一句话',
                 'bbox': [72, 220, 1100, 380],
                 'contract': {'font_size': 24, 'line_height': 1.25, 'vertical_anchor': 'top',
                              'inset': {'top': 4, 'bottom': 4, 'left': 4, 'right': 4}}},
            ],
        }
        bal = analyze_balance({}, {'slide_size': [1280, 720], 'slides': [slide]}, {}, False)
        self.assertLess(bal.details['avg_body_coverage'], 10.0)
        self.assertTrue(any('sparse' in issue.message.lower() for issue in bal.issues))

        cap = capacity(slide, [])
        self.assertLess(cap['ink_ratio'], 0.10)
        self.assertGreater(cap['largest_empty_ratio'], 0.70)
        self.assertGreaterEqual(cap['empty_quadrants'], 3)

    def test_body_whitespace_issue_flags_sparse_non_cover_slide(self):
        from deck_compiler.layout import body_whitespace_issue

        sparse_elements = [
            {'id': 'b1', 'kind': 'text', 'role': 'body', 'text': '单条简短说明',
             'bbox': [56, 220, 1168, 400],
             'contract': {'font_size': 24, 'line_height': 1.25, 'vertical_anchor': 'top',
                          'inset': {'top': 4, 'bottom': 4, 'left': 4, 'right': 4}}},
        ]
        finding = body_whitespace_issue(sparse_elements, 2, 200, 664)
        self.assertIsNotNone(finding)
        self.assertEqual(finding['rule'], 'BODY_WHITESPACE_EXCESSIVE')
        self.assertEqual(finding['severity'], 'REVIEW')

        # A well-filled 2-zone slide must NOT trigger BODY_WHITESPACE_EXCESSIVE.
        rich_elements = [
            {'id': 'fig1', 'kind': 'image', 'role': 'evidence', 'bbox': [56, 210, 620, 420]},
            {'id': 'tbl1', 'kind': 'table', 'role': 'evidence', 'bbox': [700, 210, 520, 420]},
        ]
        self.assertIsNone(body_whitespace_issue(rich_elements, 2, 200, 664))

    def test_rendered_png_whitespace_distinguishes_sparse_vs_filled(self):
        from deck_compiler.whitespace import analyze_rendered_png_whitespace

        with tempfile.TemporaryDirectory() as tmp:
            sparse_png = Path(tmp) / 'sparse.png'
            filled_png = Path(tmp) / 'filled.png'

            img = Image.new('RGB', (1280, 720), '#FFFFFF')
            draw = ImageDraw.Draw(img)
            draw.rectangle([80, 230, 220, 260], fill='#142735')
            img.save(sparse_png)

            img2 = Image.new('RGB', (1280, 720), '#FFFFFF')
            draw2 = ImageDraw.Draw(img2)
            draw2.rectangle([80, 230, 620, 620], fill='#2B6CB0')
            draw2.rectangle([660, 230, 1180, 620], fill='#D97706')
            img2.save(filled_png)

            m_sparse = analyze_rendered_png_whitespace(sparse_png)
            m_filled = analyze_rendered_png_whitespace(filled_png)
            self.assertLess(m_sparse['pixel_ink_ratio'], 0.05)
            self.assertGreater(m_filled['pixel_ink_ratio'], 0.50)

    def test_page_scene_whitespace_detects_sparse_page_and_passes_multi_zone(self):
        from agent.page_scene_qa import check_file, page_whitespace_metrics

        sparse_page = {
            'id': 'P2',
            'title': '稀疏页测试',
            'take': '只放一条短文本在大框里。',
            'objects': [
                {'id': 'b1', 'type': 'text', 'role': 'body', 'box': [0.8, 2.3, 11.5, 4.2],
                 'text': '仅有一句简短说明', 'size': 18},
            ],
        }
        rich_page = {
            'id': 'P3',
            'title': '多区页测试',
            'take': '左侧表格与右侧公式并排占据主体空间。',
            'objects': [
                {'id': 't1', 'type': 'table', 'box': [0.72, 2.3, 5.8, 4.2],
                 'rows': [['方法', '精度', '延迟'], ['基线', '81%', '22 ms'], ['本方法', '93%', '11 ms']]},
                {'id': 'f1', 'type': 'formula', 'box': [6.8, 2.3, 5.7, 1.8], 'latex': 'E = m c^2'},
                {'id': 'c1', 'type': 'chart', 'box': [6.8, 4.3, 5.7, 2.2], 'chart_type': 'bar',
                 'categories': ['A', 'B'], 'series': [{'name': 'S1', 'values': [10, 20]}]},
            ],
        }
        m_sparse = page_whitespace_metrics(sparse_page, {}, page_index=2)
        m_rich = page_whitespace_metrics(rich_page, {}, page_index=3)
        self.assertTrue(m_sparse['sparse'], m_sparse)
        self.assertLess(m_sparse['body_coverage'], 0.10)
        self.assertGreater(m_sparse['largest_empty_ratio'], 0.70)
        self.assertFalse(m_rich['sparse'], m_rich)
        self.assertGreater(m_rich['body_coverage'], 0.60)

        spec = {
            'schema_version': '0.1',
            'deck_id': 'ws-test',
            'theme': {'font': 'Microsoft YaHei'},
            'pages': [
                {'id': 'P1', 'title': '封面', 'take': '主旨', 'objects': [
                    {'id': 'sub', 'type': 'text', 'role': 'body', 'box': [0.8, 2.6, 8.0, 0.8], 'text': '副标题', 'size': 20}
                ]},
                sparse_page,
                rich_page,
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'scene.json'
            p.write_text(json.dumps(spec, ensure_ascii=False), encoding='utf-8')
            report = check_file(p)
            self.assertEqual(report['status'], 'PASS', report['errors'])
            self.assertEqual(report['expression']['summary']['sparse_pages'], 1)
            self.assertFalse(report['metrics'][0]['sparse'])  # cover excluded
            self.assertTrue(report['metrics'][1]['sparse'])
            self.assertFalse(report['metrics'][2]['sparse'])


class ExampleLibraryIntegrationTests(unittest.TestCase):
    def test_chinese_unspaced_queries_match_relevant_examples(self):
        from deck_compiler.example_index import catalog_brief, inventory, search, suggest_for_text

        entries = inventory()
        self.assertGreaterEqual(len(catalog_brief(entries)), 15)

        # Unspaced Chinese queries that previously returned [] due to regex tokenization.
        cmp_hits = search('对比两种架构机制', entries, limit=3)
        self.assertTrue(cmp_hits)
        self.assertTrue(any(h['id'] in ('local-learning-comparison', 'comparison-lanes') for h in cmp_hits), cmp_hits)

        analogy_hits = search('用生活例子类比核心概念', entries, limit=3)
        self.assertTrue(analogy_hits)
        self.assertEqual(analogy_hits[0]['id'], 'definition-factor-analogy')

        eq_hits = search('公式推导和参数对比', entries, limit=3)
        self.assertTrue(eq_hits)
        self.assertTrue(any(h['id'] in ('equation-explainer', 'rc-discharge-composite') for h in eq_hits), eq_hits)

        # Existing exact query must still rank figure-readout #1.
        fig_hits = search('原图导读 图文并排', entries, limit=1)
        self.assertEqual([h['id'] for h in fig_hits], ['figure-readout'])

        # Fallback suggestions never return empty.
        self.assertEqual(len(suggest_for_text('xyz-generic-query', entries, limit=3)), 3)

    def test_topic_design_and_scene_prompts_carry_example_catalog_and_suggestions(self):
        from agent.topic import prepare_design, prepare_scene
        from agent.state import read, write

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / 'work'
            work.mkdir()
            req = {'source_kind': 'topic', 'source': '反向传播与局部学习机制对比', 'requirements': '包含公式和对比表'}
            prepare_design(work, req)
            design_prompt = read(work / 'page_design_prompt.json')
            lookup = design_prompt['example_lookup']
            self.assertGreaterEqual(len(lookup['catalog']), 15)
            self.assertGreaterEqual(len(lookup['recommended']), 3)
            self.assertIn('45%–75%', (work / 'page_design_task.md').read_text(encoding='utf-8'))

            write(work / 'page_design.json', {
                'schema_version': 'topic-1.0',
                'deck_id': 'cmp-demo',
                'pages': [
                    {'id': 'P1', 'title': '机制对比', 'design': '上下两条流程对照架构差异，下方给更新公式。'},
                ],
            })
            prepare_scene(work, req)
            scene_prompt = read(work / 'page_scene_prompt.json')
            self.assertIn('example_lookup', scene_prompt)
            self.assertGreaterEqual(len(scene_prompt['example_lookup']['catalog']), 15)
            p1_sugg = scene_prompt['example_lookup']['per_page_suggestions']['P1']
            self.assertGreaterEqual(len(p1_sugg), 2)
            self.assertIn('PAGE_SCENE_SPARSE_LAYOUT', (work / 'page_scene_task.md').read_text(encoding='utf-8'))

    def test_paper_page_scene_prompt_attaches_per_page_example_suggestions(self):
        from agent.page_scene_binding import prepare
        from agent.state import read, write

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / 'work'
            work.mkdir()
            write(work / 'page_design.json', {
                'schema_version': '1.0',
                'deck_id': 'paper-demo',
                'setting': {'audience': 'peers', 'occasion': 'group-meeting', 'reading': 'spoken'},
                'pages': [{
                    'id': 'P1',
                    'title': '原图导读与对比',
                    'take': '左图右读，突出关键变化。',
                    'claim': 'c',
                    'items': [{'id': 'i1', 'source': 'S1.answer', 'text': '关键结果', 'evidence': ['EV0001']}],
                    'design': '保留论文原图并做图文并排读图导览，下方给参数对照表。',
                }],
            })
            prepare(work, {'presentation_type': 'group_meeting'})
            scene_prompt = read(work / 'page_scene_prompt.json')
            self.assertIn('example_lookup', scene_prompt)
            self.assertGreaterEqual(len(scene_prompt['example_lookup']['catalog']), 15)
            self.assertIn('P1', scene_prompt['example_lookup']['per_page_suggestions'])
            self.assertTrue(scene_prompt['page_catalog'][0]['example_suggestions'])
            task_text = (work / 'page_scene_task.md').read_text(encoding='utf-8')
            self.assertIn('example_suggestions', task_text)
            self.assertIn('45%–75%', task_text)


if __name__ == '__main__':
    unittest.main()
