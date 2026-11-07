"""Named visual-style packs: the shape, fill and rule language a deck is drawn in.

Composition decides *what* is on a page; a style pack decides *how it is drawn*. Keeping the two
apart is what stops "academic" from being a pile of special cases in the emitters: a deck names a
pack (or overrides one token), and every native node, edge and container reads the same resolved
values.

Packs are data, not code. A new house style is a dict plus, at most, a token the emitters already
understand; no rendering path branches on the pack name.
"""
import math
import re

COLOR = re.compile(r'^#[0-9A-Fa-f]{6}$')

SHAPE_NAMES = ('rect', 'rounded-rect', 'ellipse', 'diamond', 'hexagon', 'parallelogram', 'trapezoid')
FILLS = ('none', 'tint', 'tint-strong')
STROKES = ('accent', 'foreground', 'muted', 'none')
ALIGNS = ('left', 'center')

PACKS = {
    # Research seminar: square nodes, hairline rules, no colour fill. A figure or a table carries
    # the page; the diagram is a structure, not a card.
    'academic': {
        'graphic': {
            'node': {'shape': 'rect', 'fill': 'none', 'stroke': 'foreground', 'stroke_width': 1.25,
                     'title_size': 24, 'body_size': 20, 'align': 'center', 'bold': False},
            'emphasis': {'fill': 'none', 'stroke': 'accent', 'stroke_width': 2.25},
            'edge': {'color': 'muted', 'width': 1.25, 'arrow': 'triangle'},
        },
        'panel': {'fill': 'none', 'border': '#D8DEE6', 'border_width': 1., 'title_fill': 'none',
                  'radius': 0.},
        # Run-level emphasis is a typographic mark, not a second colour system: the deck's accent
        # ink for the phrase that carries the claim, and one highlighter tone for a symbol that has
        # to survive a projector. Both stay opt-in because they are written in the text.
        'text': {'emphasis': 'accent', 'highlight': '#FFF1A8', 'citation': 'muted'},
        # Page furniture is the deck's own signature: one hairline and a page number, in the
        # supporting ink rather than the accent, so it never competes with the page content.
        'page': {'sparse_balance': 'center', 'furniture': 'rule', 'footer_rule': '#D8DEE6',
                 'footer_ink': 'muted', 'number_ink': 'muted', 'footer_size': 20, 'number_size': 22},
    },
    # The previous default: tinted rounded cards. Kept so existing decks are unchanged.
    'commercial': {
        'graphic': {
            'node': {'shape': 'rounded-rect', 'fill': 'tint', 'stroke': 'accent', 'stroke_width': 2.,
                     'title_size': 30, 'body_size': 26, 'align': 'center', 'bold': True},
            'emphasis': {'fill': 'tint-strong', 'stroke': 'accent', 'stroke_width': 3.5},
            'edge': {'color': 'accent', 'width': 2.5, 'arrow': 'triangle'},
        },
        'panel': {'fill': '#F8FAFC', 'border': '#CBD5E1', 'border_width': 1., 'title_fill': '#EFF6FF',
                  'radius': 8.},
        'text': {'emphasis': 'accent', 'highlight': '#FFE58A', 'citation': '#0070C0'},
        'page': {'sparse_balance': 'top', 'furniture': 'rule', 'footer_rule': '#CBD5E1',
                 'footer_ink': 'muted', 'number_ink': 'muted', 'footer_size': 20, 'number_size': 22},
    },
    # Print-like: black-only rules, no tint, tighter type. For handouts and thesis defences.
    'print': {
        'graphic': {
            'node': {'shape': 'rect', 'fill': 'none', 'stroke': 'foreground', 'stroke_width': 1.,
                     'title_size': 24, 'body_size': 20, 'align': 'center', 'bold': False},
            'emphasis': {'fill': 'none', 'stroke': 'foreground', 'stroke_width': 1.75},
            'edge': {'color': 'foreground', 'width': 1., 'arrow': 'triangle'},
        },
        'panel': {'fill': 'none', 'border': '#111111', 'border_width': .75, 'title_fill': 'none',
                  'radius': 0.},
        'text': {'emphasis': 'foreground', 'highlight': '#EDEDED', 'citation': 'muted'},
        'page': {'sparse_balance': 'center', 'furniture': 'rule', 'footer_rule': '#111111',
                 'footer_ink': 'muted', 'number_ink': 'muted', 'footer_size': 20, 'number_size': 22},
    },
}

