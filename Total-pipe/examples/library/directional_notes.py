"""Directional copy for one image, one editable flow and one standalone formula."""
from common import EXAMPLES, deck, page


def attachments(kind, ref, top, left, right, bottom):
    return [
        {'id': 'top-note', 'component': 'body', 'text': top,
         'text_for': {'kind': kind, 'ref': ref, 'position': 'top'}},
        {'id': 'left-note', 'component': 'caption', 'text': left,
         'caption_for': {'kind': kind, 'ref': ref, 'position': 'left'}},
        {'id': 'right-note', 'component': 'body', 'text': right,
         'text_for': {'kind': kind, 'ref': ref, 'position': 'right'}},
        {'id': 'bottom-note', 'component': 'caption', 'text': bottom,
         'caption_for': {'kind': kind, 'ref': ref, 'position': 'bottom'}},
    ]


def make_deck():
    flow = {'id': 'workflow', 'type': 'process', 'direction': 'horizontal',
            'nodes': [{'id': key, 'title': title, 'shape': 'rounded-rect'}
                      for key, title in [('in', 'Input'), ('check', 'Check'), ('out', 'Output')]],
            'edges': [{'from': 'in', 'to': 'check'}, {'from': 'check', 'to': 'out'}]}
    pages = [
        page('image', 'Place guide text around an image',
             'The image and its annotations are measured together.',
             attachments('figure', 'example-image', 'Identify the comparison.', 'Baseline',
                         'Check the plotted alternative.', 'Illustrative chart from the software fixture.'),
             {'id': 'image', 'type': 'figure', 'ref': 0},
             figures=[{'asset_id': 'example-image', 'caption': 'Illustrative schematic of software output.'}]),
        page('flow', 'Label the input and output beside a flow',
             'The native shapes and connections remain editable.',
             attachments('graphic', 'workflow', 'Read the flow left to right.', 'Input',
                         'Inspect the output.', 'Illustrative flow. The arrows show reading order.'),
             {'id': 'flow', 'type': 'graphic', 'ref': 'workflow'}, graphics=[flow]),
        page('formula', 'Explain a standalone equation beside it',
             'Place variable definitions next to the editable equation.',
             [{'id': 'energy', 'component': 'formula', 'text': r'E=h\nu'}]
             + attachments('formula', 'energy', 'Photon energy and frequency', 'E is photon energy.',
                           'ν is frequency.', 'h is the Planck constant.'),
             {'id': 'equation', 'type': 'block', 'ref': 'energy'}),
    ]
    image = {'path': str(EXAMPLES/'demo_deck/figures/fig1_quality.png'),
             'origin': 'generated', 'generator': 'bundled-demo-fixture'}
    return deck('directional-notes', pages, {'example-image': image})
