"""Read an observed convergence rate from a log-log plot and a paired check."""
from math import pi, sin

from common import block_leaf, chip_panel, comparison_table, deck, page, region


SEGMENTS = (4, 8, 16, 32, 64)
COARSE, FINE = 16, 32


def integration_errors(n):
    step = pi / (2 * n)
    left = step * sum(sin(index * step) for index in range(n))
    # Changing the two endpoint weights adds h/2 since sin(π/2) - sin(0) = 1.
    trapezoid = left + step / 2
    return abs(1 - left), abs(1 - trapezoid)


def convergence_chart(errors):
    return {
        'id': 'convergence', 'kind': 'line', 'basis': 'explain', 'illustrative': True,
        'x': {'label': '分段数 N', 'scale': 'log', 'values': list(SEGMENTS)},
        'y': {'label': '绝对误差', 'scale': 'log'},
        'series': [
            {'label': name, 'values': [errors[n][column] for n in SEGMENTS], 'evidence_refs': []}
            for column, name in enumerate(('左矩形法', '复合梯形法'))
        ],
        'annotations': [
            {'text': f'N = {n}', 'series': 1, 'point': SEGMENTS.index(n), 'dx': dx, 'dy': -46}
            for n, dx in ((COARSE, -83), (FINE, 20))
        ],
        'source': '积分算例计算值',
    }


def make_deck():
    errors = {n: integration_errors(n) for n in SEGMENTS}
    ratio = errors[FINE][1] / errors[COARSE][1]
    table = comparison_table('error-pair', [
        ('N', '梯形法误差 E'),
        (str(COARSE), f'{errors[COARSE][1]:.6f}'),
        (str(FINE), f'{errors[FINE][1]:.6f}'),
    ], [1, 2])
    blocks = [
        {'id': 'read-line', 'component': 'body', 'text': '双对数图上，梯形法的误差下降更快。',
         'text_flow': 'native_numbered_list', 'list_start': 1},
        {'id': 'halve-step', 'component': 'body', 'text': f'N 从 {COARSE} 到 {FINE}，步长减半。',
         'text_flow': 'native_numbered_list', 'list_start': 2},
        {'id': 'ratio', 'component': 'formula',
         'text': rf'\frac{{E_{{{FINE}}}}}{{E_{{{COARSE}}}}}\approx {ratio:.2f}'},
        {'id': 'observed-order', 'component': 'body',
         'text': '比值与二阶预期一致。',
         'text_flow': 'native_numbered_list', 'list_start': 3},
    ]
    source = {'kind': 'example', 'constructed': True, 'source': '脚本内对正弦函数的数值积分'}
    for block in blocks:
        block.update(basis='supplement', supplement=source)

    readout = region('pairing-errors', 'stack', [
        block_leaf('halve-step'), {'id': 'trapezoid-pair', 'type': 'table', 'ref': 'error-pair'},
        block_leaf('ratio'), block_leaf('observed-order'),
    ], align='center')
    body = region('rate-and-check', 'columns', [
        region('plot-and-guide', 'stack', [
            block_leaf('read-line'), {'id': 'convergence-plot', 'type': 'chart', 'ref': 'convergence'},
        ], weights=[1, 9]),
        chip_panel('one-refinement', '代入两点核算', readout),
    ], weights=[1.66, 1], gap='standard')
    slide = page(
        'step-halving', '步长减半，梯形法误差约剩四分之一',
        r'构造示例 · 计算 $\sin x$ 在 $[0,\pi/2]$ 上的积分，真值为 1。两种方法使用相同的等距网格。',
        blocks, body, tables=[table], charts=[convergence_chart(errors)], evidence_refs=(),
    )
    slide['semantic']['inline_math'] = ['takeaway']
    slide['semantic']['speaker_notes'] = 'E 表示积分结果与真值 1 的绝对误差。表格保留六位小数，比值取自未舍入的计算值。'
    result = deck('trapezoid-convergence-check', [slide])
    result['theme'].update(font_family='Microsoft YaHei', font_file='msyh.ttc', bold_font_file='msyh.ttc')
    result['presentation']['text_capacity_policy'] = 'strict'
    return result