DEFAULT_PACK = 'academic'


class StyleError(ValueError):
    pass


def _merge(base, override, path=''):
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict):
            if not isinstance(base.get(key), dict):
                raise StyleError(f'{path}{key}: not a style group')
            result[key] = _merge(base[key], value, f'{path}{key}.')
        else:
            if key not in base:
                raise StyleError(f'{path}{key}: unknown style token')
            result[key] = value
    return result


def _color(value, path):
    if not isinstance(value, str):
        raise StyleError(f'{path}: colour or token name expected')
    if value in STROKES or value in FILLS or value in ('accent', 'foreground', 'muted', 'tint'):
        return value
    if not COLOR.fullmatch(value):
        raise StyleError(f'{path}: colour must be #RRGGBB or a token name')
    return value


def validate_style(value):
    """Human-readable errors for an IR ``presentation.visual_style`` object."""
    errors = []
    if not isinstance(value, dict):
        return ['visual_style must be an object']
    if set(value) - {'pack', 'overrides'}:
        errors.append('visual_style accepts only pack and overrides')
    pack = value.get('pack', DEFAULT_PACK)
    if pack not in PACKS:
        errors.append(f"visual_style.pack must be one of {sorted(PACKS)}")
    overrides = value.get('overrides', {})
    if not isinstance(overrides, dict):
        return errors+['visual_style.overrides must be an object of dotted tokens']
    flat = flatten(PACKS.get(pack, PACKS[DEFAULT_PACK]))
    for dotted, token in overrides.items():
        path = f'visual_style.overrides.{dotted}'
        if dotted not in flat:
            errors.append(f'{path}: unknown token')
            continue
        name = dotted.rsplit('.', 1)[-1]
        if name == 'shape':
            if token not in SHAPE_NAMES:
                errors.append(f'{path}: one of {list(SHAPE_NAMES)} expected')
        elif name == 'align':
            if token not in ALIGNS:
                errors.append(f'{path}: left or center expected')
        elif name == 'arrow':
            if token not in ('triangle', 'none'):
                errors.append(f'{path}: triangle or none expected')
        elif name == 'sparse_balance':
            if token not in ('center', 'top'):
                errors.append(f'{path}: center or top expected')
        elif name == 'furniture':
            if token not in ('rule', 'none'):
                errors.append(f'{path}: rule or none expected')
        elif name == 'bold':
            if not isinstance(token, bool):
                errors.append(f'{path}: true or false expected')
        elif name.endswith(('width', 'radius', 'size')):
            if isinstance(token, bool) or not isinstance(token, (int, float)) or not math.isfinite(token):
                errors.append(f'{path}: number expected')
        else:
            try:
                _color(token, path)
            except StyleError as error:
                errors.append(str(error))
    return errors


def flatten(tree, prefix=''):
    flat = {}
    for key, value in tree.items():
        dotted = f'{prefix}{key}'
        flat.update(flatten(value, dotted+'.') if isinstance(value, dict) else {dotted: value})
    return flat


def unflatten(flat):
    tree = {}
    for dotted, value in flat.items():
        cursor = tree
        *head, last = dotted.split('.')
        for part in head:
            cursor = cursor.setdefault(part, {})
        cursor[last] = value
    return tree


def resolve(presentation=None):
    """The resolved pack for a deck: ``presentation.visual_style`` with its overrides applied."""
    presentation = presentation or {}
    declared = presentation.get('visual_style') or {}
    pack = declared.get('pack') or DEFAULT_PACK
    if pack not in PACKS:
        raise StyleError(f'unknown visual_style.pack {pack!r}')
    overrides = declared.get('overrides') or {}
    errors = validate_style({'pack': pack, 'overrides': overrides})
    if errors:
        raise StyleError('; '.join(errors))
    return _merge(PACKS[pack], unflatten(overrides))


