"""Compare two editable measurement routes with a matched-blank correction."""
from common import block_leaf, deck, page, region
from comparison_lanes import arrow, rounded_box


def comparison_routes():
    total_mv, blank_mv = 14, 4
    lanes = [
        ('direct', 'A · 直接读样品', ('同一份样品', f'读数 {total_mv} mV', f'报告 {total_mv} mV'), ('测量', '直接报告')),
        ('blank', 'B · 同批扣空白', ('样品与空白', f'{total_mv} mV 与 {blank_mv} mV', f'净信号 {total_mv-blank_mv} mV'),
         ('同批测量', '样品减空白')),
    ]
    paths = [{'id': 'divider', 'stroke': '#BCCBD1', 'd': 'M 0 130 L 1120 130'}]
    labels = []
    for (name, title, states, actions), y in zip(lanes, (0, 140)):
        labels.append({'id': name, 'text': title, 'box': [4, y+2, 300, 35]})
        for index, (x, state) in enumerate(zip((4, 436, 868), states), 1):
            key = f'{name}-state-{index}'
            paths.append(rounded_box(key, x, y+47, 246, 62))
            labels.append({'id': key, 'text': state, 'box': [x+8, y+51, 230, 54]})
        for index, (x, action) in enumerate(zip((260, 692), actions), 1):
            key = f'{name}-action-{index}'
            paths.append(arrow(key, x, x+166, y+80))
            labels.append({'id': key, 'text': action, 'box': [x+2, y+36, 162, 39]})
    return {'id': 'comparison', 'type': 'path', 'view_box': [0, 0, 1120, 252],
            'paths': paths, 'labels': labels}


def make_deck():
    blocks = [
        {'id': 'subtraction', 'component': 'formula',
         'text': r'S_{\mathrm{net}}=S_{\mathrm{sample}}-S_{\mathrm{blank}}'},
        {'id': 'conditions', 'component': 'body',
         'text': '前提是样品和空白共享同一个加性偏移。',
         'text_flow': 'native_bullet_list', 'bullet_icon': '→'},
    ]
    for block in blocks:
        block.update(basis='supplement', supplement={'kind': 'example', 'constructed': True,
                                                     'source': 'matched_blank_workflow.py'})
    body = region('flow-plus-calculation', 'stack', [
        {'id': 'routes', 'type': 'graphic', 'ref': 'comparison'},
        region('equation-with-condition', 'columns', [block_leaf('subtraction'), block_leaf('conditions')],
               weights=[1, 1], gap='standard', fit='hug'),
    ], gap='standard', align='center')
    slide = page('matched-blank', '同批扣空白可以消掉共同偏移',
                 '构造示例 · 用同一份样品，比较直接报告与同批空白扣除。',
                 blocks, body, graphics=[comparison_routes()], evidence_refs=())
    output = deck('matched-blank-workflow', [slide])
    output['presentation']['text_capacity_policy'] = 'strict'
    return output
