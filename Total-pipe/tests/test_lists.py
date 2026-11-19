import unittest
from deck_compiler.lists import apply, candidates, merge_page


def block(bid, text, **extra):
    return {'id': bid, 'component': 'body', 'text': text, **extra}


def leaf(bid):
    return {'id': f'P1-{bid}', 'type': 'block', 'ref': bid}


def deck(blocks, children, presentation=None):
    return {'schema_version': '2.0', 'deck_id': 'list-fixture',
            'presentation': presentation or {},
            'slides': [{'id': 'P1', 'semantic': {}, 'presentation': {},
                        'composition': {'archetype': 'composite-research',
                                        'blocks': blocks, 'figure_refs': [],
                                        'layout_tree': {'version': '1.2', 'regions': {
                                            'body': {'id': 'P1-body', 'type': 'columns',
                                                     'gap': 'standard', 'weights': [1] * len(children),
                                                     'children': children}}}}}]}


class ListTests(unittest.TestCase):
    def test_two_blocks_become_one_native_list(self):
        ir = deck([block('P1-b1', '第一句'), block('P1-b2', '第二句')],
                  [{'id': 'P1-c0', 'type': 'stack', 'children': [leaf('P1-b1')]},
                   {'id': 'P1-c1', 'type': 'stack', 'children': [leaf('P1-b2')]}])
        self.assertEqual(candidates(ir), ['P1'])
        out = apply(ir, ['P1'])
        merged = out['slides'][0]['composition']['blocks']
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['text'], '第一句\n第二句')
        self.assertEqual(merged[0]['text_flow'], 'distributed_arrow_list')
        self.assertEqual(out['presentation']['bullet_style'], 'arrow')
        self.assertGreater(out['presentation']['list_gap'], 0)

    def test_one_block_is_not_a_list(self):
        ir = deck([block('P1-b1', '只有一句')],
                  [{'id': 'P1-c0', 'type': 'stack', 'children': [leaf('P1-b1')]}])
        self.assertEqual(candidates(ir), [])
        out = apply(ir, ['P1'])
        self.assertEqual([b['id'] for b in out['slides'][0]['composition']['blocks']], ['P1-b1'])

    def test_reviewed_body_blocks_stay_independent(self):
        ir = deck([block('one', 'First finding'), block('two', 'Second finding')],
                  [leaf('one'), leaf('two')])
        ir['slides'][0]['semantic']['content_projection'] = {'version': '2.0'}
        self.assertEqual(candidates(ir), [])
        self.assertEqual(apply(ir, ['P1']), ir)

    def test_inline_math_page_is_left_alone(self):
        ir = deck([block('P1-b1', '第一句'), block('P1-b2', '电压 $V_{ds}$ 固定', inline_math=True)],
                  [{'id': 'P1-c0', 'type': 'stack', 'children': [leaf('P1-b1')]},
                   {'id': 'P1-c1', 'type': 'stack', 'children': [leaf('P1-b2')]}])
        self.assertEqual(candidates(ir), [])

    def test_panels_stay_referenced_once(self):
        ir = deck([block('P1-b1', '甲'), block('P1-b2', '乙')],
                  [{'id': 'P1-f0', 'type': 'figure', 'ref': 0},
                   {'id': 'P1-c1', 'type': 'stack', 'children': [leaf('P1-b1'), leaf('P1-b2')]}])
        out = apply(ir, ['P1'])
        frame = out['slides'][0]['composition']['layout_tree']['regions']['body']
        kinds = [node['type'] for node in _walk(frame) if node['type'] in ('figure', 'block')]
        self.assertEqual(kinds.count('figure'), 1)
        self.assertEqual(kinds.count('block'), 1)


def _walk(node):
    yield node
    for child in node.get('children', []):
        yield from _walk(child)


if __name__ == '__main__':
    unittest.main()
