"""Trace a steady temperature drop across two layers in series."""
from common import block_leaf, comparison_table, deck, page, region


RESISTANCES_K_PER_W = (1, 3)
HOT_C, COLD_C = 40, 20
HEAT_FLOW_W = (HOT_C - COLD_C) / sum(RESISTANCES_K_PER_W)
DROPS_K = tuple(HEAT_FLOW_W * resistance for resistance in RESISTANCES_K_PER_W)
INTERFACE_C = HOT_C - DROPS_K[0]


def cross_section():
    return {
        'id': 'layers', 'type': 'path', 'view_box': [0, 0, 800, 194],
        'paths': [
            {'id': 'layer-a', 'd': 'M 106 59 L 400 59 L 400 139 L 106 139 Z',
             'fill': '#FFF1D8', 'stroke': '#A65A1A'},
            {'id': 'layer-b', 'd': 'M 400 59 L 694 59 L 694 139 L 400 139 Z',
             'fill': '#DCEDEA', 'stroke': 'accent'},
            {'id': 'heat-direction', 'd': 'M 135 165 L 669 165 M 659 157 L 670 165 L 659 173',
             'stroke': 'foreground', 'line_width': 3},
        ],
        'labels': [
            {'id': 'hot', 'text': f'{HOT_C} °C', 'box': [42, 0, 128, 54]},
            {'id': 'junction', 'text': f'{INTERFACE_C:g} °C', 'box': [336, 0, 128, 54]},
            {'id': 'cold', 'text': f'{COLD_C} °C', 'box': [630, 0, 128, 54]},
            {'id': 'a', 'text': f'A 层：降 {DROPS_K[0]:g} K', 'box': [124, 70, 258, 58]},
            {'id': 'b', 'text': f'B 层：降 {DROPS_K[1]:g} K', 'box': [418, 70, 258, 58]},
        ],
    }


def make_deck():
    blocks = [
        {'id': 'steady-condition', 'component': 'body',
         'text': '先沿箭头读温度。假定稳态一维传热，忽略接触热阻。',
         'text_flow': 'native_numbered_list', 'list_start': 1,
         'text_for': {'kind': 'graphic', 'ref': 'layers', 'position': 'top'}},
        {'id': 'hot-label', 'component': 'caption', 'text': '热端',
         'caption_for': {'kind': 'graphic', 'ref': 'layers', 'position': 'left'}},
        {'id': 'cold-label', 'component': 'caption', 'text': '冷端',
         'caption_for': {'kind': 'graphic', 'ref': 'layers', 'position': 'right'}},
        {'id': 'graphic-note', 'component': 'caption', 'text': '示意 · 箭头为热流方向，图中宽度未按比例绘制。',
         'caption_for': {'kind': 'graphic', 'ref': 'layers', 'position': 'bottom'}},
        {'id': 'drop', 'component': 'formula', 'text': r'\Delta T_i=P R_i'},
        {'id': 'flow', 'component': 'body',
         'text': f'再算各层温降。热流率 P 均为 {HEAT_FLOW_W:g} W。',
         'text_flow': 'native_numbered_list', 'list_start': 2},
    ]
    provenance = {'kind': 'example', 'constructed': True, 'source': 'thermal_resistance_section.py 的串联热阻模型'}
    for block in blocks:
        block.update(basis='supplement', supplement=provenance)

    rows = [('材料', '热阻 (K/W)', '温降 (K)')]
    rows.extend((label, f'{resistance:g}', f'{drop:g}')
                for label, resistance, drop in zip(('A 层', 'B 层'), RESISTANCES_K_PER_W, DROPS_K))
    table = comparison_table('thermal-parameters', rows, [1, 1.3, 1.1])
    relations = region('fit-model', 'columns', [
        region('equation-and-note', 'stack', [block_leaf('flow'), block_leaf('drop')], align='center'),
        {'id': 'resistance-table', 'type': 'table', 'ref': 'thermal-parameters'},
    ], gap='standard', fit='hug', weights=[1, 1.22])
    body = region('profile-and-accounting', 'stack', [
        {'id': 'temperature-section', 'type': 'graphic', 'ref': 'layers'}, relations,
    ], align='center')
    slide = page('heat-drop', '串联传热时，热阻较大的层承担更多温降',
                 f'构造示例 · 两端温差为 {HOT_C-COLD_C} K，B 层承担 {DROPS_K[1]:g} K。',
                 blocks, body, graphics=[cross_section()], tables=[table], evidence_refs=())
    result = deck('thermal-resistance-section', [slide])
    result['theme'].update(font_family='Microsoft YaHei', font_file='msyh.ttc', bold_font_file='msyh.ttc')
    result['presentation']['text_capacity_policy'] = 'strict'
    return result
