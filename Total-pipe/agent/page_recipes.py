"""Small, tested page recipes for a constrained PageScene pilot.

A recipe owns geometry and native affordances.  The author supplies scientific
slots only: no coordinates, no card vocabulary, no renderer API names.  This is
the first slice of the capability-contract approach: native lists, inline math,
tables and paths are the default path, not optional decorations.
"""
from __future__ import annotations

import re
from pathlib import Path

MARGIN = 0.72
PAGE_W = 13.333

RECIPES = {
    'cover': ('figure', 'stats'),
    'contrast': ('two_lists', 'waveforms', 'key_line'),
    'figure_readout': ('figure', 'readout_list'),
    'metrics': ('two_figures', 'metric_list', 'condition'),
    'table_compare': ('table', 'big_stat', 'readout_list'),
    'closing': ('big_stat', 'path_list', 'stats'),
    'eviz_chain': ('eviz_paths', 'eviz_labels'),
}


def _text(oid, box, text, size=18, role='body', color=None, bold=False,
          emphasis=None, align='left', valign='top', spacing=1.08):
    obj = {'id': oid, 'type': 'text', 'box': list(box), 'role': role, 'text': text,
           'size': size, 'align': align, 'valign': valign, 'line_spacing': spacing}
    if color:
        obj['color'] = color
    if bold:
        obj['bold'] = True
    if emphasis:
        obj['emphasis'] = list(emphasis)
    return obj


def _list(oid, box, items, size=18, style='dot', space_after=7, color=None):
    return {'id': oid, 'type': 'list', 'box': list(box), 'role': 'body',
            'size': size, 'bullet_style': style, 'space_after': space_after,
            'items': [dict(item, level=item.get('level', 0)) for item in items],
            **({'color': color} if color else {})}


def _image(oid, box, path):
    return {'id': oid, 'type': 'image', 'box': list(box), 'path': str(Path(path)), 'fit': 'contain'}


def _line(oid, box, color='#0B6E99', width=1.4, dash=False):
    return {'id': oid, 'type': 'line', 'box': list(box), 'stroke': color,
            'stroke_width': width, 'dash': dash}


def _path(oid, box, d, color='#0B6E99', width=2.0):
    return {'id': oid, 'type': 'path', 'box': list(box), 'view_box': [0, 0, 100, 30],
            'fill': 'none', 'stroke': color, 'stroke_width': width, 'd': d}


def _page(spec, objects, notes=''):
    return {'id': spec['id'], 'section': spec.get('section', ''),
            'title': spec['title'], 'take': spec['take'], 'objects': objects,
            'notes': notes or spec.get('notes', '')}


def cover(spec):
    image = spec.get('figure') or {}
    objects = []
    if image.get('path'):
        objects.append(_image('cover_image', [1.2, 2.18, 10.9, 2.62], image['path']))
        objects.append(_text('cover_caption', [1.2, 4.9, 10.9, .25],
                             image.get('caption', 'Fig. 1a'), 9.5, 'caption', '#5E7084'))
    objects.append(_text('cover_meta', [MARGIN, 5.2, 11.9, .28],
                         spec.get('meta', ''), 11.5, 'label', '#0B6E99', True))
    stats = spec.get('stats') or [('13', '种功能'), ('7', '数字逻辑'), ('6', '模拟功能')]
    for index, (number, label) in enumerate(stats[:3]):
        x = (0.72, 4.5, 8.55)[index]
        objects.append(_text('stat_%d' % index, [x, 5.58, 1.25, .55],
                             number, 30, 'label', '#0B6E99', True))
        objects.append(_text('stat_label_%d' % index, [x + 1.35, 5.72, 1.7, .3],
                             label, 12, 'label', '#102A43'))
        if index:
            objects.append(_line('sep_%d' % index, [x - .28, 5.62, x - .28, 6.2],
                                 '#D7DEE6', .8))
    return _page(spec, objects)


