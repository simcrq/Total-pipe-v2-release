"""Compare constructed recovery readings on a log concentration axis."""
from statistics import mean, stdev

from common import block_leaf, chip_panel, comparison_table, deck, page, region


def make_deck():
    concentration = [0.1, 1, 10, 100]
    readings = {
        '方案 A': [(68, 72, 76), (87, 90, 93), (96, 98, 100), (98, 100, 102)],
        '方案 B': [(89, 92, 95), (95, 97, 99), (98, 100, 102), (100, 102, 104)],
    }
    series = [{'label': label, 'x_values': concentration,
               'values': [mean(group) for group in groups],
               'y_error': [stdev(group) for group in groups], 'evidence_refs': []}
              for label, groups in readings.items()]
    chart = {'id': 'recovery', 'kind': 'scatter', 'basis': 'explain', 'illustrative': True,
             'x': {'label': '加标浓度 (μg/L)', 'scale': 'log'}, 'y': {'label': '回收率', 'unit': '%'},
             'series': series, 'source': '脚本内构造读数',
             'annotations': [{'text': f"A：{series[0]['values'][0]}%", 'series': 0, 'point': 0,
                              'dx': 52, 'dy': -28}]}
    rows = [('加标浓度', 'A (%)', 'B (%)')]
    for index in (0, -1):
        rows.append((f'{concentration[index]:g} μg/L', str(series[0]['values'][index]),
                     str(series[1]['values'][index])))
    table = comparison_table('ends', rows, [1.45, 1, 1])
    difference = [b-a for a, b in zip(series[0]['values'], series[1]['values'])]
    provenance = {'kind': 'example', 'constructed': True, 'source': 'dose_recovery_composite.py'}
    notes = [
        {'id': 'low', 'component': 'body', 'text': f'最低浓度相差 {difference[0]} 个百分点。',
         'text_flow': 'native_numbered_list', 'list_start': 1},
        {'id': 'high', 'component': 'body', 'text': f'最高浓度相差 {difference[-1]} 个百分点。',
         'text_flow': 'native_numbered_list', 'list_start': 2},
    ]
    for item in notes:
        item.update(basis='supplement', supplement=provenance)
    body = region('series-and-readout', 'columns', [
        {'id': 'points', 'type': 'chart', 'ref': 'recovery'},
        chip_panel('endpoints', '对照两端', region('table-and-notes', 'stack', [
            {'id': 'endpoint-table', 'type': 'table', 'ref': 'ends'},
            *[block_leaf(item['id']) for item in notes],
        ], gap='standard', align='center')),
    ], weights=[1.6, 1], gap='standard')
    slide = page('dose-recovery', '两种方案在低浓度的回收率差异最大',
                 '构造示例 · 每个浓度有三次读数，点为平均值，误差棒为 ±1 样本标准差。',
                 notes, body, charts=[chart], tables=[table], evidence_refs=())
    output = deck('dose-recovery-composite', [slide])
    output['presentation']['text_capacity_policy'] = 'strict'
    return output