def capabilities():
    """What an authoring agent may choose, published next to the other compiler capabilities."""
    return {'contract': 'totalpipe.visual-style', 'default': DEFAULT_PACK,
            'packs': {name: {'tokens': sorted(flatten(pack)),
                             'page': pack['page']['sparse_balance']}
                      for name, pack in PACKS.items()},
            'paths': ['presentation.visual_style.pack', 'presentation.visual_style.overrides'],
            'usage': 'Set presentation.visual_style={"pack":"academic"} for a research deck; override a '
                     'token with a dotted key, e.g. {"graphic.node.stroke_width": 1}. Composition stays '
                     'in Deck IR; the pack only decides how it is drawn.'}


def named_color(token, theme):
    """Resolve a palette token against the deck theme; explicit colours pass through."""
    if token == 'accent':
        return theme.get('accent', '#C2410C')
    if token == 'foreground':
        return theme.get('foreground', '#142735')
    if token == 'muted':
        return theme.get('muted') or _mix(theme.get('foreground', '#142735'),
                                          theme.get('background', '#FFFFFF'), .45)
    if token == 'none':
        return 'none'
    return token


def _mix(first, second, share):
    return '#' + ''.join(f'{round(int(first[k:k+2], 16)*(1-share)+int(second[k:k+2], 16)*share):02X}'
                         for k in (1, 3, 5))


def tint(accent, background, mix):
    return _mix(accent, background, mix)


def node_style(theme, tone='default'):
    """Concrete node values for the deck style, including the emphasis override."""
    style = (theme or {}).get('_visual_style') or PACKS[DEFAULT_PACK]
    node = dict(style['graphic']['node'])
    if tone == 'emphasis':
        node.update(style['graphic']['emphasis'])
    node['fill'] = _fill_value(node.get('fill', 'tint'), theme)
    node['stroke'] = named_color(node.get('stroke', 'accent'), theme or {})
    return node


def _fill_value(value, theme):
    theme = theme or {}
    if value == 'none':
        return 'none'
    if value in ('tint', 'tint-strong'):
        return tint(theme.get('accent', '#C2410C'), theme.get('background', '#FFFFFF'),
                    .18 if value == 'tint-strong' else .08)
    return value


def edge_style(theme):
    style = (theme or {}).get('_visual_style') or PACKS[DEFAULT_PACK]
    edge = style['graphic']['edge']
    return named_color(edge.get('color', 'accent'), theme or {}), float(edge.get('width', 2.5))


def text_styles(theme):
    """Run-level inks for authored emphasis, highlight and citation, resolved against the theme."""
    style = (theme or {}).get('_visual_style') or PACKS[DEFAULT_PACK]
    text = style.get('text') or PACKS[DEFAULT_PACK]['text']
    return {'emphasis': named_color(text.get('emphasis', 'accent'), theme or {}),
            'highlight': named_color(text.get('highlight', '#FFF1A8'), theme or {}),
            'citation': named_color(text.get('citation', 'muted'), theme or {})}


def page_furniture(theme):
    """The footer rule and page-number inks a page is dressed in, resolved against the theme."""
    style = (theme or {}).get('_visual_style') or PACKS[DEFAULT_PACK]
    page = style.get('page') or PACKS[DEFAULT_PACK]['page']
    return {'furniture': page.get('furniture', 'rule'),
            'rule': named_color(page.get('footer_rule', '#D8DEE6'), theme or {}),
            'footer_ink': named_color(page.get('footer_ink', 'muted'), theme or {}),
            'number_ink': named_color(page.get('number_ink', 'muted'), theme or {}),
            'footer_size': float(page.get('footer_size', 20)),
            'number_size': float(page.get('number_size', 22))}