def contrast(spec):
    left = spec.get('left') or {}
    right = spec.get('right') or {}
    objects = [
        _text('left_head', [0.72, 2.24, 4.6, .3], left.get('head', ''), 11.5, 'label', '#0B6E99', True),
        _list('left_list', [0.72, 2.68, 4.8, 1.55], left.get('items') or [], 19, 'square', 6),
        _text('right_head', [6.72, 2.24, 5.4, .3], right.get('head', ''), 11.5, 'label', '#D97706', True),
        _list('right_list', [6.72, 2.68, 5.4, 1.55], right.get('items') or [], 19, 'dash', 6),
        _line('column_rule', [6.28, 2.3, 6.28, 5.1], '#D7DEE6', .8),
        _path('wave_digital', [0.95, 4.45, 3.4, .55],
              'M 0 15 L 0 5 L 20 5 L 20 25 L 40 25 L 40 5 L 60 5 L 60 25 L 80 25 L 80 5 L 100 5',
              '#0B6E99', 2.0),
        _path('wave_analog', [6.95, 4.45, 3.4, .55],
              'M 0 15 C 8 2 17 2 25 15 C 33 28 42 28 50 15 C 58 2 67 2 75 15 C 83 28 92 28 100 15',
              '#D97706', 2.0),
        _line('key_rule', [0.72, 5.55, 0.77, 6.05], '#0B6E99', 2.0),
        _text('key_line', [0.98, 5.55, 11.5, .5], spec.get('key', ''), 19, 'body',
              None, True),
    ]
    return _page(spec, objects)


def figure_readout(spec):
    image = spec.get('figure') or {}
    objects = [
        _image('figure', [1.2, 2.18, 10.9, 2.65], image['path']),
        _text('caption', [1.2, 4.9, 10.9, .25], image.get('caption', ''), 9.5, 'caption', '#5E7084'),
        _text('read_label', [0.72, 5.28, 5.0, .28], spec.get('read_label', '读图'), 11.2, 'label', '#0B6E99', True),
        _list('readout', [0.72, 5.66, 11.9, 1.15], spec.get('items') or [], 18, 'arrow', 5),
    ]
    return _page(spec, objects)


def metrics(spec):
    images = spec.get('figures') or []
    objects = []
    positions = ([0.72, 2.2, 4.0, 3.65], [4.85, 2.2, 4.0, 3.65])
    for index, image in enumerate(images[:2]):
        objects.append(_image('metric_image_%d' % index, positions[index], image['path']))
    objects.extend([
        _text('caption', [0.72, 5.92, 8.1, .25], spec.get('caption', ''), 9.5, 'caption', '#5E7084'),
        _list('metric_list', [9.05, 2.24, 3.65, 3.15], spec.get('items') or [], 20, 'square', 12),
        _text('condition', [0.72, 6.28, 8.1, .45], spec.get('condition', ''), 16.5, 'label', '#5E7084'),
    ])
    return _page(spec, objects)


def table_compare(spec):
    table = spec['table']
    objects = [
        {'id': 'compare_table', 'type': 'table', 'box': [0.72, 2.28, 8.3, 3.4],
         'rows': table['rows'], 'col_widths': table.get('col_widths', [1.2, 2.4, 2.3, 1.9]),
         'row_height': table.get('row_height', .82), 'header': True,
         'header_fill': table.get('header_fill', '#3F6FA8'), 'font_size': 13.2},
        _text('big_stat', [9.35, 2.24, 1.15, .9], spec.get('big', '13'), 42, 'label', '#0B6E99', True),
        _text('big_label', [10.65, 2.48, 1.5, .35], spec.get('big_label', '种功能'), 13, 'label', '#102A43', True),
        _list('readout', [9.35, 3.55, 3.3, 2.45], spec.get('items') or [], 18, 'dot', 8),
        _text('source', [0.72, 6.55, 10.0, .3], spec.get('source', ''), 11.2, 'label', '#D97706'),
    ]
    return _page(spec, objects)


