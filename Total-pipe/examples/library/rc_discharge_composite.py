"""Explain one controlled comparison with an editable chart, circuit, equation and table."""
from math import exp

from common import block_leaf, deck, page, region


RESISTANCES_KOHM = (10, 20)
CAPACITANCE_UF = 1
INITIAL_VOLTAGE = 1
TIME_CONSTANTS_MS = tuple(r * CAPACITANCE_UF for r in RESISTANCES_KOHM)
TIMES_MS = sorted({0, 5, 15, 30, 40, *TIME_CONSTANTS_MS})
VOLTAGE_AFTER_ONE_TAU = INITIAL_VOLTAGE * exp(-1)


def discharge_chart():
    return {
        'id': 'discharge', 'kind': 'line', 'basis': 'explain', 'illustrative': True,
        'x': {'label': '放电时间 (ms)', 'values': list(TIMES_MS)},
        'y': {'label': '电容电压', 'unit': 'V'},
        'series': [
            {'label': f'{resistance} kΩ', 'evidence_refs': [],
             'values': [INITIAL_VOLTAGE * exp(-time / tau) for time in TIMES_MS]}
            for resistance, tau in zip(RESISTANCES_KOHM, TIME_CONSTANTS_MS)
        ],
        'annotations': [
            {'text': f'τ = {tau} ms', 'series': series, 'point': TIMES_MS.index(tau),
             'dx': dx, 'dy': dy}
            for series, (tau, (dx, dy)) in enumerate(zip(TIME_CONSTANTS_MS, [(-104, 13), (42, -42)]))
        ],
        'source': '理想 RC 模型计算',
    }


def circuit():
    # All coordinates are local to the diagram. The layout tree places the
    # circuit on the slide. R is a zigzag and C has two equal plates.
    return {
        'id': 'circuit', 'type': 'path', 'view_box': [0, 0, 390, 104],
        'paths': [
            {'id': 'wire-top', 'd': 'M 139 43 L 34 43 L 34 94 L 332 94 L 332 76',
             'stroke': 'foreground'},
            {'id': 'wire-right', 'd': 'M 247 43 L 332 43 L 332 63', 'stroke': 'foreground'},
            {'id': 'resistor', 'd': 'M 139 43 L 151 35 L 169 51 L 187 35 L 205 51 L 223 35 L 235 51 L 247 43',
             'stroke': 'accent', 'line_width': 3},
            {'id': 'plate-top', 'd': 'M 310 63 L 354 63', 'stroke': 'accent', 'line_width': 3},
            {'id': 'plate-bottom', 'd': 'M 310 76 L 354 76', 'stroke': 'accent', 'line_width': 3},
        ],
        'labels': [
            {'id': 'resistance', 'text': 'R', 'box': [169, 0, 48, 40]},
            {'id': 'capacitance', 'text': 'C', 'box': [356, 47, 34, 42]},
        ],
    }


def parameter_table():
    rows = [('R (kΩ)', 'C (μF)', 'τ (ms)')]
    rows.extend((str(r), str(CAPACITANCE_UF), str(tau))
                for r, tau in zip(RESISTANCES_KOHM, TIME_CONSTANTS_MS))
    return {
        'id': 'parameters', 'origin': 'generated', 'row_count': len(rows),
        'column_count': len(rows[0]), 'header_rows': 1,
        'cells': [
            {'id': f'cell-{row}-{column}', 'row': row, 'column': column,
             'text': text, 'align': 'center'}
            for row, cells in enumerate(rows) for column, text in enumerate(cells)
        ],
    }


def titled_group(id, title, body):
    return {
        'id': id, 'type': 'panel', 'title': title, 'padding': 'compact', 'gap': 'compact',
        'frame': {'title_band': 'chip', 'title_fill': '#266E72', 'title_color': '#FFFFFF'},
        'body': body,
    }


def make_deck():
    blocks = [
        {'id': 'compare', 'component': 'body',
         'text': f'放电开始后，{max(RESISTANCES_KOHM)} kΩ 组在同一时刻的电压更高。',
         'text_flow': 'native_numbered_list', 'list_start': 1},
        {'id': 'threshold', 'component': 'body',
         'text': f'经过各自的时间常数，两组都降到约 {VOLTAGE_AFTER_ONE_TAU:.2f} V。',
         'text_flow': 'native_numbered_list', 'list_start': 2},
        {'id': 'circuit-caption', 'component': 'caption', 'text': '图 1 · 理想放电回路',
         'caption_for': {'kind': 'graphic', 'ref': 'circuit', 'position': 'bottom'}},
        {'id': 'model', 'component': 'formula', 'text': r'V(t)=V_0e^{-t/(RC)}'},
    ]
    provenance = {'kind': 'example', 'constructed': True, 'source': 'rc_discharge_composite.py'}
    for block in blocks:
        block.update(basis='supplement', supplement=provenance)
    left = titled_group('results', '读曲线', region('curve-and-readout', 'stack', [
        {'id': 'discharge-chart', 'type': 'chart', 'ref': 'discharge'},
        block_leaf('compare'),
        block_leaf('threshold'),
    ]))
    right = titled_group('conditions', '模型与参数', region('circuit-and-parameters', 'stack', [
        {'id': 'circuit-diagram', 'type': 'graphic', 'ref': 'circuit'},
        block_leaf('model'),
        {'id': 'parameter-table', 'type': 'table', 'ref': 'parameters'},
    ]))
    body = region('compare-and-explain', 'columns', [left, right], weights=[1.48, 1])
    slide = page('discharge-comparison', '电阻加倍，放电时间常数也加倍',
                 rf'构造示例 · 理想 RC 放电，两组初始电压均为 {INITIAL_VOLTAGE} V，时间常数为 $\tau=RC$。',
                 blocks, body, graphics=[circuit()], tables=[parameter_table()],
                 charts=[discharge_chart()], evidence_refs=())
    slide['semantic']['inline_math'] = ['takeaway']
    example = deck('rc-discharge-composite', [slide])
    example['presentation']['text_capacity_policy'] = 'strict'
    return example
