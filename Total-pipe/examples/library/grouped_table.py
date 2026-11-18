"""Compare two estimators with a true merged header and visible example inputs."""
from statistics import mean, median

from common import block_leaf, deck, page, region


def cell(row, column, text, **options):
    return {'id': f'cell-{row}-{column}', 'row': row, 'column': column,
            'text': text, **options}


def make_deck():
    baseline = [10, 11, 12, 13, 14]
    with_spike = [*baseline[:-1], 54]
    cells = [
        cell(0, 0, 'Estimator', row_span=2),
        cell(0, 1, 'Readout (ms)', column_span=2, align='center'),
        cell(1, 1, 'Baseline', align='center'),
        cell(1, 2, 'With a spike', align='center'),
    ]
    for row, estimator in enumerate((mean, median), start=2):
        cells.extend([
            cell(row, 0, estimator.__name__.title()),
            cell(row, 1, str(estimator(baseline)), align='center'),
            cell(row, 2, str(estimator(with_spike)), align='center'),
        ])
    table = {
        'id': 'estimators', 'origin': 'generated', 'row_count': 4, 'column_count': 3,
        'header_rows': 2, 'column_weights': [1.25, 1, 1], 'cells': cells,
    }
    inputs = {
        'id': 'inputs', 'component': 'body',
        'text': '构造示例 · Start with 10, 11, 12, 13 and 14 ms. Replace 14 ms with 54 ms.',
        'basis': 'supplement',
        'supplement': {'kind': 'example', 'constructed': True,
                       'source': 'Constructed inputs in grouped_table.py'},
    }
    body = region('table-and-inputs', 'stack', [
        {'id': 'table', 'type': 'table', 'ref': 'estimators'},
        block_leaf(inputs['id']),
    ], gap='standard', align='center')
    slide = page('outlier', 'One extreme reading shifts the mean',
                 'For these five values, the median stays at 12 ms.', [inputs], body,
                 tables=[table], evidence_refs=())
    return deck('grouped-table', [slide])