def closing(spec):
    objects = [
        _text('big_stat', [0.72, 2.2, 2.7, 1.7], spec.get('big', '13'), 104, 'label', '#0B6E99', True),
        _text('big_label', [0.95, 3.95, 2.4, .38], spec.get('big_label', '种功能'), 21, 'label', '#102A43', True),
        _text('big_sub', [0.95, 4.36, 2.4, .3], spec.get('big_sub', '一个结构'), 11.5, 'label', '#5E7084'),
        _list('path_list', [4.1, 2.38, 8.2, 2.8], spec.get('items') or [], 20, 'arrow', 10),
        _text('stats', [0.72, 5.45, 11.9, .45], spec.get('stats', ''), 17, 'label', '#0B6E99', True),
        _text('fixed', [0.72, 5.98, 11.9, .4], spec.get('fixed', ''), 18, 'body', None, True),
    ]
    return _page(spec, objects)


def eviz_chain(spec):
    """Render a validated ExplainViz spec as native PageScene paths and labels.

    EViz owns the bounded visual spec and its source-fact validation.  This
    adapter only lowers its path/label JSON into the same native vocabulary as
    the rest of PageScene; it does not re-derive scientific relations.
    """
    from deck_compiler.explain_viz.specs import validate_spec
    from deck_compiler.explain_viz.templates import build as build_viz

    eviz = spec.get('eviz') or {}
    facts = eviz.get('facts') or {}
    visual = eviz.get('spec') or {}
    validate_spec(visual, facts)
    theme = spec.get('theme') or {'accent': '#0B6E99', 'background': '#FFFFFF',
                                  'foreground': '#1B2A3A'}
    viz = build_viz(visual, theme)
    box = spec.get('box') or [0.72, 2.35, 11.9, 4.1]
    vx, vy, vw, vh = viz['view_box']
    sx, sy = box[2] / vw, box[3] / vh
    tokens = {'background': '#FFFFFF', 'foreground': '#1B2A3A', 'accent': '#0B6E99',
              'none': 'none'}
    objects = []
    process = visual.get('template') == 'process_steps@1'
    for index, item in enumerate(viz.get('paths') or []):
        # A process chain reads as text + arrows, not a row of filled cards.
        if process and re.search(r'_step_\d+$', str(item.get('id'))):
            continue
        fill = tokens.get(str(item.get('fill')), item.get('fill', 'none'))
        stroke = tokens.get(str(item.get('stroke')), item.get('stroke', '#1B2A3A'))
        objects.append({
            'id': 'eviz_path_%d' % index, 'type': 'path', 'box': list(box),
            'view_box': [vx, vy, vw, vh], 'commands': item['commands'],
            'fill': fill, 'stroke': stroke,
            'stroke_width': item.get('line_width', 2),
        })
    for index, item in enumerate(viz.get('labels') or []):
        lx, ly, lw, lh = item['box']
        objects.append(_text(
            'eviz_label_%d' % index,
            [box[0] + (lx - vx) * sx, box[1] + (ly - vy) * sy, lw * sx, lh * sy],
            item['text'], 9.2 if item['text'] in ('示意', 'Schematic') else 12.5,
            'caption' if item['text'] in ('示意', 'Schematic') else 'label',
            '#5E7084' if item['text'] in ('示意', 'Schematic') else '#102A43',
            True if item['text'] not in ('示意', 'Schematic') else False,
            align='center', valign='middle'))
    return _page(spec, objects, spec.get('notes', 'ExplainViz process chain; schematic geometry.'))


BUILDERS = {
    'cover': cover,
    'contrast': contrast,
    'figure_readout': figure_readout,
    'metrics': metrics,
    'table_compare': table_compare,
    'closing': closing,
    'eviz_chain': eviz_chain,
}


def compose(page_spec):
    """Expand one recipe page; raise early on an unknown recipe."""
    recipe = page_spec.get('recipe')
    if recipe not in BUILDERS:
        raise ValueError('unknown recipe: %r (choose %s)' % (recipe, ', '.join(BUILDERS)))
    return BUILDERS[recipe](page_spec)


def compose_deck(page_specs):
    return {'schema_version': '0.1', 'deck_id': 'recipe-pilot',
            'theme': {'font': 'Microsoft YaHei', 'ink': '#1B2A3A', 'navy': '#102A43',
                      'accent': '#0B6E99', 'orange': '#D97706', 'gray': '#5E7084',
                      'light': '#F3F6F8'},
            'bindings': {}, 'pages': [compose(spec) for spec in page_specs]}
