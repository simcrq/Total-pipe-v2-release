"""Read a two-factor interaction from a merged-header control matrix."""
from common import block_leaf, deck, page, region


PEAKS = ((16, 11), (12, 5))
BASELINE, DETREND_ONLY = PEAKS[0]
WINDOW_ONLY, COMBINED = PEAKS[1]
ADDITIVE = WINDOW_ONLY + DETREND_ONLY - BASELINE
INTERACTION = COMBINED - ADDITIVE


def contrast_table():
    cells = [
        {'id': 'window', 'row': 0, 'column': 0, 'text': '加窗', 'row_span': 2},
        {'id': 'trend', 'row': 0, 'column': 1, 'text': '去趋势 · 伪峰幅度 (a.u.)',
         'column_span': 2, 'align': 'center'},
        {'id': 'keep', 'row': 1, 'column': 1, 'text': '否', 'align': 'center'},
        {'id': 'remove', 'row': 1, 'column': 2, 'text': '是', 'align': 'center'},
    ]
    for row, readings in enumerate(PEAKS, start=2):
        cells.append({'id': f'window-{row}', 'row': row, 'column': 0, 'text': ('否', '是')[row - 2]})
        cells.extend({'id': f'peak-{row}-{column}', 'row': row, 'column': column, 'text': str(peak),
                      'align': 'center'} for column, peak in enumerate(readings, start=1))
    return {'id': 'peaks', 'origin': 'generated', 'row_count': 4, 'column_count': 3, 'header_rows': 2,
            'column_weights': [1, 1, 1], 'cells': cells}


def control_design():
    nodes = [
        {'id': 'signal', 'title': '同一时序', 'shape': 'ellipse'},
        {'id': 'keep', 'title': '保留趋势', 'shape': 'rounded-rect'},
        {'id': 'remove', 'title': '去除趋势', 'shape': 'rounded-rect'},
        {'id': 'compare', 'title': '各算有窗与无窗', 'shape': 'rounded-rect'},
    ]
    edges = [{'from': start, 'to': end} for start, end in
             [('signal', 'keep'), ('signal', 'remove'), ('keep', 'compare'), ('remove', 'compare')]]
    return {'id': 'controlled-branches', 'type': 'dag', 'direction': 'horizontal',
            'nodes': nodes, 'edges': edges}


def make_deck():
    blocks = [
        {'id': 'matrix-guide', 'component': 'body', 'text': '读四组结果。',
         'text_flow': 'native_numbered_list', 'list_start': 1},
        {'id': 'formula-guide', 'component': 'body', 'text': '算联用值与相加预期之差。',
         'text_flow': 'native_numbered_list', 'list_start': 2,
         'text_for': {'kind': 'formula', 'ref': 'interaction', 'position': 'top'}},
        {'id': 'interaction', 'component': 'formula', 'text': rf'I={COMBINED}-{ADDITIVE}={INTERACTION}'},
        {'id': 'units', 'component': 'caption',
         'text': f'相加预期 = {WINDOW_ONLY} + {DETREND_ONLY} − {BASELINE} = {ADDITIVE} a.u.',
         'caption_for': {'kind': 'formula', 'ref': 'interaction', 'position': 'bottom'}},
        {'id': 'hold', 'component': 'body', 'text': '固定窗长、采样率和伪峰定义。',
         'text_flow': 'native_numbered_list', 'list_start': 3},
    ]
    provenance = {'kind': 'example', 'constructed': True, 'source': 'spectral_preprocessing_matrix.py 的 2×2 构造读数'}
    for block in blocks:
        block.update(basis='supplement', supplement=provenance)

    matrix_and_formula = region('matrix-and-interaction', 'columns', [
        region('control-table', 'stack', [
            block_leaf('matrix-guide'), {'id': 'control-matrix', 'type': 'table', 'ref': 'peaks'},
        ]),
        region('math-and-control', 'stack', [
            block_leaf('interaction'), block_leaf('hold'),
        ]),
    ], fit='hug', weights=[1.14, 1], gap='standard')
    body = region('factorial-control', 'stack', [
        matrix_and_formula,
        {'id': 'control-flow', 'type': 'graphic', 'ref': 'controlled-branches'},
    ], align='center')
    slide = page('spectral-interaction', '联合处理把伪峰压到低于相加预期',
                 f'构造示例 · 加窗和去趋势单独有效，联用结果比相加预期低 {abs(INTERACTION)} a.u.。',
                 blocks, body, tables=[contrast_table()], graphics=[control_design()], evidence_refs=())
    result = deck('spectral-preprocessing-matrix', [slide])
    result['theme'].update(font_family='Microsoft YaHei', font_file='msyh.ttc', bold_font_file='msyh.ttc')
    result['presentation']['text_capacity_policy'] = 'strict'
    return result
