"""Build an illustrative comparison with error bars from explicit sample data."""
from statistics import mean, stdev

from common import block_leaf, deck, page, region


def make_deck():
    # Three constructed readings per condition. Means and sample SDs share
    # these inputs, so editing a reading updates both summaries on rebuild.
    readings = {
        'Sample': [(11, 12, 13), (16, 18, 20), (23, 25, 27), (27, 30, 33)],
        'Blank': [(8, 9, 10), (8, 9, 10), (9, 10, 11), (9, 10, 11)],
    }
    chart = {
        'id': 'response', 'kind': 'line', 'basis': 'explain', 'illustrative': True,
        'x': {'label': 'Exposure time (s)', 'values': [0, 10, 20, 30]},
        'y': {'label': 'Signal', 'unit': 'mV'},
        'series': [
            {'label': label, 'values': [mean(group) for group in groups],
             'y_error': [stdev(group) for group in groups], 'evidence_refs': []}
            for label, groups in readings.items()
        ],
        'annotations': [{'text': 'Final sample', 'series': 0, 'point': 3, 'dx': -147, 'dy': 30}],
        'source': 'Constructed readings · layout example',
    }
    note = {'id': 'error-definition', 'component': 'body',
            'text': 'Points show the mean. Bars show ±1 sample SD for three readings per point.'}
    body = region('read-the-chart', 'stack', [
        {'id': 'plot', 'type': 'chart', 'ref': 'response'},
        block_leaf(note['id']),
    ], weights=[7, 1])
    slide = page('uncertainty', 'The sample signal rises faster than the blank',
                 'Illustrative time series with matched readout times.', [note], body,
                 charts=[chart], evidence_refs=())
    return deck('chart-uncertainty', [slide])
