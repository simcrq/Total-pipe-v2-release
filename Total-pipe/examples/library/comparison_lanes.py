"""Two named process lanes, with native state boxes and separate action labels."""
from common import deck, page


def rounded_box(id, x, y, width, height):
    right, bottom, radius = x+width, y+height, 9
    return {'id': id, 'fill': '#EEF5F6', 'stroke': 'accent', 'commands': [
        ['M', x+radius, y], ['L', right-radius, y], ['Q', right, y, right, y+radius],
        ['L', right, bottom-radius], ['Q', right, bottom, right-radius, bottom],
        ['L', x+radius, bottom], ['Q', x, bottom, x, bottom-radius],
        ['L', x, y+radius], ['Q', x, y, x+radius, y], ['Z'],
    ]}


def arrow(id, left, right, y):
    return {'id': id, 'stroke': 'accent', 'line_width': 2, 'commands': [
        ['M', left, y], ['L', right, y], ['M', right-9, y-6],
        ['L', right, y], ['L', right-9, y+6],
    ]}


def make_deck():
    graphic = {'id': 'routes', 'type': 'path', 'view_box': [0, 0, 1120, 267],
               'paths': [{'id': 'divider', 'stroke': '#9AAFB4', 'commands': [['M', 0, 134], ['L', 1120, 134]]}],
               'labels': []}
    for id, name, y, states, actions in (
        ('direct', 'A. Direct route', 0, ('Input sample', 'Aligned sample', 'Placed sample'), ('Align', 'Place')),
        ('assisted', 'B. Assisted route', 146, ('Input sample', 'Carrier and sample', 'Placed sample'), ('Mount', 'Release')),
    ):
        graphic['labels'].append({'id': id, 'text': name, 'box': [4, y+1, 240, 34]})
        for index, (x, state) in enumerate(zip((4, 436, 868), states), 1):
            key = f'{id}-state-{index}'
            graphic['paths'].append(rounded_box(key, x, y+49, 246, 66))
            graphic['labels'].append({'id': key, 'text': state, 'box': [x+9, y+55, 228, 54]})
        for index, (left, action) in enumerate(zip((260, 692), actions), 1):
            key = f'{id}-action-{index}'
            graphic['paths'].append(arrow(key, left, left+166, y+85))
            graphic['labels'].append({'id': key, 'text': action, 'box': [left+2, y+39, 162, 39]})
    return deck('comparison-lanes', [page(
        'comparison', 'Compare two routes under one heading',
        'Illustrative workflow. Aligned boxes identify the states to compare.',
        [], {'id': 'route-comparison', 'type': 'graphic', 'ref': 'routes'}, graphics=[graphic],
    )])
