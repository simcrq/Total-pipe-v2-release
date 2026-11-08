"""PageScene P0 guardrails: explicit boxes, density and native render input."""
import json
import tempfile
import unittest
from pathlib import Path

from pptx import Presentation

from agent.page_scene_qa import check_file, render_spec, validate_spec


def spec(objects=None):
    return {
        'schema_version': '0.1',
        'deck_id': 'test',
        'theme': {'font': 'Microsoft YaHei'},
        'pages': [{
            'id': 'P1',
            'title': '一页测试',
            'take': '这一页只验证页面场景和渲染。',
            'objects': objects if objects is not None else [
                {'type': 'text', 'role': 'body', 'box': [0.8, 2.0, 5.0, 0.5], 'text': '测试正文', 'size': 18},
            ],
        }],
    }


class PageSceneTests(unittest.TestCase):
    def test_minimal_page_passes_and_renders_one_native_slide(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'scene.json'
            path.write_text(json.dumps(spec(), ensure_ascii=False), encoding='utf-8')
            result = check_file(path)
            self.assertEqual(result['status'], 'PASS', result)
            out = render_spec(spec(), path, Path(temp)/'out.pptx')
            self.assertTrue(out.is_file())
            self.assertEqual(len(Presentation(str(out)).slides), 1)

    def test_overlapping_body_boxes_fail(self):
        objects = [
            {'type': 'text', 'role': 'body', 'box': [1, 2, 3, 1], 'text': 'A', 'size': 18},
            {'type': 'text', 'role': 'body', 'box': [1.5, 2.5, 3, 1], 'text': 'B', 'size': 18},
        ]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'scene.json'
            path.write_text(json.dumps(spec(objects), ensure_ascii=False), encoding='utf-8')
            result = check_file(path)
            self.assertEqual(result['status'], 'FAIL')
            self.assertTrue(any('text collision' in e for e in result['errors']))

    def test_too_many_body_blocks_fail(self):
        objects = [
            {'type': 'text', 'role': 'body', 'box': [0.8, 2 + i*0.8, 5, 0.5], 'text': '块%d' % i, 'size': 18}
            for i in range(5)
        ]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'scene.json'
            path.write_text(json.dumps(spec(objects), ensure_ascii=False), encoding='utf-8')
            result = check_file(path)
            self.assertEqual(result['status'], 'FAIL')
            self.assertTrue(any('body text blocks' in e for e in result['errors']))

    def test_body_font_floor_and_missing_image(self):
        objects = [
            {'type': 'text', 'role': 'body', 'box': [0.8, 2.0, 5.0, 0.5], 'text': '小字', 'size': 12},
            {'type': 'image', 'box': [0.8, 3.0, 2.0, 2.0], 'path': 'missing.png'},
        ]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'scene.json'
            path.write_text(json.dumps(spec(objects), ensure_ascii=False), encoding='utf-8')
            result = check_file(path)
            errors = '\n'.join(result['errors'])
            self.assertIn('body text below', errors)
            self.assertIn('image not found', errors)

    def test_native_multilevel_list_and_group_render(self):
        objects = [
            {'type': 'list', 'role': 'body', 'box': [0.8, 2.0, 6.0, 2.0], 'size': 18, 'items': [
                {'text': '一级条目', 'level': 0, 'size': 18},
                {'text': '二级条目', 'level': 1, 'size': 18},
            ]},
            {'type': 'group', 'box': [7.2, 2.0, 4.5, 2.0], 'children': [
                {'type': 'text', 'role': 'body', 'box': [0, 0, 4.0, 0.5], 'text': '组内文本', 'size': 18},
            ]},
        ]
        with tempfile.TemporaryDirectory() as temp:
            spec_value = spec(objects)
            path = Path(temp)/'scene.json'
            path.write_text(json.dumps(spec_value, ensure_ascii=False), encoding='utf-8')
            result = check_file(path)
            self.assertEqual(result['status'], 'PASS', result)
            out = render_spec(spec_value, path, Path(temp)/'out.pptx')
            slide = Presentation(str(out)).slides[0]
            text = ' '.join(sh.text for sh in slide.shapes if hasattr(sh, 'text'))
            self.assertIn('一级条目', text)
            self.assertIn('二级条目', text)
            self.assertIn('组内文本', text)

    def test_native_formula_path_chart_and_notes_render(self):
        objects = [
            {'id': 'curve', 'type': 'path', 'box': [0.8, 3.0, 4.0, 2.0],
             'view_box': [0, 0, 100, 100],
             'commands': [['M', 0, 100], ['C', 25, 0, 75, 0, 100, 100]],
             'stroke': '#0B6E99', 'stroke_width': 2},
            {'id': 'formula', 'type': 'formula', 'box': [5.3, 2.0, 3.0, 0.8],
             'latex': r'V_{out}=G\cdot V_{in}', 'size': 22},
            {'id': 'chart', 'type': 'chart', 'box': [5.3, 3.0, 6.0, 3.0],
             'chart_type': 'line', 'categories': ['1', '2', '3'],
             'series': [{'name': 'Gain', 'values': [1, 2, 3]}],
             'x_label': 'V_in', 'y_label': 'V_out'},
        ]
        with tempfile.TemporaryDirectory() as temp:
            value = spec(objects)
            value['pages'][0]['notes'] = '讲稿留在备注里。'
            path = Path(temp)/'scene.json'
            path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
            result = check_file(path)
            self.assertEqual(result['status'], 'PASS', result)
            out = render_spec(value, path, Path(temp)/'out.pptx')
            prs = Presentation(str(out))
            self.assertEqual(len(prs.slides), 1)
            self.assertEqual(prs.slides[0].notes_slide.notes_text_frame.text, '讲稿留在备注里。')
            names = [shape.name for shape in prs.slides[0].shapes]
            self.assertTrue(any(name.startswith('Chart') for name in names))
            self.assertTrue(any(name.startswith('TextBox') for name in names))

    def test_title_and_take_refs_resolve_from_bindings(self):
        value = spec()
        value['bindings'] = {'P1.title': '一页测试', 'P1.take': '这一页只验证页面场景和渲染。'}
        value['pages'][0].pop('title')
        value['pages'][0].pop('take')
        value['pages'][0]['title_ref'] = 'P1.title'
        value['pages'][0]['take_ref'] = 'P1.take'
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'scene.json'
            path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
            result = check_file(path)
            self.assertEqual(result['status'], 'PASS', result)
            out = render_spec(value, path, Path(temp)/'out.pptx')
            slide = Presentation(str(out)).slides[0]
            text = ' '.join(shape.text for shape in slide.shapes if hasattr(shape, 'text'))
            self.assertIn('一页测试', text)

    def test_preview_rejects_unknown_page_without_rendering(self):
        from agent.page_scene_qa import preview_pages
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'scene.json'
            path.write_text(json.dumps(spec(), ensure_ascii=False), encoding='utf-8')
            result = preview_pages(path, ['P9'], Path(temp)/'preview')
            self.assertEqual(result['status'], 'FAIL')
            self.assertTrue(result['job_unchanged'])
            self.assertIn('unknown page ids', result['issues'][0])

    def test_copy_ref_binding_and_unresolved_ref(self):
        objects = [
            {'type': 'text', 'role': 'body', 'box': [0.8, 2.0, 5.0, 0.5], 'copy_ref': 'body', 'size': 18},
        ]
        with tempfile.TemporaryDirectory() as temp:
            spec_value = spec(objects)
            spec_value['bindings'] = {'body': '已批准正文'}
            path = Path(temp)/'scene.json'
            path.write_text(json.dumps(spec_value, ensure_ascii=False), encoding='utf-8')
            self.assertEqual(check_file(path)['status'], 'PASS')
            out = render_spec(spec_value, path, Path(temp)/'out.pptx')
            slide = Presentation(str(out)).slides[0]
            self.assertIn('已批准正文', ' '.join(sh.text for sh in slide.shapes if hasattr(sh, 'text')))

            spec_value['bindings'] = {}
            path.write_text(json.dumps(spec_value, ensure_ascii=False), encoding='utf-8')
            result = check_file(path)
            self.assertEqual(result['status'], 'FAIL')
            self.assertTrue(any('unresolved copy_ref' in e for e in result['errors']))


if __name__ == '__main__':
    unittest.main()
