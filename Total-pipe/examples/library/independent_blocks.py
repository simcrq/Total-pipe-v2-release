"""Two named groups with one native, separately editable paragraph per block."""
from common import SOURCE, block_leaf, deck, page, region


def named_group(id, title, blocks):
    return {
        'id': id, 'type': 'panel', 'title': title, 'padding': 'compact', 'gap': 'compact',
        'frame': {'title_band': 'chip', 'title_fill': '#266E72', 'title_color': '#FFFFFF'},
        'body': region(f'{id}-body', 'stack', [block_leaf(block['id']) for block in blocks]),
    }


def make_deck():
    parallel = [
        {'id': 'device-condition', 'component': 'body', 'text': 'Keep the device condition visible.',
         'text_flow': 'native_bullet_list', 'bullet_icon': '→', 'evidence_refs': [SOURCE]},
        {'id': 'baseline', 'component': 'body', 'text': 'Name the baseline alongside the comparison.',
         'text_flow': 'native_bullet_list', 'bullet_icon': '→', 'evidence_refs': [SOURCE]},
    ]
    steps = [
        {'id': 'read-baseline', 'component': 'body', 'text': 'Read the baseline first.',
         'text_flow': 'native_numbered_list', 'list_start': 1, 'evidence_refs': [SOURCE]},
        {'id': 'read-change', 'component': 'body', 'text': 'Then point to the change under the same condition.',
         'text_flow': 'native_numbered_list', 'list_start': 2, 'evidence_refs': [SOURCE]},
    ]
    body = region('groups', 'stack', [
        named_group('parallel-cues', 'Read together', parallel),
        named_group('ordered-cues', 'Read in order', steps),
    ])
    return deck('independent-blocks', [page(
        'markers', 'Independent blocks keep their own markers',
        'Arrows indicate peer points. Numbers give a reading order.', parallel + steps, body,
    )])
