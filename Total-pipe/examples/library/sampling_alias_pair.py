"""Compare two continuous signals that are identical on one sampling grid."""
from math import cos, tau

from common import block_leaf, chip_panel, deck, page, region


SAMPLE_RATE_HZ = 8
FREQUENCIES_HZ = (3, SAMPLE_RATE_HZ - 3)
TIMES_S = [index / (2 * SAMPLE_RATE_HZ) for index in range(2 * SAMPLE_RATE_HZ + 1)]


def signal_chart(frequency):
    marked_point = 4
    return {
        'id': f'signal-{frequency}', 'kind': 'line', 'basis': 'explain', 'illustrative': True,
        'x': {'label': '时间 (s)', 'values': TIMES_S},
        'y': {'label': '归一化幅度'},
        'series': [{'label': f'{frequency} Hz 余弦', 'evidence_refs': [],
                    'values': [round(cos(tau * frequency * t), 8) for t in TIMES_S]}],
        'annotations': [{'text': f'取样 {TIMES_S[marked_point]:g} s', 'series': 0,
                         'point': marked_point, 'dx': 43, 'dy': -90}],
        'source': '余弦模型计算',
    }


def make_deck():
    low, high = FREQUENCIES_HZ
    blocks = [
        {'id': 'grid', 'component': 'body', 'text': f'从零时刻起，每隔 {1000/SAMPLE_RATE_HZ:g} ms 取样。',
         'text_flow': 'native_numbered_list', 'list_start': 1},
        {'id': 'match', 'component': 'body', 'text': '任意整数采样序号 n 上，两组取值相等。',
         'text_flow': 'native_numbered_list', 'list_start': 2},
        {'id': 'identity', 'component': 'formula',
         'text': rf'\cos(2\pi\cdot {high}n/{SAMPLE_RATE_HZ})=\cos(2\pi\cdot {low}n/{SAMPLE_RATE_HZ})'},
    ]
    provenance = {'kind': 'example', 'constructed': True, 'source': 'sampling_alias_pair.py 的同相余弦模型'}
    for block in blocks:
        block.update(basis='supplement', supplement=provenance)

    charts = [signal_chart(frequency) for frequency in FREQUENCIES_HZ]
    display = region('synchronized-plots', 'columns', [
        chip_panel(f'panel-{frequency}', f'{frequency} Hz 信号',
                   {'id': f'chart-{frequency}', 'type': 'chart', 'ref': chart['id']})
        for frequency, chart in zip(FREQUENCIES_HZ, charts)
    ], fit='hug', gap='standard')
    readout = region('sample-comparison', 'columns', [
        region('sample-steps', 'stack', [block_leaf('grid'), block_leaf('match')]),
        block_leaf('identity'),
    ], weights=[1.08, 1], fit='hug', gap='standard')
    body = region('sampling-model', 'stack', [display, readout], align='center')
    slide = page('aliasing', f'{SAMPLE_RATE_HZ} Hz 采样无法区分 {low} Hz 和 {high} Hz 余弦',
                 '构造示例 · 初相位均为零。两图采用同一时间和幅度尺度，箭头指向同一个采样时刻。',
                 blocks, body, charts=charts, evidence_refs=())
    result = deck('sampling-alias-pair', [slide])
    result['theme'].update(font_family='Microsoft YaHei', font_file='msyh.ttc', bold_font_file='msyh.ttc')
    result['presentation']['text_capacity_policy'] = 'strict'
    return result
