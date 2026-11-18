"""Draw a falsifiable mechanism with native nodes and tentative connections."""
from common import block_leaf, deck, page, region


def make_deck():
    mechanism = {
        'id': 'leakage', 'type': 'mechanism',
        'nodes': [
            {'id': 'passivation', 'title': 'Passivation'},
            {'id': 'traps', 'title': 'Interface traps'},
            {'id': 'leakage', 'title': 'Leakage current'},
        ],
        'edges': [
            {'from': 'passivation', 'to': 'traps', 'kind': 'inhibit', 'basis': 'hypothesis'},
            {'from': 'traps', 'to': 'leakage', 'kind': 'activate', 'basis': 'hypothesis'},
        ],
    }
    check = {'id': 'test', 'component': 'body',
             'text': 'Compare trap density and leakage at the same bias in devices with and without passivation.'}
    body = region('hypothesis-and-test', 'stack', [
        {'id': 'mechanism', 'type': 'graphic', 'ref': 'leakage'},
        block_leaf(check['id']),
    ], gap='standard', align='center')
    slide = page('traps', 'Could passivation reduce leakage?',
                 'Hypothesis: passivation lowers the density of interface traps that contribute to leakage.',
                 [check], body, graphics=[mechanism], evidence_refs=())
    return deck('mechanism-hypothesis', [slide])
