"""Keep a supplied figure intact and put two independent reading cues beside it."""
from common import EXAMPLES, SOURCE, block_leaf, deck, page, region


def make_deck():
    # Use an existing software-demo figure. For a paper figure, use origin=paper
    # and fill both source_figure fields and source_label from the actual source.
    asset = {
        'path': str(EXAMPLES/'demo_deck/figures/fig1_quality.png'),
        'origin': 'reference',
        'reference_source': 'Bundled Total-pipe demo · Fig. 1',
    }
    figure = {
        'asset_id': 'layout-benchmark',
        'source_label': 'Total-pipe demo · Fig. 1',
        'caption': 'Both methods use the same two-figure fixture.',
    }
    cues = [
        {'id': 'baseline', 'component': 'body',
         'text': 'Start at 1.00×, where the box and its text have the same height.',
         'text_flow': 'native_numbered_list', 'list_start': 1, 'evidence_refs': [SOURCE]},
        {'id': 'worst-case', 'component': 'body',
         'text': 'Compare the mean bar and the worst-page value below it.',
         'text_flow': 'native_numbered_list', 'list_start': 2, 'evidence_refs': [SOURCE]},
    ]
    body = region('figure-and-cues', 'columns', [
        {'id': 'original-figure', 'type': 'figure', 'ref': 0},
        region('readout', 'stack', [block_leaf(cue['id']) for cue in cues],
               align='center'),
    ], weights=[2.2, 1], gap='standard')
    slide = page('benchmark', 'Compare the average and the worst page',
                 'On this fixture, the packer fits the text more closely.', cues, body,
                 figures=[figure])
    return deck('figure-readout', [slide], {'layout-benchmark': asset})
